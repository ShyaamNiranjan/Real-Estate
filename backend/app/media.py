"""Listing media: gallery, floor plans, hero image, walkthrough videos (docs/SCOPE.md 8.6–8.8, 9.4).

Flow: request an upload (signed URL locked to size and type) → browser uploads directly to storage
→ complete (we check what actually arrived). Images are re-encoded on the spot (EXIF and GPS
stripped); videos go to the processing queue. Drafts stay private; Publish copies to public.
"""

import io
import json
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import FileResponse
from PIL import Image, ImageOps
from pydantic import BaseModel, Field
from sqlalchemy import Row, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import tenant_session
from app.deps import Auth, in_workspace
from app.errors import ApiError, ErrorResponse
from app.listings import _editable, _load
from app.permissions import load_access
from app.plans import trial_video_max_bytes
from app.storage import LocalStorage, get_storage, private_to_public, verify_token

router = APIRouter(prefix="/api/v1/media", tags=["media"],
                   responses={k: {"model": ErrorResponse} for k in (401, 403, 404, 409, 422)})

IMAGE_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
VIDEO_TYPES = {"video/mp4": "mp4", "video/quicktime": "mov"}
IMAGE_MAX_BYTES = 25 * 1024 * 1024
VIDEO_MAX_BYTES = 2 * 1024 * 1024 * 1024
LIMITS = {"gallery": 40, "floor_plan": 10, "hero": 1, "video": 1}
IMAGE_SIZES = {"large": 2400, "thumb": 640}
Image.MAX_IMAGE_PIXELS = 80_000_000

NOT_FOUND = ApiError(404, "not_found", "That file doesn't exist.")


# ---------- schemas ----------


class UploadRequest(BaseModel):
    listing_id: UUID
    kind: Literal["gallery", "floor_plan", "hero", "video"]
    filename: str = Field(max_length=200)
    content_type: str
    size: int = Field(gt=0)
    aspect: Literal["landscape", "portrait"] | None = None


class UploadTargetOut(BaseModel):
    url: str
    method: str
    headers: dict[str, str]
    expires_in: int


class FramesOut(BaseModel):
    media_id: UUID
    count: int
    first: str
    middle: str
    last: str


class MediaOut(BaseModel):
    id: UUID
    listing_id: UUID | None
    kind: str
    aspect: str | None
    status: Literal["uploading", "processing", "ready", "failed"]
    original_name: str
    bytes: int
    width: int | None
    height: int | None
    duration_ms: int | None
    label: str
    alt: str
    sort_order: int
    warnings: list[str]
    error: str | None
    thumb_url: str | None
    large_url: str | None
    frames: FramesOut | None


class UploadOut(BaseModel):
    media: MediaOut
    upload: UploadTargetOut


class MediaPatch(BaseModel):
    label: str | None = Field(default=None, max_length=60)
    alt: str | None = Field(default=None, max_length=200)


class MediaOrder(BaseModel):
    listing_id: UUID
    kind: Literal["gallery", "floor_plan"]
    ids: list[UUID] = Field(max_length=60)


class FrameUrls(BaseModel):
    count: int
    urls: list[str]


# ---------- helpers ----------


def frame_key(prefix: str, size: str, n: int) -> str:
    return f"{prefix}/{size}/{n:04d}.webp"


def _out(s: Session, row: Row) -> MediaOut:
    storage = get_storage()
    variants = row.variants or {}
    thumb = large = None
    if row.status == "ready" and "large" in variants:
        large = storage.signed_url(variants["large"])
        thumb = storage.signed_url(variants["thumb"])
    frames = None
    if row.kind == "video":
        child = s.execute(
            text("SELECT * FROM media WHERE parent_id = :id AND kind = 'frames' AND deleted_at IS NULL AND status = 'ready'"),
            {"id": row.id},
        ).first()
        if child:
            count = child.variants["count"]
            frames = FramesOut(
                media_id=child.id, count=count,
                first=storage.signed_url(frame_key(child.key, "small", 1)),
                middle=storage.signed_url(frame_key(child.key, "small", max(1, count // 2))),
                last=storage.signed_url(frame_key(child.key, "small", count)),
            )
    return MediaOut(
        id=row.id, listing_id=row.listing_id, kind=row.kind, aspect=row.aspect, status=row.status,
        original_name=row.original_name, bytes=row.bytes, width=row.width, height=row.height,
        duration_ms=row.duration_ms, label=row.label, alt=row.alt, sort_order=row.sort_order,
        warnings=list(row.warnings or []), error=row.error, thumb_url=thumb, large_url=large, frames=frames,
    )


def _media(s: Session, media_id: UUID) -> Row:
    row = s.execute(text("SELECT * FROM media WHERE id = :id AND deleted_at IS NULL AND kind <> 'frames'"),
                    {"id": media_id}).first()
    if row is None:
        raise NOT_FOUND
    return row


def _touch_listing(s: Session, listing_id: UUID | None) -> None:
    if listing_id:
        s.execute(text("UPDATE listings SET updated_at = clock_timestamp() WHERE id = :id"), {"id": listing_id})


def soft_delete(s: Session, row: Row) -> None:
    """Marks the file and anything derived from it deleted and removes the private objects.
    Public copies stay: the live snapshot may still use them until the next Publish."""
    deleted = s.execute(
        text("""UPDATE media SET deleted_at = now() WHERE (id = :id OR parent_id = :id) AND deleted_at IS NULL
                RETURNING kind, key, variants"""),
        {"id": row.id},
    ).all()
    storage = get_storage()
    for kind, key, variants in deleted:
        if kind == "frames":
            storage.delete_prefix(key + "/")
        else:
            storage.delete([key, *(variants or {}).get("all", [])])


def process_image(s: Session, row: Row) -> None:
    """Re-encodes to WebP sizes with metadata (EXIF, GPS) stripped. A file that isn't a real image
    is refused here, so nothing else is ever served from our storage."""
    storage = get_storage()
    data = storage.read(row.key, IMAGE_MAX_BYTES + 1)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image = Image.open(io.BytesIO(data))
            if image.format not in ("JPEG", "PNG", "WEBP"):
                raise ValueError(image.format)
            image.load()
    except Exception:
        raise ApiError(422, "invalid_image", "That file isn't a JPEG, PNG or WebP image we can use.") from None
    image = ImageOps.exif_transpose(image)
    has_alpha = image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info)
    image = image.convert("RGBA" if has_alpha else "RGB")
    base = row.key.rsplit("/", 1)[0].replace("/orig", f"/img/{row.id}")
    variants, size = {}, None
    for name, edge in IMAGE_SIZES.items():
        copy = image.copy()
        copy.thumbnail((edge, edge), Image.LANCZOS)
        buffer = io.BytesIO()
        copy.save(buffer, "WEBP", quality=86 if name == "large" else 80, method=5)
        key = f"{base}/{name}.webp"
        storage.write(key, buffer.getvalue(), "image/webp")
        variants[name] = key
        if name == "large":
            size = copy.size
    variants["all"] = [variants["large"], variants["thumb"]]
    s.execute(
        text("""UPDATE media SET status = 'ready', width = :w, height = :h, variants = CAST(:v AS jsonb),
                       updated_at = now() WHERE id = :id"""),
        {"w": size[0], "h": size[1], "v": json.dumps(variants), "id": row.id},
    )


def walkthrough_state(s: Session, listing_id: UUID) -> str:
    """'ready' if any walkthrough has frames, 'processing' if one is on its way, else 'missing'."""
    rows = s.execute(
        text("""SELECT kind, status FROM media WHERE listing_id = :l AND kind IN ('video', 'frames')
                AND deleted_at IS NULL"""),
        {"l": listing_id},
    ).all()
    if any(r.kind == "frames" and r.status == "ready" for r in rows):
        return "ready"
    if any(r.kind == "video" and r.status in ("uploading", "processing") for r in rows):
        return "processing"
    return "missing"


def listing_media(s: Session, listing_id: UUID, public: bool) -> dict:
    """The listing's ready media as used in a snapshot. `public=True` (Publish) copies files to
    public storage (once per file; media is immutable) and uses permanent public URLs;
    `public=False` (owner's draft preview) uses short-lived signed URLs and copies nothing."""
    storage = get_storage()
    rows = s.execute(
        text("""SELECT * FROM media WHERE listing_id = :l AND deleted_at IS NULL AND status = 'ready'
                AND kind IN ('gallery', 'floor_plan', 'hero', 'frames') ORDER BY kind, sort_order, created_at"""),
        {"l": listing_id},
    ).all()
    if public:
        copies: list[tuple[str, str]] = []
        for row in rows:
            if row.public_key:
                continue
            if row.kind == "frames":
                count = row.variants["count"]
                copies += [(frame_key(row.key, size, n), private_to_public(frame_key(row.key, size, n)))
                           for size in ("large", "small") for n in range(1, count + 1)]
                key = private_to_public(row.key)
            else:
                copies += [(k, private_to_public(k)) for k in row.variants["all"]]
                key = private_to_public(row.variants["large"])
            s.execute(text("UPDATE media SET public_key = :p WHERE id = :id"), {"p": key, "id": row.id})
        with ThreadPoolExecutor(max_workers=16) as pool:
            list(pool.map(lambda pair: storage.copy(*pair), copies))

    def url(key: str) -> str:
        return storage.public_url(private_to_public(key)) if public else storage.signed_url(key)

    def image(row: Row) -> dict:
        v = row.variants
        return {"id": str(row.id), "url": url(v["large"]), "thumb_url": url(v["thumb"]),
                "width": row.width, "height": row.height, "label": row.label, "alt": row.alt}

    walkthrough = {}
    for row in rows:
        if row.kind != "frames":
            continue
        count = row.variants["count"]
        sets = {}
        for size in ("large", "small"):
            if public:
                frames = {"pattern": f"{storage.public_url(private_to_public(row.key))}/{size}/{{n}}.webp"}
            else:
                frames = {"urls": [url(frame_key(row.key, size, n)) for n in range(1, count + 1)]}
            sets[size] = {**frames, **row.variants[size]}
        walkthrough[row.aspect] = {"count": count, **sets}
    return {
        "gallery": [image(r) for r in rows if r.kind == "gallery"],
        "floor_plans": [image(r) for r in rows if r.kind == "floor_plan"],
        "hero_images": {str(r.id): image(r) for r in rows if r.kind in ("hero", "gallery")},
        "walkthrough": walkthrough,
    }


# ---------- endpoints ----------


@router.post("/uploads", status_code=201, response_model=UploadOut)
def request_upload(body: UploadRequest, auth: Auth = Depends(in_workspace)) -> UploadOut:
    is_video = body.kind == "video"
    types = VIDEO_TYPES if is_video else IMAGE_TYPES
    if body.content_type not in types:
        allowed = "MP4 or MOV" if is_video else "JPEG, PNG or WebP"
        raise ApiError(422, "unsupported_type", f"Upload a {allowed} file.")
    if is_video and body.aspect is None:
        raise ApiError(422, "aspect_required", "Say whether this walkthrough is landscape or portrait.")
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        _, ws, listing = _editable(s, auth, body.listing_id)
        max_bytes = VIDEO_MAX_BYTES if is_video else IMAGE_MAX_BYTES
        if is_video and ws.subscription_state in ("trialing", "none"):
            max_bytes = trial_video_max_bytes(s)
        if body.size > max_bytes:
            raise ApiError(422, "file_too_large", f"Files can be up to {max_bytes // (1024 * 1024)} MB.")
        if body.kind in ("gallery", "floor_plan"):
            count = s.execute(text("SELECT count(*) FROM media WHERE listing_id = :l AND kind = :k AND deleted_at IS NULL"),
                              {"l": listing.id, "k": body.kind}).scalar_one()
            if count >= LIMITS[body.kind]:
                raise ApiError(409, "too_many_files", f"A listing can have up to {LIMITS[body.kind]} of these.")
        media_id = uuid4()
        key = f"private/ws/{auth.workspace_id}/orig/{media_id}.{types[body.content_type]}"
        next_order = s.execute(text("SELECT coalesce(max(sort_order) + 1, 0) FROM media WHERE listing_id = :l AND kind = :k"),
                               {"l": listing.id, "k": body.kind}).scalar_one()
        s.execute(
            text("""INSERT INTO media (id, workspace_id, listing_id, kind, aspect, original_name, content_type, bytes,
                                       key, sort_order, created_by)
                    VALUES (:id, :w, :l, :k, :a, :n, :ct, :b, :key, :o, :u)"""),
            {"id": media_id, "w": auth.workspace_id, "l": listing.id, "k": body.kind,
             "a": body.aspect if is_video else None, "n": Path(body.filename).name[:200], "ct": body.content_type,
             "b": body.size, "key": key, "o": next_order, "u": auth.user_id},
        )
        target = get_storage().upload_target(key, body.content_type, body.size)
        return UploadOut(media=_out(s, _media(s, media_id)), upload=UploadTargetOut(**target.__dict__))


@router.post("/{media_id}/complete", response_model=MediaOut)
def complete_upload(media_id: UUID, auth: Auth = Depends(in_workspace)) -> MediaOut:
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        row = _media(s, media_id)
        _editable(s, auth, row.listing_id)
        if row.status != "uploading":
            return _out(s, row)
        info = get_storage().head(row.key)
        if info is None:
            raise ApiError(409, "upload_missing", "We didn't receive the file. Try uploading it again.")
        if info.size != row.bytes or info.content_type != row.content_type:
            get_storage().delete([row.key])
            raise ApiError(422, "upload_mismatch", "The uploaded file doesn't match what was announced.")
        if row.kind == "video":
            s.execute(text("UPDATE media SET status = 'processing', updated_at = now() WHERE id = :id"), {"id": row.id})
            s.execute(text("INSERT INTO processing_jobs (workspace_id, media_id, kind) VALUES (:w, :m, 'video')"),
                      {"w": auth.workspace_id, "m": row.id})
        else:
            process_image(s, row)
            if row.kind == "hero":
                for old in s.execute(text("""SELECT * FROM media WHERE listing_id = :l AND kind = 'hero'
                                             AND id <> :id AND deleted_at IS NULL"""),
                                     {"l": row.listing_id, "id": row.id}).all():
                    s.execute(text("UPDATE listing_hero SET image_media_id = NULL WHERE image_media_id = :m"), {"m": old.id})
                    soft_delete(s, old)
                s.execute(text("UPDATE listing_hero SET image_media_id = :m WHERE listing_id = :l"),
                          {"m": row.id, "l": row.listing_id})
        _touch_listing(s, row.listing_id)
        return _out(s, _media(s, media_id))


@router.get("", response_model=list[MediaOut])
def list_media(listing_id: UUID = Query(), auth: Auth = Depends(in_workspace)) -> list[MediaOut]:
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        load_access(s, auth.user_id, auth.workspace_id)
        _load(s, listing_id)
        rows = s.execute(
            text("""SELECT * FROM media WHERE listing_id = :l AND deleted_at IS NULL AND kind <> 'frames'
                    ORDER BY kind, sort_order, created_at"""),
            {"l": listing_id},
        ).all()
        return [_out(s, r) for r in rows]


@router.patch("/{media_id}", response_model=MediaOut)
def update_media(media_id: UUID, body: MediaPatch, auth: Auth = Depends(in_workspace)) -> MediaOut:
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        row = _media(s, media_id)
        _editable(s, auth, row.listing_id)
        changes = body.model_dump(exclude_unset=True, exclude_none=True)
        if changes:
            s.execute(text(f"UPDATE media SET {', '.join(f'{k} = :{k}' for k in changes)}, updated_at = now() WHERE id = :id"),
                      {**{k: v.strip() for k, v in changes.items()}, "id": media_id})
            _touch_listing(s, row.listing_id)
        return _out(s, _media(s, media_id))


@router.put("/order", response_model=list[MediaOut])
def reorder_media(body: MediaOrder, auth: Auth = Depends(in_workspace)) -> list[MediaOut]:
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        _editable(s, auth, body.listing_id)
        current = set(s.execute(text("SELECT id FROM media WHERE listing_id = :l AND kind = :k AND deleted_at IS NULL"),
                                {"l": body.listing_id, "k": body.kind}).scalars())
        if set(body.ids) != current or len(body.ids) != len(current):
            raise ApiError(422, "invalid_order", "Send every file of this kind exactly once.")
        for order, media_id in enumerate(body.ids):
            s.execute(text("UPDATE media SET sort_order = :o WHERE id = :id"), {"o": order, "id": media_id})
        _touch_listing(s, body.listing_id)
        rows = s.execute(text("SELECT * FROM media WHERE id = ANY(:ids) ORDER BY sort_order"), {"ids": body.ids}).all()
        return [_out(s, r) for r in rows]


@router.delete("/{media_id}", status_code=204)
def delete_media(media_id: UUID, auth: Auth = Depends(in_workspace)) -> Response:
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        row = _media(s, media_id)
        _editable(s, auth, row.listing_id)
        s.execute(text("UPDATE listing_hero SET image_media_id = NULL WHERE image_media_id = :m"), {"m": media_id})
        soft_delete(s, row)
        _touch_listing(s, row.listing_id)
    return Response(status_code=204)


@router.get("/{media_id}/frames", response_model=FrameUrls)
def frame_urls(media_id: UUID, size: Literal["small", "large"] = "small",
               auth: Auth = Depends(in_workspace)) -> FrameUrls:
    """Signed frame URLs for the Studio preview of a draft walkthrough."""
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        load_access(s, auth.user_id, auth.workspace_id)
        row = s.execute(text("SELECT * FROM media WHERE id = :id AND kind = 'frames' AND deleted_at IS NULL"),
                        {"id": media_id}).first()
        if row is None or row.status != "ready":
            raise NOT_FOUND
        storage = get_storage()
        count = row.variants["count"]
        return FrameUrls(count=count, urls=[storage.signed_url(frame_key(row.key, size, n)) for n in range(1, count + 1)])


# ---------- local storage stand-in (development only) ----------

local_router = APIRouter(prefix="/api/v1/media/local", include_in_schema=False)


def _local() -> LocalStorage:
    storage = get_storage()
    if not isinstance(storage, LocalStorage):
        raise ApiError(404, "not_found", "Not found.")
    return storage


@local_router.put("/upload/{token}", status_code=200)
async def local_upload(token: str, request: Request) -> Response:
    storage = _local()
    claim = verify_token(token)
    if not claim or claim.get("op") != "put":
        raise ApiError(403, "invalid_upload_link", "This upload link has expired.")
    if request.headers.get("content-type") != claim["ct"]:
        raise ApiError(403, "invalid_upload_link", "The file type doesn't match this upload link.")
    body, limit = bytearray(), claim["size"]
    async for chunk in request.stream():
        body += chunk
        if len(body) > limit:
            raise ApiError(403, "invalid_upload_link", "The file is larger than announced.")
    if len(body) != limit:
        raise ApiError(403, "invalid_upload_link", "The file size doesn't match this upload link.")
    storage.write(claim["key"], bytes(body), claim["ct"])
    return Response(status_code=200)


@local_router.get("/file/{token}")
def local_private_file(token: str) -> FileResponse:
    storage = _local()
    claim = verify_token(token)
    if not claim or claim.get("op") != "get":
        raise ApiError(403, "expired_link", "This link has expired.")
    info = storage.head(claim["key"])
    if info is None:
        raise NOT_FOUND
    return FileResponse(storage._path(claim["key"]), media_type=info.content_type,
                        headers={"Cache-Control": "private, max-age=3600"})


@local_router.get("/public/{key:path}")
def local_public_file(key: str) -> FileResponse:
    storage = _local()
    full = f"public/{key}"
    try:
        info = storage.head(full)
    except ValueError:
        info = None
    if info is None:
        raise NOT_FOUND
    return FileResponse(storage._path(full), media_type=info.content_type,
                        headers={"Cache-Control": "public, max-age=31536000, immutable"})

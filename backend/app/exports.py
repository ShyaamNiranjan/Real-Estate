"""'Download everything' (docs/SCOPE.md 11): one zip with every listing's text, original videos,
photos and floor plans, the profile, and all enquiries. Admin only, available in every state
(including offline), built in the background, downloadable for 7 days."""

import json
import logging
import re
import tempfile
import zipfile
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text

from app import email as mail
from app.config import get_settings
from app.db import tenant_session
from app.deps import Auth, in_workspace
from app.enquiries import enquiries_csv
from app.errors import ApiError, ErrorResponse
from app.permissions import load_access
from app.storage import get_storage

log = logging.getLogger("scrollwalk.exports")

router = APIRouter(
    prefix="/api/v1/export",
    tags=["export"],
    responses={k: {"model": ErrorResponse} for k in (401, 403, 409, 429)},
)

AVAILABLE_FOR = timedelta(days=7)
PER_DAY = 3
README = """Your Scrollwalk data

workspace.json        your profile, contact details and compliance settings
listings/<address>/   each listing: listing.json (all text, sections, captions) and its original
                      videos, photos and floor plans
enquiries.csv         every enquiry you've received (opens in Excel, Numbers or Google Sheets)

Generated {date}.
"""


class ExportOut(BaseModel):
    id: UUID
    status: Literal["queued", "running", "ready", "failed", "expired"]
    created_at: datetime
    finished_at: datetime | None
    expires_at: datetime | None
    bytes: int
    download_url: str | None


def _out(row) -> ExportOut:
    url = None
    if row.status == "ready" and row.key:
        url = get_storage().signed_url(row.key, ttl=3600)
    return ExportOut(id=row.id, status=row.status, created_at=row.created_at, finished_at=row.finished_at,
                     expires_at=row.expires_at, bytes=row.bytes, download_url=url)


@router.post("", status_code=202, response_model=ExportOut)
def request_export(auth: Auth = Depends(in_workspace)) -> ExportOut:
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        load_access(s, auth.user_id, auth.workspace_id).require_admin()
        s.execute(text("SELECT 1 FROM workspaces WHERE id = :w FOR UPDATE"), {"w": auth.workspace_id})
        recent = s.execute(text("""SELECT count(*) FILTER (WHERE status IN ('queued', 'running')) AS busy,
                                          count(*) FILTER (WHERE created_at > now() - interval '1 day') AS today
                                   FROM exports""")).one()
        if recent.busy:
            raise ApiError(409, "export_in_progress", "Your download is already being prepared. We'll email you.")
        if recent.today >= PER_DAY:
            raise ApiError(429, "export_limit", "You've made 3 downloads today. Try again tomorrow.")
        export_id = uuid4()
        s.execute(text("INSERT INTO exports (id, workspace_id, requested_by) VALUES (:id, :w, :u)"),
                  {"id": export_id, "w": auth.workspace_id, "u": auth.user_id})
        return _out(s.execute(text("SELECT * FROM exports WHERE id = :id"), {"id": export_id}).one())


@router.get("", response_model=list[ExportOut])
def list_exports(auth: Auth = Depends(in_workspace)) -> list[ExportOut]:
    """Recent downloads; `download_url` is fresh each time (valid for an hour)."""
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        load_access(s, auth.user_id, auth.workspace_id).require_admin()
        return [_out(r) for r in s.execute(text("SELECT * FROM exports ORDER BY created_at DESC LIMIT 5")).all()]


# ---------- background ----------


def _safe(name: str, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip(" .")[:80]
    return cleaned or fallback


def _plain(v):
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, UUID):
        return str(v)
    if isinstance(v, Decimal):
        return float(v)
    return v


def _jsonable(row) -> dict:
    return {k: _plain(v) for k, v in row._mapping.items()}


def build_export(export_id: UUID, workspace_id: UUID, user_id: UUID) -> None:
    storage = get_storage()
    with tempfile.TemporaryDirectory(prefix="sw-export-") as tmp:
        zip_path = Path(tmp) / "export.zip"
        with tenant_session(user_id, workspace_id) as s:
            if not load_access(s, user_id, workspace_id).is_admin:
                raise PermissionError("requester is no longer the Admin")
            profile = s.execute(text("""SELECT w.username, w.display_name, w.country_code, w.currency_default,
                                               w.area_unit, w.timezone, w.plan_key, p.brokerage_name, p.contact_email,
                                               p.contact_phone, p.whatsapp, p.booking_url, p.style_preset,
                                               p.compliance, p.tagline, p.bio
                                        FROM workspaces w LEFT JOIN workspace_profiles p ON p.workspace_id = w.id
                                        WHERE w.id = :w"""), {"w": workspace_id}).one()
            listings = s.execute(text("""SELECT id, slug, title, subtitle, summary, location, price_amount,
                                                price_currency, price_label, bedrooms, bathrooms, area, area_unit,
                                                property_type, status, experience_type, compliance, seo_title,
                                                seo_description, published_at, created_at, updated_at
                                         FROM listings WHERE deleted_at IS NULL ORDER BY created_at""")).all()
            sections = s.execute(text("""SELECT listing_id, type, layout_variant, content, is_visible
                                         FROM listing_sections ORDER BY listing_id, sort_order""")).all()
            beats = s.execute(text("SELECT listing_id, at, label, text FROM walkthrough_beats ORDER BY listing_id, at")).all()
            media = s.execute(text("""SELECT listing_id, kind, aspect, key, original_name, label, alt, sort_order
                                      FROM media WHERE deleted_at IS NULL AND status = 'ready'
                                        AND parent_id IS NULL AND kind IN ('gallery', 'floor_plan', 'hero', 'video')
                                      ORDER BY listing_id, kind, sort_order""")).all()
            enquiries = enquiries_csv(s)
            now = s.execute(text("SELECT now()")).scalar_one()

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("README.txt", README.format(date=now.strftime("%d %B %Y")))
            z.writestr("workspace.json", json.dumps(_jsonable(profile), indent=2, ensure_ascii=False))
            z.writestr("enquiries.csv", enquiries)
            for listing in listings:
                folder = f"listings/{listing.slug}/"
                data = _jsonable(listing)
                data["sections"] = [{"type": x.type, "layout": x.layout_variant, "content": x.content,
                                     "visible": x.is_visible} for x in sections if x.listing_id == listing.id]
                data["captions"] = [{"at": float(b.at), "label": b.label, "text": b.text}
                                    for b in beats if b.listing_id == listing.id]
                z.writestr(folder + "listing.json", json.dumps(data, indent=2, ensure_ascii=False))
                for n, m in enumerate((m for m in media if m.listing_id == listing.id), start=1):
                    suffix = Path(m.key).suffix
                    name = _safe(Path(m.original_name).stem or m.label, f"{m.kind}-{n}")
                    local = Path(tmp) / f"item{suffix}"
                    try:
                        storage.download(m.key, local)
                    except Exception:  # noqa: BLE001 - one missing file shouldn't sink the whole download
                        log.warning("export %s: missing %s", export_id, m.key)
                        continue
                    z.write(local, f"{folder}{m.kind}/{n:02d}-{name}{suffix}", compress_type=zipfile.ZIP_STORED)
                    local.unlink()

        key = f"private/ws/{workspace_id}/exports/{export_id}.zip"
        storage.upload_file(zip_path, key, "application/zip")
        size = zip_path.stat().st_size
    with tenant_session(user_id, workspace_id) as s:
        s.execute(text("""UPDATE exports SET status = 'ready', key = :k, bytes = :b, finished_at = now(),
                                 expires_at = now() + :ttl WHERE id = :id"""),
                  {"k": key, "b": size, "ttl": AVAILABLE_FOR, "id": export_id})
        to = s.execute(text("SELECT email FROM users WHERE id = :u"), {"u": user_id}).scalar_one()
    mail.send(mail.lifecycle_email(to, "export_ready", get_settings().app_url))


def run_exports() -> int:
    """Builds every queued download. Run by the worker loop or `python -m app.jobs exports`."""
    done = 0
    while True:
        with tenant_session() as s:
            job = s.execute(text("SELECT * FROM claim_export()")).first()
        if job is None:
            return done
        try:
            build_export(job.id, job.workspace_id, job.requested_by)
            done += 1
        except Exception as exc:  # noqa: BLE001
            log.exception("export %s failed", job.id)
            try:
                with tenant_session(job.requested_by, job.workspace_id) as s:
                    s.execute(text("""UPDATE exports SET status = 'failed', error = :e, finished_at = now()
                                      WHERE id = :id"""), {"e": str(exc)[:300], "id": job.id})
            except Exception:  # noqa: BLE001
                log.exception("export %s: couldn't record failure", job.id)

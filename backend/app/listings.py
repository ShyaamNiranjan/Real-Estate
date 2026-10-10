"""Listings (docs/SCOPE.md 8.3–8.5, 8.8, 10, 11).

Drafts are edited freely; the public only ever sees the snapshot taken at the last Publish.
"""

import json
import re
import unicodedata
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy import Row, text
from sqlalchemy.orm import Session

from app import compliance, sections
from app.config import get_settings
from app.content import ListingContent
from app.db import tenant_session
from app.deps import Auth, in_workspace
from app.errors import ApiError, ErrorResponse
from app.permissions import Access, load_access
from app.plans import (
    FREE_PREVIEW_LISTINGS,
    LISTING_LIMITS,
    PUBLISH_STATES,
    READ_ONLY_STATES,
    TRIAL_LISTINGS_DEFAULT,
    TRIAL_LIVE_DAYS,
)
from app.workspace import (
    Blocker,
    blockers as workspace_blockers,
    compliance_items,
    contact_of,
    require_compliance_ack,
    workspace_row,
)

router = APIRouter(
    prefix="/api/v1/listings",
    tags=["listings"],
    responses={k: {"model": ErrorResponse} for k in (401, 403, 404, 409, 422)},
)

RESERVED_SLUGS = frozenset({"properties", "about", "contact", "neighbourhoods", "neighborhoods", "journal",
                            "preview", "report", "studio", "sold", "page", "search"})
LICENSED_PROFILES = frozenset({"US", "CA", "AU", "AE", "IN"})
SLUG = r"^[a-z0-9]+(-[a-z0-9]+)*$"
PLACEHOLDER = re.compile(r"\[Add\b[^\]]*\]")

NOT_FOUND = ApiError(404, "not_found", "That listing doesn't exist.")


# ---------- schemas ----------


class AgentOut(BaseModel):
    membership_id: UUID
    name: str


class SectionOut(BaseModel):
    id: UUID
    type: str
    layout_variant: str
    content: dict
    is_visible: bool
    ai_drafted: bool = Field(description="Written by AI and not edited since; label it for the agent to review.")


class HeroOut(BaseModel):
    enabled: bool
    image_media_id: UUID | None
    show_facts: bool
    show_price: bool


class BeatIn(BaseModel):
    at: float = Field(ge=0, le=1)
    label: str = Field(default="", max_length=40)
    text: str = Field(default="", max_length=200)


class ListingPermissions(BaseModel):
    can_edit: bool
    can_publish: bool
    can_submit: bool
    can_approve: bool
    can_delete: bool


class ListingSummary(BaseModel):
    id: UUID
    slug: str
    title: str
    location: str
    status: Literal["draft", "pending_approval", "published", "sold"]
    live_state: Literal["draft", "pending_approval", "live", "sold", "expired", "offline"]
    has_unpublished_changes: bool
    awaiting_approval: bool
    experience_type: str
    is_trial: bool
    trial_expires_at: datetime | None
    agent: AgentOut | None
    updated_at: datetime


class ListingOut(ListingSummary):
    subtitle: str
    summary: str
    price_amount: float | None
    price_currency: str
    price_label: str
    bedrooms: int | None
    bathrooms: float | None
    area: float | None
    area_unit: str
    property_type: str
    mobile_mode: str
    compliance: dict[str, str]
    compliance_fields: list[compliance.Field]
    seo_title: str
    seo_description: str
    published_at: datetime | None
    public_path: str | None
    preview_path: str
    sections: list[SectionOut]
    hero: HeroOut
    beats: list[BeatIn]
    permissions: ListingPermissions
    publish_blockers: list[Blocker]


class ListingCreate(BaseModel):
    title: str = Field(default="", max_length=120)
    experience_type: Literal["photo", "immersive"] = "immersive"


class ListingPatch(BaseModel):
    title: str | None = Field(default=None, max_length=120)
    subtitle: str | None = Field(default=None, max_length=160)
    summary: str | None = Field(default=None, max_length=6000)
    location: str | None = Field(default=None, max_length=160)
    price_amount: float | None = Field(default=None, ge=0, le=999_999_999_999)
    price_currency: str | None = Field(default=None, pattern=r"^[A-Za-z]{3}$")
    price_label: str | None = Field(default=None, max_length=40)
    bedrooms: int | None = Field(default=None, ge=0, le=99)
    bathrooms: float | None = Field(default=None, ge=0, le=99)
    area: float | None = Field(default=None, gt=0, le=999_999_999)
    area_unit: Literal["sqft", "sqm"] | None = None
    property_type: str | None = Field(default=None, max_length=40)
    experience_type: Literal["photo", "immersive"] | None = None
    mobile_mode: Literal["rotate", "fit", "fill"] | None = None
    compliance: dict[str, str] | None = None
    seo_title: str | None = Field(default=None, max_length=70)
    seo_description: str | None = Field(default=None, max_length=170)
    slug: str | None = Field(default=None, max_length=80)
    agent_member_id: UUID | None = None


class SectionCreate(BaseModel):
    type: sections.SectionType
    layout_variant: str | None = None
    after_id: UUID | None = None


class SectionPatch(BaseModel):
    layout_variant: str | None = None
    content: dict | None = None
    is_visible: bool | None = None


class SectionOrder(BaseModel):
    ids: list[UUID] = Field(max_length=50)


class HeroIn(BaseModel):
    enabled: bool
    show_facts: bool
    show_price: bool
    image_media_id: UUID | None = Field(default=None, description="Omit to keep the current image; null clears it.")


class PublishIn(BaseModel):
    acknowledge_compliance: bool = False


class ListingPreview(BaseModel):
    id: UUID
    status: str
    noindex: Literal[True] = True
    content: ListingContent


# ---------- helpers ----------


def slugify(value: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug[:60].strip("-") or "listing"


def _slug_taken(s: Session, slug: str, listing_id: UUID | None) -> bool:
    return bool(s.execute(
        text("""SELECT 1 FROM listings
                WHERE (slug = :s OR live_slug = :s) AND deleted_at IS NULL AND id IS DISTINCT FROM :id
                UNION ALL
                SELECT 1 FROM listing_slug_history WHERE slug = :s AND listing_id IS DISTINCT FROM :id
                LIMIT 1"""),
        {"s": slug, "id": listing_id},
    ).first())


def unique_slug(s: Session, base: str, listing_id: UUID | None = None) -> str:
    if base in RESERVED_SLUGS:
        base = f"{base}-home"
    candidate, n = base, 1
    while _slug_taken(s, candidate, listing_id):
        n += 1
        candidate = f"{base[:76]}-{n}"
    return candidate


def _load(s: Session, listing_id: UUID) -> Row:
    row = s.execute(
        text("""SELECT l.*, coalesce(nullif(u.display_name, ''), u.email) AS agent_name
                FROM listings l
                LEFT JOIN memberships m ON m.id = l.agent_member_id
                LEFT JOIN users u ON u.id = m.user_id
                WHERE l.id = :id AND l.deleted_at IS NULL"""),
        {"id": listing_id},
    ).first()
    if row is None:
        raise NOT_FOUND
    return row


def _is_own(listing: Row, access: Access) -> bool:
    if listing.agent_member_id is not None:
        return listing.agent_member_id == access.membership_id
    return listing.created_by == access.user_id


def _permissions(listing: Row, access: Access) -> ListingPermissions:
    own = _is_own(listing, access)
    can_edit = access.has("listings.edit_all") or (own and access.has("listings.edit_own"))
    can_publish = access.has("listings.publish_all") or (own and access.has("listings.publish_own"))
    return ListingPermissions(
        can_edit=can_edit,
        can_publish=can_publish,
        can_submit=can_edit and not can_publish,
        can_approve=access.has("listings.publish_all"),
        can_delete=access.has("listings.delete_all") or (own and access.has("listings.delete_own")),
    )


def _live_state(listing: Row, ws: Row) -> str:
    if listing.status in ("draft", "pending_approval"):
        return listing.status
    if ws.subscription_state == "offline":
        return "offline"
    if listing.trial_expires_at and listing.trial_expires_at <= datetime.now(UTC) and ws.subscription_state != "active":
        return "expired"
    return "live" if listing.status == "published" else "sold"


def _float(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _sections(s: Session, listing: Row, visible_only: bool = False) -> list[SectionOut]:
    rows = s.execute(
        text("SELECT * FROM listing_sections WHERE listing_id = :id ORDER BY sort_order"), {"id": listing.id}
    ).all()
    out = []
    for r in rows:
        if visible_only and not r.is_visible:
            continue
        content = dict(r.content)
        if r.type == "at_a_glance" and content.get("auto", True):
            content["items"] = sections.glance_items(listing)
        out.append(SectionOut(id=r.id, type=r.type, layout_variant=r.layout_variant, content=content,
                              is_visible=r.is_visible, ai_drafted=r.ai_drafted))
    return out


def _hero(s: Session, listing_id: UUID) -> HeroOut:
    row = s.execute(text("SELECT * FROM listing_hero WHERE listing_id = :id"), {"id": listing_id}).first()
    if row is None:
        return HeroOut(enabled=True, image_media_id=None, show_facts=True, show_price=True)
    return HeroOut(enabled=row.enabled, image_media_id=row.image_media_id, show_facts=row.show_facts,
                   show_price=row.show_price)


def _beats(s: Session, listing_id: UUID) -> list[BeatIn]:
    rows = s.execute(text("SELECT at, label, text FROM walkthrough_beats WHERE listing_id = :id ORDER BY at"),
                     {"id": listing_id}).all()
    return [BeatIn(at=float(r.at), label=r.label, text=r.text) for r in rows]


def _listing_fields(profile: str | None) -> list[compliance.Field]:
    if not profile:
        return []
    return [f for f in compliance.PROFILES[profile].fields if f.scope == "listing"]


def listing_blockers(s: Session, listing: Row, ws: Row) -> list[Blocker]:
    from app.media import walkthrough_state

    found = [Blocker(code=f"workspace.{b.code}", message=b.message) for b in workspace_blockers(ws)]
    if ws.subscription_state not in PUBLISH_STATES:
        found.insert(0, Blocker(code="plan", message="Choose a plan to publish."))
    if not listing.title.strip():
        found.append(Blocker(code="title", message="Give this listing a title."))
    if listing.experience_type == "immersive":
        state = walkthrough_state(s, listing.id)
        if state == "processing":
            found.append(Blocker(code="walkthrough_processing", message="Your walkthrough is still being prepared."))
        elif state == "missing":
            found.append(Blocker(code="walkthrough",
                                 message="Upload a walkthrough video, or switch this to a photo listing."))
    values = listing.compliance or {}
    for field in _listing_fields(ws.compliance_profile):
        if field.required and not str(values.get(field.key, "")).strip():
            found.append(Blocker(code=f"compliance.{field.key}", message=f"Add the {field.label.lower()}."))
    if _has_placeholders(s, listing):
        found.append(Blocker(code="placeholders", message="Fill in or remove the [Add …] placeholders."))
    return found


def _has_placeholders(s: Session, listing: Row) -> bool:
    texts = [listing.subtitle, listing.seo_title, listing.seo_description]
    texts += [json.dumps(c) for c in s.execute(
        text("SELECT content FROM listing_sections WHERE listing_id = :l AND is_visible"), {"l": listing.id}).scalars()]
    texts += list(s.execute(text("SELECT label || ' ' || text FROM walkthrough_beats WHERE listing_id = :l"),
                            {"l": listing.id}).scalars())
    return any(PLACEHOLDER.search(t or "") for t in texts)


def _summary_fields(listing: Row, ws: Row) -> dict:
    return dict(
        id=listing.id, slug=listing.slug, title=listing.title, location=listing.location, status=listing.status,
        live_state=_live_state(listing, ws),
        has_unpublished_changes=bool(listing.live_at and listing.updated_at > listing.live_at),
        awaiting_approval=listing.status == "pending_approval" or listing.changes_submitted_at is not None,
        experience_type=listing.experience_type, is_trial=listing.is_trial,
        trial_expires_at=listing.trial_expires_at,
        agent=AgentOut(membership_id=listing.agent_member_id, name=listing.agent_name) if listing.agent_member_id else None,
        updated_at=listing.updated_at,
    )


def build(s: Session, listing_id: UUID, access: Access) -> ListingOut:
    listing = _load(s, listing_id)
    ws = workspace_row(s, access.workspace_id)
    public_slug = listing.live_slug or listing.slug
    return ListingOut(
        **_summary_fields(listing, ws),
        subtitle=listing.subtitle, summary=listing.summary,
        price_amount=_float(listing.price_amount), price_currency=listing.price_currency,
        price_label=listing.price_label, bedrooms=listing.bedrooms, bathrooms=_float(listing.bathrooms),
        area=_float(listing.area), area_unit=listing.area_unit, property_type=listing.property_type,
        mobile_mode=listing.mobile_mode, compliance=listing.compliance or {},
        compliance_fields=_listing_fields(ws.compliance_profile),
        seo_title=listing.seo_title, seo_description=listing.seo_description, published_at=listing.published_at,
        public_path=f"/{ws.username}/{public_slug}" if ws.username else None,
        preview_path=f"/preview/{listing.id}",
        sections=_sections(s, listing), hero=_hero(s, listing.id), beats=_beats(s, listing.id),
        permissions=_permissions(listing, access),
        publish_blockers=listing_blockers(s, listing, ws),
    )


def _touch(s: Session, listing_id: UUID) -> None:
    s.execute(text("UPDATE listings SET updated_at = clock_timestamp() WHERE id = :id"), {"id": listing_id})


def _writable(s: Session, auth: Auth) -> tuple[Access, Row]:
    access = load_access(s, auth.user_id, auth.workspace_id)
    ws = workspace_row(s, auth.workspace_id)
    if ws.subscription_state in READ_ONLY_STATES:
        raise ApiError(403, "read_only", "Your subscription has ended, so the Studio is read-only. Resubscribe to edit.")
    return access, ws


def _editable(s: Session, auth: Auth, listing_id: UUID) -> tuple[Access, Row, Row]:
    access, ws = _writable(s, auth)
    listing = _load(s, listing_id)
    if not _permissions(listing, access).can_edit:
        raise ApiError(403, "permission_denied", "Your role doesn't allow editing this listing.")
    return access, ws, listing


def _snapshot(s: Session, listing: Row, ws: Row, public: bool = True) -> dict:
    """The listing as the public sees it. Self-contained (agent, contact, brand) so it renders even
    while the realtor site is offline."""
    from app.media import listing_media

    hero = _hero(s, listing.id)
    media = listing_media(s, listing.id, public)
    hero_image = media.pop("hero_images").get(str(hero.image_media_id)) if hero.image_media_id else None
    licence = ""
    if listing.agent_member_id:
        licence = s.execute(text("SELECT licence_number FROM memberships WHERE id = :m"),
                            {"m": listing.agent_member_id}).scalar_one_or_none() or ""
    values = listing.compliance or {}
    return {
        "title": listing.title, "subtitle": listing.subtitle, "location": listing.location,
        "price_amount": _float(listing.price_amount), "price_currency": listing.price_currency,
        "price_label": listing.price_label, "bedrooms": listing.bedrooms, "bathrooms": _float(listing.bathrooms),
        "area": _float(listing.area), "area_unit": listing.area_unit, "property_type": listing.property_type,
        "experience_type": listing.experience_type, "mobile_mode": listing.mobile_mode,
        "compliance": [{"key": f.key, "label": f.label, "value": str(values[f.key]).strip()}
                       for f in _listing_fields(ws.compliance_profile) if str(values.get(f.key, "")).strip()],
        "seo_title": listing.seo_title, "seo_description": listing.seo_description,
        "sections": [sec.model_dump(mode="json", exclude={"is_visible", "ai_drafted"}) for sec in _sections(s, listing, visible_only=True)],
        "hero": {**hero.model_dump(mode="json", exclude={"image_media_id"}), "image": hero_image},
        "beats": [b.model_dump() for b in _beats(s, listing.id)],
        "agent": {"name": listing.agent_name or ws.display_name, "licence_number": licence.strip()},
        "contact": contact_of(ws),
        "brand": {"display_name": ws.display_name, "brokerage_name": ws.brokerage_name,
                  "style_preset": ws.style_preset, "compliance": compliance_items(ws)},
        **media,
    }


def _go_live(s: Session, listing: Row, ws: Row, access: Access, acknowledge: bool) -> None:
    if (found := listing_blockers(s, listing, ws)):
        raise ApiError(409, "publish_blocked", found[0].message)
    require_compliance_ack(s, ws.id, access.user_id, acknowledge)
    if listing.live_slug and listing.live_slug != listing.slug:
        s.execute(text("""INSERT INTO listing_slug_history (workspace_id, slug, listing_id) VALUES (:w, :s, :l)
                          ON CONFLICT (workspace_id, slug) DO NOTHING"""),
                  {"w": ws.id, "s": listing.live_slug, "l": listing.id})
    trial_expiry = None
    if listing.is_trial and listing.trial_expires_at is None:
        trial_expiry = datetime.now(UTC) + timedelta(days=TRIAL_LIVE_DAYS)
    stamp = s.execute(text("SELECT clock_timestamp()")).scalar_one()
    s.execute(
        text("""UPDATE listings SET status = 'published', live = CAST(:live AS jsonb), live_slug = slug,
                       live_at = :stamp, updated_at = :stamp, changes_submitted_at = NULL,
                       published_at = coalesce(published_at, :stamp),
                       trial_expires_at = coalesce(trial_expires_at, :trial)
                WHERE id = :id"""),
        {"live": json.dumps(_snapshot(s, listing, ws)), "trial": trial_expiry, "stamp": stamp, "id": listing.id},
    )


def _can_create(ws: Row, active_count: int) -> None:
    state = ws.subscription_state
    if state in ("grace", "offline"):
        raise ApiError(403, "lapsed_no_new_listings", "Resubscribe to create new listings.")
    if state == "none" and ws.listings_created_total >= FREE_PREVIEW_LISTINGS:
        raise ApiError(403, "plan_required", "Your free preview is ready. Choose a plan to create more listings.")
    if state == "trialing" and ws.listings_created_total >= (ws.trial_listing_allowance or TRIAL_LISTINGS_DEFAULT):
        raise ApiError(403, "trial_limit", "You've used all your trial listings. Subscribe to create more.")
    if state == "active":
        limit = LISTING_LIMITS.get(ws.plan_key or "", 0)
        if limit is not None and active_count >= limit:
            raise ApiError(403, "listing_limit", "You've reached your plan's listing limit.")


def _agent_eligible(s: Session, ws: Row, membership_id: UUID) -> None:
    member = s.execute(
        text("""SELECT m.is_admin, m.licence_number,
                       EXISTS (SELECT 1 FROM role_permissions rp WHERE rp.role_id = m.role_id
                               AND rp.permission = 'listings.listing_agent') AS can_list
                FROM memberships m WHERE m.id = :m AND m.removed_at IS NULL"""),
        {"m": membership_id},
    ).first()
    if member is None:
        raise ApiError(422, "invalid_agent", "That person isn't on your team.")
    if not (member.is_admin or member.can_list):
        raise ApiError(422, "invalid_agent", "That person's role can't appear as the listing agent.")
    if not member.is_admin and ws.compliance_profile in LICENSED_PROFILES and not member.licence_number.strip():
        raise ApiError(422, "agent_needs_licence", "Add this agent's licence number before making them the listing agent.")


# ---------- endpoints ----------


@router.get("", response_model=list[ListingSummary])
def list_listings(auth: Auth = Depends(in_workspace)) -> list[ListingSummary]:
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        load_access(s, auth.user_id, auth.workspace_id)
        ws = workspace_row(s, auth.workspace_id)
        rows = s.execute(
            text("""SELECT l.*, coalesce(nullif(u.display_name, ''), u.email) AS agent_name
                    FROM listings l
                    LEFT JOIN memberships m ON m.id = l.agent_member_id
                    LEFT JOIN users u ON u.id = m.user_id
                    WHERE l.deleted_at IS NULL ORDER BY l.updated_at DESC""")
        ).all()
        return [ListingSummary(**_summary_fields(r, ws)) for r in rows]


@router.post("", status_code=201, response_model=ListingOut)
def create_listing(body: ListingCreate, auth: Auth = Depends(in_workspace)) -> ListingOut:
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        access, ws = _writable(s, auth)
        access.require("listings.create")
        s.execute(text("SELECT 1 FROM workspaces WHERE id = :w FOR UPDATE"), {"w": auth.workspace_id})
        active = s.execute(text("SELECT count(*) FROM listings WHERE deleted_at IS NULL AND status <> 'sold'")).scalar_one()
        _can_create(ws, active)
        agent = access.membership_id if access.has("listings.listing_agent") else None
        listing_id = s.execute(
            text("""INSERT INTO listings (workspace_id, agent_member_id, created_by, slug, title, price_currency,
                                          area_unit, experience_type, is_trial)
                    VALUES (:w, :agent, :u, :slug, :title, :cur, :unit, :exp, :trial) RETURNING id"""),
            {"w": auth.workspace_id, "agent": agent, "u": auth.user_id,
             "slug": unique_slug(s, slugify(body.title)), "title": body.title.strip(),
             "cur": ws.currency_default, "unit": ws.area_unit, "exp": body.experience_type,
             "trial": ws.subscription_state == "trialing"},
        ).scalar_one()
        for order, (section_type, content) in enumerate(sections.DEFAULT_SET):
            s.execute(
                text("""INSERT INTO listing_sections (workspace_id, listing_id, type, layout_variant, content, sort_order)
                        VALUES (:w, :l, :t, :v, CAST(:c AS jsonb), :o)"""),
                {"w": auth.workspace_id, "l": listing_id, "t": section_type, "v": sections.default_variant(section_type),
                 "c": json.dumps(sections.validate(section_type, content)), "o": order},
            )
        s.execute(text("INSERT INTO listing_hero (listing_id, workspace_id) VALUES (:l, :w)"),
                  {"l": listing_id, "w": auth.workspace_id})
        s.execute(text("UPDATE workspaces SET listings_created_total = listings_created_total + 1 WHERE id = :w"),
                  {"w": auth.workspace_id})
        return build(s, listing_id, access)


@router.get("/{listing_id}", response_model=ListingOut)
def get_listing(listing_id: UUID, auth: Auth = Depends(in_workspace)) -> ListingOut:
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        return build(s, listing_id, load_access(s, auth.user_id, auth.workspace_id))


@router.get("/{listing_id}/preview", response_model=ListingPreview)
def preview_listing(listing_id: UUID, auth: Auth = Depends(in_workspace)) -> ListingPreview:
    """The current draft exactly as it would publish, for the owner only (signed media URLs, noindex)."""
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        load_access(s, auth.user_id, auth.workspace_id)
        listing = _load(s, listing_id)
        ws = workspace_row(s, auth.workspace_id)
        return ListingPreview(id=listing.id, status=listing.status,
                              content=ListingContent.model_validate(_snapshot(s, listing, ws, public=False)))


@router.patch("/{listing_id}", response_model=ListingOut)
def update_listing(listing_id: UUID, body: ListingPatch, auth: Auth = Depends(in_workspace)) -> ListingOut:
    changes = body.model_dump(exclude_unset=True)
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        access, ws, listing = _editable(s, auth, listing_id)
        updates: dict = {}
        for key in ("title", "subtitle", "summary", "location", "price_label", "property_type", "seo_title",
                    "seo_description"):
            if key in changes:
                updates[key] = (changes[key] or "").strip()
        for key in ("price_amount", "bedrooms", "bathrooms", "area", "area_unit", "experience_type", "mobile_mode"):
            if key in changes and (changes[key] is not None or key in ("price_amount", "bedrooms", "bathrooms", "area")):
                value = changes[key]
                updates[key] = Decimal(str(value)) if isinstance(value, float) else value
        if changes.get("price_currency"):
            updates["price_currency"] = changes["price_currency"].upper()
        if "compliance" in changes:
            allowed = {f.key for f in _listing_fields(ws.compliance_profile)}
            values = {}
            for key, value in (changes["compliance"] or {}).items():
                if key not in allowed:
                    raise ApiError(422, "unknown_compliance_field", f"'{key}' isn't a field for this country.")
                values[key] = str(value).strip()[:200]
            updates["compliance"] = json.dumps(values)
        if "slug" in changes and changes["slug"] is not None:
            slug = changes["slug"].strip().lower()
            if not re.match(SLUG, slug) or slug in RESERVED_SLUGS:
                raise ApiError(422, "invalid_slug", "Use lowercase letters, numbers and single hyphens.")
            if slug != listing.slug:
                if _slug_taken(s, slug, listing_id):
                    raise ApiError(409, "slug_taken", "Another listing already uses that address.")
                updates["slug"] = slug
        if "agent_member_id" in changes:
            target = changes["agent_member_id"]
            if target != listing.agent_member_id:
                if not (access.has("listings.edit_all") or (target == access.membership_id and access.has("listings.listing_agent"))):
                    raise ApiError(403, "permission_denied", "Your role doesn't allow changing the listing agent.")
                if target is not None:
                    _agent_eligible(s, ws, target)
                updates["agent_member_id"] = target
        if updates:
            assignments = ", ".join(
                f"{k} = CAST(:{k} AS jsonb)" if k == "compliance" else f"{k} = :{k}" for k in updates
            )
            s.execute(text(f"UPDATE listings SET {assignments}, updated_at = clock_timestamp() WHERE id = :id"),
                      {**updates, "id": listing_id})
        return build(s, listing_id, access)


@router.delete("/{listing_id}", status_code=204)
def delete_listing(listing_id: UUID, auth: Auth = Depends(in_workspace)) -> Response:
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        access, _ = _writable(s, auth)
        listing = _load(s, listing_id)
        if not _permissions(listing, access).can_delete:
            raise ApiError(403, "permission_denied", "Your role doesn't allow deleting this listing.")
        s.execute(text("UPDATE listings SET deleted_at = now() WHERE id = :id"), {"id": listing_id})
    return Response(status_code=204)


# ----- sections -----


@router.post("/{listing_id}/sections", status_code=201, response_model=ListingOut)
def add_section(listing_id: UUID, body: SectionCreate, auth: Auth = Depends(in_workspace)) -> ListingOut:
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        access, _, _ = _editable(s, auth, listing_id)
        variant = body.layout_variant or sections.default_variant(body.type)
        if variant not in sections.variants(body.type):
            raise ApiError(422, "invalid_layout", "That layout isn't available for this section.")
        ids = list(s.execute(text("SELECT id FROM listing_sections WHERE listing_id = :l ORDER BY sort_order"),
                             {"l": listing_id}).scalars())
        if len(ids) >= 30:
            raise ApiError(409, "too_many_sections", "This listing already has the maximum number of sections.")
        position = ids.index(body.after_id) + 1 if body.after_id in ids else len(ids)
        new_id = s.execute(
            text("""INSERT INTO listing_sections (workspace_id, listing_id, type, layout_variant, content, sort_order)
                    VALUES (:w, :l, :t, :v, CAST(:c AS jsonb), 0) RETURNING id"""),
            {"w": auth.workspace_id, "l": listing_id, "t": body.type, "v": variant,
             "c": json.dumps(sections.validate(body.type, {}))},
        ).scalar_one()
        ids.insert(position, new_id)
        for order, section_id in enumerate(ids):
            s.execute(text("UPDATE listing_sections SET sort_order = :o WHERE id = :id"), {"o": order, "id": section_id})
        _touch(s, listing_id)
        return build(s, listing_id, access)


@router.patch("/{listing_id}/sections/{section_id}", response_model=ListingOut)
def update_section(listing_id: UUID, section_id: UUID, body: SectionPatch,
                   auth: Auth = Depends(in_workspace)) -> ListingOut:
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        access, _, _ = _editable(s, auth, listing_id)
        section = s.execute(text("SELECT * FROM listing_sections WHERE id = :id AND listing_id = :l"),
                            {"id": section_id, "l": listing_id}).first()
        if section is None:
            raise ApiError(404, "not_found", "That section doesn't exist.")
        updates: dict = {}
        if body.layout_variant is not None:
            if body.layout_variant not in sections.variants(section.type):
                raise ApiError(422, "invalid_layout", "That layout isn't available for this section.")
            updates["layout_variant"] = body.layout_variant
        if body.content is not None:
            try:
                updates["content"] = json.dumps(sections.validate(section.type, body.content))
            except ValueError as exc:
                raise ApiError(422, "invalid_content", str(exc).splitlines()[0]) from None
            updates["ai_drafted"] = False
        if body.is_visible is not None:
            updates["is_visible"] = body.is_visible
        if updates:
            assignments = ", ".join(f"{k} = CAST(:{k} AS jsonb)" if k == "content" else f"{k} = :{k}" for k in updates)
            s.execute(text(f"UPDATE listing_sections SET {assignments}, updated_at = now() WHERE id = :id"),
                      {**updates, "id": section_id})
            _touch(s, listing_id)
        return build(s, listing_id, access)


@router.delete("/{listing_id}/sections/{section_id}", response_model=ListingOut)
def delete_section(listing_id: UUID, section_id: UUID, auth: Auth = Depends(in_workspace)) -> ListingOut:
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        access, _, _ = _editable(s, auth, listing_id)
        deleted = s.execute(text("DELETE FROM listing_sections WHERE id = :id AND listing_id = :l"),
                            {"id": section_id, "l": listing_id}).rowcount
        if not deleted:
            raise ApiError(404, "not_found", "That section doesn't exist.")
        _touch(s, listing_id)
        return build(s, listing_id, access)


@router.put("/{listing_id}/sections/order", response_model=ListingOut)
def reorder_sections(listing_id: UUID, body: SectionOrder, auth: Auth = Depends(in_workspace)) -> ListingOut:
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        access, _, _ = _editable(s, auth, listing_id)
        current = set(s.execute(text("SELECT id FROM listing_sections WHERE listing_id = :l"), {"l": listing_id}).scalars())
        if set(body.ids) != current or len(body.ids) != len(current):
            raise ApiError(422, "invalid_order", "Send every section of this listing exactly once.")
        for order, section_id in enumerate(body.ids):
            s.execute(text("UPDATE listing_sections SET sort_order = :o WHERE id = :id"), {"o": order, "id": section_id})
        _touch(s, listing_id)
        return build(s, listing_id, access)


# ----- hero and beats -----


@router.put("/{listing_id}/hero", response_model=ListingOut)
def update_hero(listing_id: UUID, body: HeroIn, auth: Auth = Depends(in_workspace)) -> ListingOut:
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        access, _, _ = _editable(s, auth, listing_id)
        s.execute(
            text("""INSERT INTO listing_hero (listing_id, workspace_id, enabled, show_facts, show_price)
                    VALUES (:l, :w, :e, :f, :p)
                    ON CONFLICT (listing_id) DO UPDATE SET enabled = :e, show_facts = :f, show_price = :p"""),
            {"l": listing_id, "w": auth.workspace_id, "e": body.enabled, "f": body.show_facts, "p": body.show_price},
        )
        if "image_media_id" in body.model_fields_set:
            if body.image_media_id is not None:
                ok = s.execute(
                    text("""SELECT 1 FROM media WHERE id = :m AND listing_id = :l AND kind IN ('hero', 'gallery')
                            AND status = 'ready' AND deleted_at IS NULL"""),
                    {"m": body.image_media_id, "l": listing_id},
                ).first()
                if not ok:
                    raise ApiError(422, "invalid_hero_image", "Pick a ready photo from this listing.")
            s.execute(text("UPDATE listing_hero SET image_media_id = :m WHERE listing_id = :l"),
                      {"m": body.image_media_id, "l": listing_id})
        _touch(s, listing_id)
        return build(s, listing_id, access)


@router.put("/{listing_id}/beats", response_model=ListingOut)
def replace_beats(listing_id: UUID, beats: list[BeatIn], auth: Auth = Depends(in_workspace)) -> ListingOut:
    if len(beats) > 20:
        raise ApiError(422, "too_many_beats", "A walkthrough can have up to 20 captions.")
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        access, _, _ = _editable(s, auth, listing_id)
        s.execute(text("DELETE FROM walkthrough_beats WHERE listing_id = :l"), {"l": listing_id})
        for beat in beats:
            s.execute(text("""INSERT INTO walkthrough_beats (workspace_id, listing_id, at, label, text)
                              VALUES (:w, :l, :at, :label, :text)"""),
                      {"w": auth.workspace_id, "l": listing_id, "at": Decimal(str(round(beat.at, 4))),
                       "label": beat.label.strip(), "text": beat.text.strip()})
        _touch(s, listing_id)
        return build(s, listing_id, access)


# ----- status -----


@router.post("/{listing_id}/publish", response_model=ListingOut)
def publish(listing_id: UUID, body: PublishIn, auth: Auth = Depends(in_workspace)) -> ListingOut:
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        access, ws = _writable(s, auth)
        listing = _load(s, listing_id)
        perms = _permissions(listing, access)
        if not perms.can_publish:
            if perms.can_edit:
                raise ApiError(403, "approval_required", "Your role needs approval to publish. Submit it for approval.")
            raise ApiError(403, "permission_denied", "Your role doesn't allow publishing this listing.")
        _go_live(s, listing, ws, access, body.acknowledge_compliance)
        return build(s, listing_id, access)


@router.post("/{listing_id}/submit", response_model=ListingOut)
def submit_for_approval(listing_id: UUID, auth: Auth = Depends(in_workspace)) -> ListingOut:
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        access, ws = _writable(s, auth)
        listing = _load(s, listing_id)
        if not _permissions(listing, access).can_edit:
            raise ApiError(403, "permission_denied", "Your role doesn't allow editing this listing.")
        if listing.status != "draft" and not (listing.live_at and listing.updated_at > listing.live_at):
            raise ApiError(409, "nothing_to_submit", "There are no changes waiting to go live.")
        if (found := listing_blockers(s, listing, ws)):
            raise ApiError(409, "publish_blocked", found[0].message)
        if listing.status == "draft":
            s.execute(text("UPDATE listings SET status = 'pending_approval' WHERE id = :id"), {"id": listing_id})
        else:
            # Already live: the live version stays up while the changes wait for approval.
            s.execute(text("UPDATE listings SET changes_submitted_at = now() WHERE id = :id"), {"id": listing_id})
        return build(s, listing_id, access)


@router.post("/{listing_id}/approve", response_model=ListingOut)
def approve(listing_id: UUID, body: PublishIn, auth: Auth = Depends(in_workspace)) -> ListingOut:
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        access, ws = _writable(s, auth)
        access.require("listings.publish_all")
        listing = _load(s, listing_id)
        if listing.status != "pending_approval" and listing.changes_submitted_at is None:
            raise ApiError(409, "not_pending", "This listing isn't waiting for approval.")
        _go_live(s, listing, ws, access, body.acknowledge_compliance)
        return build(s, listing_id, access)


@router.post("/{listing_id}/unpublish", response_model=ListingOut)
def unpublish(listing_id: UUID, auth: Auth = Depends(in_workspace)) -> ListingOut:
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        access, _ = _writable(s, auth)
        listing = _load(s, listing_id)
        perms = _permissions(listing, access)
        if listing.changes_submitted_at is not None and perms.can_edit and not perms.can_publish:
            s.execute(text("UPDATE listings SET changes_submitted_at = NULL WHERE id = :id"), {"id": listing_id})
            return build(s, listing_id, access)
        withdrawing = listing.status == "pending_approval" and perms.can_edit
        if not (perms.can_publish or withdrawing):
            raise ApiError(403, "permission_denied", "Your role doesn't allow unpublishing this listing.")
        s.execute(text("UPDATE listings SET status = 'draft', changes_submitted_at = NULL WHERE id = :id"),
                  {"id": listing_id})
        return build(s, listing_id, access)


@router.post("/{listing_id}/sold", response_model=ListingOut)
def mark_sold(listing_id: UUID, auth: Auth = Depends(in_workspace)) -> ListingOut:
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        access, _ = _writable(s, auth)
        listing = _load(s, listing_id)
        if not _permissions(listing, access).can_publish:
            raise ApiError(403, "permission_denied", "Your role doesn't allow changing this listing's status.")
        if listing.status != "published":
            raise ApiError(409, "not_published", "Only a live listing can be marked as sold.")
        s.execute(text("UPDATE listings SET status = 'sold' WHERE id = :id"), {"id": listing_id})
        return build(s, listing_id, access)

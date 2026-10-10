"""Workspace setup: username, About you, contact methods, style, compliance, setup guide
(docs/SCOPE.md 5, 8.2, 8.13)."""

import json
import re
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import available_timezones

from fastapi import APIRouter, Depends, Query
from pydantic import AfterValidator, BaseModel, EmailStr, Field, HttpUrl
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import compliance, indexnow, usernames
from app import email as mail
from app.db import tenant_session
from app.deps import Auth, in_workspace
from app.errors import ApiError, ErrorResponse
from app.permissions import Access, load_access
from app.plans import PUBLISH_STATES
from app.ratelimit import Rule, enforce

router = APIRouter(
    prefix="/api/v1/workspace",
    tags=["workspace"],
    responses={k: {"model": ErrorResponse} for k in (400, 401, 403, 404, 409, 422, 429)},
)

USERNAME_CHECK = Rule("username-check", 60, 600)
CLAIM_STATES = frozenset({"trialing", "active", "grace"})
SETUP_STEPS = ("about_you", "contact", "style", "team")
SITE_PAGES = ("", "/properties", "/about", "/contact")
_TIMEZONES = frozenset(available_timezones())
_PHONE = re.compile(r"^\+[1-9]\d{6,14}$")


def _phone(value: str | None) -> str | None:
    if value in (None, ""):
        return None
    cleaned = re.sub(r"[\s().-]", "", value)
    if not _PHONE.match(cleaned):
        raise ValueError("Use the international format, starting with + and the country code.")
    return cleaned


def _timezone(value: str | None) -> str | None:
    if value is not None and value not in _TIMEZONES:
        raise ValueError("Unknown time zone.")
    return value


def _https(value: HttpUrl | None) -> HttpUrl | None:
    if value is not None and value.scheme != "https":
        raise ValueError("Use a secure link starting with https://")
    return value


Phone = Annotated[str | None, AfterValidator(_phone)]


# ---------- schemas ----------


class ProfileOut(BaseModel):
    brokerage_name: str
    photo_url: str | None
    contact_email: str | None
    contact_phone: str | None
    whatsapp: str | None
    booking_url: str | None
    style_preset: str
    compliance: dict[str, str]
    tagline: str
    bio: str
    featured_listing_ids: list[UUID]


class Blocker(BaseModel):
    code: str
    message: str


class WorkspaceOut(BaseModel):
    id: UUID
    username: str | None
    display_name: str
    kind: str
    plan_key: str | None
    subscription_state: str
    can_claim_username: bool
    country_code: str | None
    compliance_profile: str | None
    currency_default: str
    area_unit: str
    timezone: str
    site_published_at: str | None
    site_state: Literal["draft", "live", "offline"]
    site_has_unpublished_changes: bool
    site_blockers: list[Blocker]
    profile: ProfileOut
    setup: dict[str, Literal["done", "skipped"]]
    publish_blockers: list[Blocker]
    is_admin: bool
    my_permissions: list[str]


class ProfilePatch(BaseModel):
    display_name: str | None = Field(default=None, max_length=80)
    brokerage_name: str | None = Field(default=None, max_length=120)
    country_code: str | None = Field(default=None, pattern=r"^[A-Za-z]{2}$")
    currency_default: str | None = Field(default=None, pattern=r"^[A-Za-z]{3}$")
    area_unit: Literal["sqft", "sqm"] | None = None
    timezone: Annotated[str | None, AfterValidator(_timezone)] = None
    compliance: dict[str, Annotated[str, Field(max_length=200)]] | None = None
    contact_email: EmailStr | Literal[""] | None = None
    contact_phone: Phone = None
    whatsapp: Phone = None
    booking_url: Annotated[HttpUrl | None, AfterValidator(_https)] | Literal[""] = None
    style_preset: Literal["noir", "coastal", "terracotta", "evergreen"] | None = None
    tagline: str | None = Field(default=None, max_length=160)
    bio: str | None = Field(default=None, max_length=4000)


class FeaturedIn(BaseModel):
    listing_ids: list[UUID] = Field(max_length=8)


class SitePublishIn(BaseModel):
    acknowledge_compliance: bool = False


class UsernameCheck(BaseModel):
    username: str
    available: bool
    reason: Literal["too_short", "too_long", "invalid_characters", "reserved", "taken"] | None
    suggestions: list[str]


class UsernameClaim(BaseModel):
    username: str = Field(max_length=60)
    confirm_permanent: Literal[True]


class SetupStep(BaseModel):
    step: Literal["about_you", "contact", "style", "team"]
    status: Literal["done", "skipped"]


class ComplianceProfiles(BaseModel):
    profiles: list[compliance.Profile]
    eu_countries: list[str]


# ---------- helpers ----------

BRAND_FIELDS = {"display_name", "brokerage_name", "country_code", "currency_default", "area_unit",
                "timezone", "compliance", "style_preset"}
CONTACT_FIELDS = {"contact_email", "contact_phone", "whatsapp", "booking_url"}
PAGE_FIELDS = {"tagline", "bio"}


def _ensure_profile(s: Session, workspace_id: UUID) -> None:
    s.execute(text("INSERT INTO workspace_profiles (workspace_id) VALUES (:w) ON CONFLICT DO NOTHING"),
              {"w": workspace_id})


def _compliance_values(row) -> dict[str, str]:
    values = dict(row.compliance or {})
    values["brokerage_name"] = row.brokerage_name
    return values


def compliance_items(row) -> list[dict]:
    """The workspace's filled-in compliance fields with their labels, as shown in public footers."""
    values = _compliance_values(row)
    return [{"key": f.key, "label": f.label, "value": values[f.key]}
            for f in compliance.workspace_fields(row.compliance_profile) if str(values.get(f.key, "")).strip()]


def contact_of(row) -> dict:
    return {"email": row.contact_email, "phone": row.contact_phone, "whatsapp": row.whatsapp,
            "booking_url": row.booking_url}


def require_compliance_ack(s: Session, workspace_id: UUID, user_id: UUID, acknowledge: bool) -> None:
    """The first publish of anything (site or listing) needs the compliance notice ticked once."""
    if s.execute(text("SELECT 1 FROM compliance_acknowledgements WHERE workspace_id = :w"), {"w": workspace_id}).first():
        return
    if not acknowledge:
        raise ApiError(409, "compliance_ack_required",
                       "Confirm you're responsible for your site and listings meeting your local rules.")
    s.execute(text("INSERT INTO compliance_acknowledgements (workspace_id, user_id) VALUES (:w, :u)"),
              {"w": workspace_id, "u": user_id})


def blockers(row) -> list[Blocker]:
    found = []
    if not row.username:
        found.append(Blocker(code="username", message="Choose your username."))
    if not row.display_name.strip():
        found.append(Blocker(code="display_name", message="Add the name buyers will see."))
    if not any([row.contact_email, row.contact_phone, row.whatsapp, row.booking_url]):
        found.append(Blocker(code="contact", message="Add at least one way for buyers to reach you."))
    if not row.compliance_profile:
        found.append(Blocker(code="country", message="Choose the country you work in."))
    for field in compliance.missing_workspace_fields(row.compliance_profile, _compliance_values(row)):
        found.append(Blocker(code=f"compliance.{field.key}", message=f"Add your {field.label.lower()}."))
    return found


def site_state(row) -> str:
    if row.subscription_state == "offline":
        return "offline"
    return "live" if row.site_live is not None else "draft"


def site_blockers(row) -> list[Blocker]:
    found = blockers(row)
    if row.subscription_state == "trialing":
        found.insert(0, Blocker(code="trial_no_site", message="Your trial covers listings. Subscribe to publish your website."))
    elif row.subscription_state not in PUBLISH_STATES:
        found.insert(0, Blocker(code="plan", message="Choose a plan to publish."))
    return found


def site_snapshot(row) -> dict:
    return {
        "display_name": row.display_name, "brokerage_name": row.brokerage_name, "tagline": row.tagline,
        "bio": row.bio, "photo_url": row.photo_url, "style_preset": row.style_preset,
        "country_code": row.country_code, "contact": contact_of(row), "compliance": compliance_items(row),
        "featured_listing_ids": [str(i) for i in row.featured_listing_ids or []],
    }


def workspace_row(s: Session, workspace_id: UUID):
    _ensure_profile(s, workspace_id)
    return s.execute(
        text("""SELECT w.*, p.brokerage_name, p.photo_url, p.contact_email, p.contact_phone, p.whatsapp,
                       p.booking_url, p.style_preset, p.compliance, p.setup, p.tagline, p.bio,
                       p.featured_listing_ids, p.updated_at AS profile_updated_at
                FROM workspaces w JOIN workspace_profiles p ON p.workspace_id = w.id
                WHERE w.id = :w"""),
        {"w": workspace_id},
    ).one()


def load_workspace(s: Session, access: Access) -> WorkspaceOut:
    row = workspace_row(s, access.workspace_id)
    return WorkspaceOut(
        id=row.id, username=row.username, display_name=row.display_name, kind=row.kind,
        plan_key=row.plan_key, subscription_state=row.subscription_state,
        can_claim_username=row.username is None and row.subscription_state in CLAIM_STATES and access.is_admin,
        country_code=row.country_code, compliance_profile=row.compliance_profile,
        currency_default=row.currency_default, area_unit=row.area_unit, timezone=row.timezone,
        site_published_at=row.site_published_at.isoformat() if row.site_published_at else None,
        site_state=site_state(row),
        site_has_unpublished_changes=bool(row.site_live_at and row.profile_updated_at > row.site_live_at),
        site_blockers=site_blockers(row),
        profile=ProfileOut(
            brokerage_name=row.brokerage_name, photo_url=row.photo_url, contact_email=row.contact_email,
            contact_phone=row.contact_phone, whatsapp=row.whatsapp, booking_url=row.booking_url,
            style_preset=row.style_preset, compliance=row.compliance or {}, tagline=row.tagline, bio=row.bio,
            featured_listing_ids=list(row.featured_listing_ids or []),
        ),
        setup=row.setup or {},
        publish_blockers=blockers(row),
        is_admin=access.is_admin,
        my_permissions=sorted(access.effective()),
    )


# ---------- endpoints ----------


@router.get("", response_model=WorkspaceOut)
def get_workspace(auth: Auth = Depends(in_workspace)) -> WorkspaceOut:
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        return load_workspace(s, load_access(s, auth.user_id, auth.workspace_id))


@router.patch("/profile", response_model=WorkspaceOut)
def update_profile(body: ProfilePatch, auth: Auth = Depends(in_workspace)) -> WorkspaceOut:
    changes = body.model_dump(exclude_unset=True)
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        access = load_access(s, auth.user_id, auth.workspace_id)
        if changes.keys() & BRAND_FIELDS:
            access.require("site.edit_brand")
        if changes.keys() & CONTACT_FIELDS:
            access.require("site.edit_contact")
        if changes.keys() & PAGE_FIELDS:
            access.require("site.edit_pages")
        _ensure_profile(s, auth.workspace_id)
        current = s.execute(
            text("SELECT w.compliance_profile, p.compliance FROM workspaces w "
                 "JOIN workspace_profiles p ON p.workspace_id = w.id WHERE w.id = :w"),
            {"w": auth.workspace_id},
        ).one()

        ws: dict = {}
        if "display_name" in changes:
            ws["display_name"] = (changes["display_name"] or "").strip()
        if changes.get("country_code"):
            code = changes["country_code"].upper()
            profile = compliance.profile_for_country(code)
            ws["country_code"] = code
            if profile.key != current.compliance_profile:
                ws["compliance_profile"] = profile.key
                ws.setdefault("currency_default", profile.currency)
                ws.setdefault("area_unit", profile.area_unit)
        if changes.get("currency_default"):
            ws["currency_default"] = changes["currency_default"].upper()
        if changes.get("area_unit"):
            ws["area_unit"] = changes["area_unit"]
        if changes.get("timezone"):
            ws["timezone"] = changes["timezone"]
        if ws:
            assignments = ", ".join(f"{k} = :{k}" for k in ws)
            s.execute(text(f"UPDATE workspaces SET {assignments} WHERE id = :w"), {**ws, "w": auth.workspace_id})

        profile_key = ws.get("compliance_profile", current.compliance_profile)
        prof: dict = {}
        if "compliance" in changes or "compliance_profile" in ws:
            allowed = {f.key for f in compliance.workspace_fields(profile_key)} - {"brokerage_name"}
            merged = {} if "compliance_profile" in ws else dict(current.compliance or {})
            for key, value in (changes.get("compliance") or {}).items():
                if key not in allowed:
                    raise ApiError(422, "unknown_compliance_field", f"'{key}' isn't a field for this country.")
                merged[key] = value.strip()
            prof["compliance"] = merged
        for key in ("brokerage_name", "contact_email", "contact_phone", "whatsapp", "booking_url", "tagline", "bio"):
            if key in changes:
                value = changes[key]
                plain = key in ("brokerage_name", "tagline", "bio")
                prof[key] = (value or "").strip() if plain else (str(value).strip() if value else None)
        if changes.get("style_preset"):
            prof["style_preset"] = changes["style_preset"]
        if prof:
            params = {k: v for k, v in prof.items() if k != "compliance"}
            assignments = [f"{k} = :{k}" for k in params]
            if "compliance" in prof:
                assignments.append("compliance = CAST(:compliance AS jsonb)")
                params["compliance"] = json.dumps(prof["compliance"])
            s.execute(
                text(f"UPDATE workspace_profiles SET {', '.join(assignments)}, updated_at = now() WHERE workspace_id = :w"),
                {**params, "w": auth.workspace_id},
            )
        elif ws:
            s.execute(text("UPDATE workspace_profiles SET updated_at = now() WHERE workspace_id = :w"),
                      {"w": auth.workspace_id})
        return load_workspace(s, access)


@router.get("/username/check", response_model=UsernameCheck)
def check_username(username: str = Query(max_length=60), auth: Auth = Depends(in_workspace)) -> UsernameCheck:
    enforce((USERNAME_CHECK, str(auth.user_id)))
    name = usernames.normalize(username)
    reason = usernames.problem(name)
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        if reason is None and usernames.taken(s, [name]):
            reason = "taken"
        suggestions = usernames.suggestions(s, name) if reason in ("taken", "reserved") else []
    return UsernameCheck(username=name, available=reason is None, reason=reason, suggestions=suggestions)


@router.post("/username", response_model=WorkspaceOut)
def claim_username(body: UsernameClaim, auth: Auth = Depends(in_workspace)) -> WorkspaceOut:
    enforce((USERNAME_CHECK, str(auth.user_id)))
    name = usernames.normalize(body.username)
    if (reason := usernames.problem(name)) is not None:
        raise ApiError(422, f"username_{reason}", "That username can't be used.")
    try:
        with tenant_session(auth.user_id, auth.workspace_id) as s:
            access = load_access(s, auth.user_id, auth.workspace_id)
            access.require_admin()
            state = s.execute(text("SELECT username, subscription_state FROM workspaces WHERE id = :w"),
                              {"w": auth.workspace_id}).one()
            if state.username:
                raise ApiError(409, "username_permanent", "Your username is already set and can't be changed.")
            if state.subscription_state not in CLAIM_STATES:
                raise ApiError(403, "plan_required", "Choose a plan to claim your username.")
            if usernames.taken(s, [name]):
                raise ApiError(409, "username_taken", "That username was just taken. Try one of the suggestions.")
            s.execute(text("UPDATE workspaces SET username = :n WHERE id = :w"), {"n": name, "w": auth.workspace_id})
            return load_workspace(s, access)
    except IntegrityError:
        raise ApiError(409, "username_taken", "That username was just taken. Try one of the suggestions.")


@router.post("/setup", response_model=WorkspaceOut)
def record_setup_step(body: SetupStep, auth: Auth = Depends(in_workspace)) -> WorkspaceOut:
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        access = load_access(s, auth.user_id, auth.workspace_id)
        access.require_admin()
        _ensure_profile(s, auth.workspace_id)
        s.execute(
            text("UPDATE workspace_profiles SET setup = setup || jsonb_build_object(CAST(:k AS text), CAST(:v AS text)) "
                 "WHERE workspace_id = :w"),
            {"k": body.step, "v": body.status, "w": auth.workspace_id},
        )
        return load_workspace(s, access)


@router.put("/site/featured", response_model=WorkspaceOut)
def set_featured(body: FeaturedIn, auth: Auth = Depends(in_workspace)) -> WorkspaceOut:
    """Homes shown on the site's home page (up to 8, in order). Goes live with the next site Publish."""
    if len(set(body.listing_ids)) != len(body.listing_ids):
        raise ApiError(422, "duplicate_listing", "Each home can be featured once.")
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        access = load_access(s, auth.user_id, auth.workspace_id)
        access.require("site.edit_pages")
        found = s.execute(text("SELECT count(*) FROM listings WHERE id = ANY(:ids) AND deleted_at IS NULL"),
                          {"ids": body.listing_ids}).scalar_one()
        if found != len(body.listing_ids):
            raise ApiError(422, "invalid_listing", "One of those listings doesn't exist.")
        _ensure_profile(s, auth.workspace_id)
        s.execute(text("UPDATE workspace_profiles SET featured_listing_ids = :ids, updated_at = now() WHERE workspace_id = :w"),
                  {"ids": body.listing_ids, "w": auth.workspace_id})
        return load_workspace(s, access)


@router.post("/site/publish", response_model=WorkspaceOut)
def publish_site(body: SitePublishIn, auth: Auth = Depends(in_workspace)) -> WorkspaceOut:
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        access = load_access(s, auth.user_id, auth.workspace_id)
        access.require("site.publish")
        row = workspace_row(s, auth.workspace_id)
        if (found := site_blockers(row)):
            raise ApiError(409, "publish_blocked", found[0].message)
        require_compliance_ack(s, auth.workspace_id, auth.user_id, body.acknowledge_compliance)
        s.execute(
            text("""UPDATE workspaces SET site_live = CAST(:live AS jsonb), site_live_at = now(),
                           site_published_at = coalesce(site_published_at, now()) WHERE id = :w"""),
            {"live": json.dumps(site_snapshot(row)), "w": auth.workspace_id},
        )
        indexnow.submit(*(f"/{row.username}{p}" for p in SITE_PAGES))
        return load_workspace(s, access)


@router.post("/site/unpublish", response_model=WorkspaceOut)
def unpublish_site(auth: Auth = Depends(in_workspace)) -> WorkspaceOut:
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        access = load_access(s, auth.user_id, auth.workspace_id)
        access.require("site.publish")
        username = s.execute(text("""UPDATE workspaces SET site_live = NULL, site_live_at = NULL WHERE id = :w
                                     RETURNING username"""), {"w": auth.workspace_id}).scalar()
        indexnow.submit(*(f"/{username}{p}" for p in SITE_PAGES))
        return load_workspace(s, access)


class DeleteWorkspaceIn(BaseModel):
    password: str = Field(max_length=128)
    confirm: Literal["DELETE"] = Field(description='The Admin types "DELETE".')


class DeletionScheduled(BaseModel):
    status: Literal["scheduled"] = "scheduled"
    delete_after: datetime


@router.post("/delete", response_model=DeletionScheduled)
def request_deletion(body: DeleteWorkspaceIn, auth: Auth = Depends(in_workspace)) -> DeletionScheduled:
    """Admin only. The site goes offline now and everything is permanently deleted after 7 days.
    A running subscription must be cancelled first."""
    from app.auth import lookup_user
    from app.security import verify_password

    with tenant_session(auth.user_id, auth.workspace_id) as s:
        load_access(s, auth.user_id, auth.workspace_id).require_admin()
        email = s.execute(text("SELECT email FROM users WHERE id = :u"), {"u": auth.user_id}).scalar_one()
    user = lookup_user(email)
    if not verify_password(user.password_hash if user else None, body.password):
        raise ApiError(401, "invalid_password", "That password isn't right.")
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        status = s.execute(text("SELECT workspace_request_deletion()")).scalar_one()
        if status == "has_subscription":
            raise ApiError(409, "cancel_subscription_first", "Cancel your plan in Billing first.")
        if status != "scheduled":
            raise ApiError(403, "admin_only", "Only the workspace Admin can do this.")
        delete_after = s.execute(text("SELECT delete_after FROM workspaces WHERE id = :w"),
                                 {"w": auth.workspace_id}).scalar_one()
    mail.send(mail.Email(to=email, subject="Your Scrollwalk account will be deleted",
                         text=f"As you asked, your site is now offline and everything will be permanently deleted on "
                              f"{delete_after.strftime('%d %B %Y').lstrip('0')}. Changed your mind? Reply to this "
                              f"email before then."))
    return DeletionScheduled(delete_after=delete_after)


class Announcement(BaseModel):
    id: UUID
    title: str
    body: str
    starts_at: datetime
    ends_at: datetime | None


@router.get("/announcements", response_model=list[Announcement])
def announcements(auth: Auth = Depends(in_workspace)) -> list[Announcement]:
    """Studio banners from Scrollwalk. Remember dismissals in the browser by id."""
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        rows = s.execute(text("""SELECT id, title, body, starts_at, ends_at FROM announcements
                                 ORDER BY starts_at DESC LIMIT 5""")).all()
    return [Announcement(id=r.id, title=r.title, body=r.body, starts_at=r.starts_at, ends_at=r.ends_at) for r in rows]


@router.get("/compliance-profiles", response_model=ComplianceProfiles)
def compliance_profiles(_: Auth = Depends(in_workspace)) -> ComplianceProfiles:
    return ComplianceProfiles(profiles=list(compliance.PROFILES.values()), eu_countries=sorted(compliance.EU_COUNTRIES))

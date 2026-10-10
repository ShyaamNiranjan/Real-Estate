"""Super-Admin pages: customers, read-only customer view, trial invites, audit log
(docs/SCOPE.md 12). Reads go through the app_hq role; buyers' enquiry contents are never shown,
only counts. Opening a customer is recorded in the audit log."""

import re
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, EmailStr, Field, model_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app import email as mail
from app.config import get_settings
from app.db import hq_session
from app.errors import ApiError, ErrorResponse
from app.security import new_token, token_hash
from app.staff import Staff, audit, current_staff

router = APIRouter(
    prefix="/api/v1/hq",
    tags=["hq"],
    responses={k: {"model": ErrorResponse} for k in (401, 403, 404, 409, 422)},
)

State = Literal["none", "trialing", "active", "grace", "offline"]


# ---------- customers ----------


class CustomerRow(BaseModel):
    workspace_id: UUID
    username: str | None
    display_name: str
    admin_email: str | None
    admin_name: str | None
    plan_key: str | None
    state: State
    kind: str
    listings: int
    members: int
    created_at: datetime
    last_active_at: datetime | None


class CustomersOut(BaseModel):
    items: list[CustomerRow]
    total: int
    by_plan: dict[str, int] = Field(description="Paying (active/grace) workspaces per plan; the first is the most popular.")


def _like(q: str) -> str:
    return "%" + re.sub(r"([\\%_])", r"\\\1", q.strip()) + "%"


@router.get("/customers", response_model=CustomersOut)
def customers(
    q: str = Query(default="", max_length=100),
    state: State | None = None,
    plan: str | None = Query(default=None, max_length=30),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    staff: Staff = Depends(current_staff),
) -> CustomersOut:
    staff.require("customers.view")
    where = """w.deleted_at IS NULL
               AND (:q = '' OR w.username ILIKE :like OR w.display_name ILIKE :like OR u.email ILIKE :like)
               AND (CAST(:state AS text) IS NULL OR w.subscription_state = :state)
               AND (CAST(:plan AS text) IS NULL OR w.plan_key = :plan)"""
    params = {"q": q.strip(), "like": _like(q), "state": state, "plan": plan}
    base = """FROM workspaces w
              LEFT JOIN memberships m ON m.workspace_id = w.id AND m.is_admin AND m.removed_at IS NULL
              LEFT JOIN users u ON u.id = m.user_id"""
    with hq_session() as s:
        rows = s.execute(text(f"""
            SELECT w.id, w.username, w.display_name, w.plan_key, w.subscription_state, w.kind, w.created_at,
                   u.email AS admin_email, nullif(u.display_name, '') AS admin_name,
                   (SELECT count(*) FROM listings l WHERE l.workspace_id = w.id AND l.deleted_at IS NULL) AS listings,
                   (SELECT count(*) FROM memberships x WHERE x.workspace_id = w.id AND x.removed_at IS NULL) AS members,
                   (SELECT max(se.last_seen_at) FROM sessions se WHERE se.workspace_id = w.id) AS last_active_at
            {base} WHERE {where} ORDER BY w.created_at DESC LIMIT :limit OFFSET :offset"""),
            {**params, "limit": limit, "offset": offset}).all()
        total = s.execute(text(f"SELECT count(*) {base} WHERE {where}"), params).scalar_one()
        by_plan = s.execute(text("""SELECT plan_key, count(*) AS n FROM workspaces
                                    WHERE deleted_at IS NULL AND subscription_state IN ('active', 'grace')
                                      AND plan_key IS NOT NULL
                                    GROUP BY plan_key ORDER BY n DESC, plan_key""")).all()
    return CustomersOut(
        items=[CustomerRow(workspace_id=r.id, username=r.username, display_name=r.display_name,
                           admin_email=r.admin_email, admin_name=r.admin_name, plan_key=r.plan_key,
                           state=r.subscription_state, kind=r.kind, listings=r.listings, members=r.members,
                           created_at=r.created_at, last_active_at=r.last_active_at) for r in rows],
        total=total, by_plan={r.plan_key: r.n for r in by_plan},
    )


class CustomerMember(BaseModel):
    name: str
    email: str
    is_admin: bool
    role_name: str | None
    joined_at: datetime
    last_login_at: datetime | None


class CustomerListing(BaseModel):
    id: UUID
    title: str
    slug: str
    status: str
    is_trial: bool
    published_at: datetime | None
    trial_expires_at: datetime | None
    updated_at: datetime


class CustomerSubscription(BaseModel):
    provider: str
    plan_key: str
    interval: str
    status: str
    current_period_end: datetime | None
    cancel_at_period_end: bool


class CustomerTrial(BaseModel):
    invite_id: UUID
    invite_kind: str
    invite_code: str | None
    listings_allowed: int
    redeemed_at: datetime
    converted_at: datetime | None


class CustomerUsage(BaseModel):
    enquiries_total: int
    enquiries_30d: int
    page_views_30d: int
    ai_requests_30d: int
    ai_cost_usd_30d: float


class AuditEntry(BaseModel):
    id: int
    at: datetime
    staff_email: str
    action: str
    target_workspace_id: UUID | None
    target_user_id: UUID | None
    reason: str
    details: dict


class CustomerOut(BaseModel):
    workspace_id: UUID
    username: str | None
    display_name: str
    kind: str
    country_code: str | None
    plan_key: str | None
    state: State
    created_at: datetime
    site_live: bool
    listings_created_total: int
    trial_listing_allowance: int | None
    lapsed_at: datetime | None
    grace_ends_at: datetime | None
    offline_at: datetime | None
    delete_after: datetime | None
    subscription: CustomerSubscription | None
    trial: CustomerTrial | None
    members: list[CustomerMember]
    listings: list[CustomerListing]
    usage: CustomerUsage
    recent_staff_actions: list[AuditEntry]


def _audit_entry(r) -> AuditEntry:
    return AuditEntry(id=r.id, at=r.at, staff_email=r.staff_email, action=r.action,
                      target_workspace_id=r.target_workspace_id, target_user_id=r.target_user_id,
                      reason=r.reason, details=r.details)


@router.get("/customers/{workspace_id}", response_model=CustomerOut)
def customer(workspace_id: UUID, staff: Staff = Depends(current_staff)) -> CustomerOut:
    """Read-only view of one customer. Recorded in the audit log."""
    staff.require("customers.view")
    p = {"w": workspace_id}
    with hq_session() as s:
        ws = s.execute(text("SELECT * FROM workspaces WHERE id = :w AND deleted_at IS NULL"), p).first()
        if ws is None:
            raise ApiError(404, "not_found", "Customer not found.")
        members = s.execute(text("""
            SELECT coalesce(nullif(u.display_name, ''), u.email::text) AS name, u.email, m.is_admin, r.name AS role_name,
                   m.joined_at, u.last_login_at
            FROM memberships m JOIN users u ON u.id = m.user_id LEFT JOIN roles r ON r.id = m.role_id
            WHERE m.workspace_id = :w AND m.removed_at IS NULL ORDER BY m.is_admin DESC, m.joined_at"""), p).all()
        listings = s.execute(text("""
            SELECT id, title, slug, status, is_trial, published_at, trial_expires_at, updated_at FROM listings
            WHERE workspace_id = :w AND deleted_at IS NULL ORDER BY updated_at DESC LIMIT 200"""), p).all()
        sub = s.execute(text("SELECT * FROM subscriptions WHERE workspace_id = :w"), p).first()
        trial = s.execute(text("""
            SELECT r.invite_id, t.kind, t.code, t.listings_allowed, r.redeemed_at, r.converted_at
            FROM trial_redemptions r JOIN trial_invites t ON t.id = r.invite_id WHERE r.workspace_id = :w"""), p).first()
        usage = s.execute(text("""SELECT
            (SELECT count(*) FROM enquiries WHERE workspace_id = :w) AS enquiries_total,
            (SELECT count(*) FROM enquiries WHERE workspace_id = :w AND created_at > now() - interval '30 days') AS enquiries_30d,
            (SELECT count(*) FROM analytics_events WHERE workspace_id = :w AND event = 'pageview'
               AND created_at > now() - interval '30 days') AS views_30d,
            (SELECT count(*) FROM ai_generations WHERE workspace_id = :w AND created_at > now() - interval '30 days') AS ai_30d,
            (SELECT coalesce(sum(cost_usd), 0) FROM ai_generations WHERE workspace_id = :w
               AND created_at > now() - interval '30 days') AS ai_cost_30d"""), p).one()
        audit(s, staff, "customer.viewed", workspace_id=workspace_id)
        recent = s.execute(text("""SELECT * FROM audit_log WHERE target_workspace_id = :w
                                   ORDER BY at DESC, id DESC LIMIT 20"""), p).all()
    return CustomerOut(
        workspace_id=ws.id, username=ws.username, display_name=ws.display_name, kind=ws.kind,
        country_code=ws.country_code, plan_key=ws.plan_key, state=ws.subscription_state, created_at=ws.created_at,
        site_live=ws.site_live is not None, listings_created_total=ws.listings_created_total,
        trial_listing_allowance=ws.trial_listing_allowance, lapsed_at=ws.lapsed_at, grace_ends_at=ws.grace_ends_at,
        offline_at=ws.offline_at, delete_after=ws.delete_after,
        subscription=CustomerSubscription(provider=sub.provider, plan_key=sub.plan_key, interval=sub.billing_interval,
                                          status=sub.status, current_period_end=sub.current_period_end,
                                          cancel_at_period_end=sub.cancel_at_period_end) if sub else None,
        trial=CustomerTrial(invite_id=trial.invite_id, invite_kind=trial.kind, invite_code=trial.code,
                            listings_allowed=trial.listings_allowed, redeemed_at=trial.redeemed_at,
                            converted_at=trial.converted_at) if trial else None,
        members=[CustomerMember(name=m.name, email=m.email, is_admin=m.is_admin, role_name=m.role_name,
                                joined_at=m.joined_at, last_login_at=m.last_login_at) for m in members],
        listings=[CustomerListing(id=x.id, title=x.title, slug=x.slug, status=x.status, is_trial=x.is_trial,
                                  published_at=x.published_at, trial_expires_at=x.trial_expires_at,
                                  updated_at=x.updated_at) for x in listings],
        usage=CustomerUsage(enquiries_total=usage.enquiries_total, enquiries_30d=usage.enquiries_30d,
                            page_views_30d=usage.views_30d, ai_requests_30d=usage.ai_30d,
                            ai_cost_usd_30d=float(usage.ai_cost_30d)),
        recent_staff_actions=[_audit_entry(r) for r in recent],
    )


# ---------- trial invites ----------


class TrialInviteIn(BaseModel):
    kind: Literal["personal", "campaign"] = "personal"
    email: EmailStr | None = Field(default=None, description="Personal invites: the person's email.")
    code: str | None = Field(default=None, pattern=r"^[A-Za-z0-9-]{4,30}$", description="Campaign code, e.g. REZA30.")
    listings_allowed: int = Field(default=3, ge=1, le=20)
    expires_in_days: int = Field(default=30, ge=1, le=365)
    max_redemptions: int | None = Field(default=None, ge=1, le=100000, description="Campaign codes only; null = no cap.")
    note: str = Field(default="", max_length=300)

    @model_validator(mode="after")
    def _shape(self):
        if self.kind == "personal" and (not self.email or self.code or self.max_redemptions):
            raise ValueError("A personal invite needs an email and no code or cap.")
        if self.kind == "campaign" and (not self.code or self.email):
            raise ValueError("A campaign needs a code and no email.")
        return self


class TrialInviteOut(BaseModel):
    id: UUID
    kind: Literal["personal", "campaign"]
    email: str | None
    code: str | None
    listings_allowed: int
    max_redemptions: int | None
    redemptions: int
    conversions: int
    expires_at: datetime
    note: str
    status: Literal["open", "expired", "used", "revoked"]
    created_by: str
    created_at: datetime
    link: str | None = Field(default=None, description="Personal invites, only in the create response (shown once).")


_INVITES = """SELECT t.*, st.email AS creator,
                     (SELECT count(*) FROM trial_redemptions r WHERE r.invite_id = t.id AND r.converted_at IS NOT NULL) AS conversions,
                     CASE WHEN t.revoked_at IS NOT NULL THEN 'revoked'
                          WHEN t.expires_at <= now() THEN 'expired'
                          WHEN t.redemptions >= coalesce(t.max_redemptions, 2147483647) THEN 'used'
                          ELSE 'open' END AS status
              FROM trial_invites t JOIN staff st ON st.id = t.created_by"""


def _invite_out(r, link: str | None = None) -> TrialInviteOut:
    return TrialInviteOut(id=r.id, kind=r.kind, email=r.email, code=r.code, listings_allowed=r.listings_allowed,
                          max_redemptions=r.max_redemptions, redemptions=r.redemptions, conversions=r.conversions,
                          expires_at=r.expires_at, note=r.note, status=r.status, created_by=r.creator,
                          created_at=r.created_at, link=link)


def trial_email(to: str, link: str, listings: int, expires_at: datetime) -> mail.Email:
    return mail.Email(
        to=to, subject="You're invited to try Scrollwalk",
        text=f"You're invited to try Scrollwalk free: create up to {listings} listing walkthroughs, each live for "
             f"60 days after you publish it.\n\nStart your trial:\n{link}\n\n"
             f"This invitation works until {expires_at.strftime('%d %B %Y').lstrip('0')}.",
    )


@router.get("/trial-invites", response_model=list[TrialInviteOut])
def list_trial_invites(
    status: Literal["open", "expired", "used", "revoked"] | None = None,
    staff: Staff = Depends(current_staff),
) -> list[TrialInviteOut]:
    staff.require("trials.manage")
    with hq_session() as s:
        rows = s.execute(text(f"SELECT * FROM ({_INVITES}) x WHERE CAST(:st AS text) IS NULL OR x.status = :st "
                              "ORDER BY x.created_at DESC LIMIT 500"), {"st": status}).all()
    return [_invite_out(r) for r in rows]


@router.post("/trial-invites", status_code=201, response_model=TrialInviteOut)
def create_trial_invite(body: TrialInviteIn, staff: Staff = Depends(current_staff)) -> TrialInviteOut:
    staff.require("trials.manage")
    token = new_token() if body.kind == "personal" else None
    email = body.email.lower() if body.email else None
    try:
        with hq_session() as s:
            invite_id = s.execute(
                text("""INSERT INTO trial_invites (kind, email, token_hash, code, listings_allowed, max_redemptions,
                                                   expires_at, note, created_by)
                        VALUES (:k, :e, :h, :c, :l, :m, now() + :ttl, :n, :by) RETURNING id"""),
                {"k": body.kind, "e": email, "h": token_hash(token) if token else None,
                 "c": body.code.upper() if body.code else None, "l": body.listings_allowed,
                 "m": 1 if body.kind == "personal" else body.max_redemptions,
                 "ttl": timedelta(days=body.expires_in_days), "n": body.note.strip(), "by": staff.staff_id},
            ).scalar_one()
            audit(s, staff, "trial_invite.created", invite_id=str(invite_id), kind=body.kind, email=email,
                  code=body.code, listings_allowed=body.listings_allowed)
            row = s.execute(text(f"{_INVITES} WHERE t.id = :id"), {"id": invite_id}).one()
    except IntegrityError:
        raise ApiError(409, "code_taken", "That campaign code is already in use.") from None
    link = f"{get_settings().app_url}/trial#{token}" if token else None
    if link:
        mail.send(trial_email(email, link, row.listings_allowed, row.expires_at))
    return _invite_out(row, link)


@router.post("/trial-invites/{invite_id}/revoke", response_model=TrialInviteOut)
def revoke_trial_invite(invite_id: UUID, staff: Staff = Depends(current_staff)) -> TrialInviteOut:
    staff.require("trials.manage")
    with hq_session() as s:
        if not s.execute(text("UPDATE trial_invites SET revoked_at = coalesce(revoked_at, now()) WHERE id = :id"),
                         {"id": invite_id}).rowcount:
            raise ApiError(404, "not_found", "Invite not found.")
        audit(s, staff, "trial_invite.revoked", invite_id=str(invite_id))
        return _invite_out(s.execute(text(f"{_INVITES} WHERE t.id = :id"), {"id": invite_id}).one())


# ---------- audit log ----------


class AuditPage(BaseModel):
    items: list[AuditEntry]
    next_before_id: int | None = Field(description="Pass as before_id for the next (older) page.")


@router.get("/audit", response_model=AuditPage)
def audit_log(
    workspace_id: UUID | None = None,
    staff_id: UUID | None = None,
    action: str | None = Query(default=None, max_length=60),
    before_id: int | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    staff: Staff = Depends(current_staff),
) -> AuditPage:
    staff.require("audit.view")
    with hq_session() as s:
        rows = s.execute(text("""SELECT * FROM audit_log
                                 WHERE (CAST(:w AS uuid) IS NULL OR target_workspace_id = :w)
                                   AND (CAST(:sid AS uuid) IS NULL OR staff_id = :sid)
                                   AND (CAST(:a AS text) IS NULL OR action = :a)
                                   AND (CAST(:b AS bigint) IS NULL OR id < :b)
                                 ORDER BY id DESC LIMIT :n"""),
                         {"w": workspace_id, "sid": staff_id, "a": action, "b": before_id, "n": limit}).all()
    return AuditPage(items=[_audit_entry(r) for r in rows],
                     next_before_id=rows[-1].id if len(rows) == limit else None)

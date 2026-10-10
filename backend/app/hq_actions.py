"""Super-Admin actions (docs/SCOPE.md 12): trials, free plans, freezing, bans, deletion requests,
"log in as them", reports and takedowns, plans and settings, announcements, legal versions.

Every action takes a typed reason, runs through a narrow database function, and is written to the
audit log in the same transaction.
"""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import email as mail
from app import indexnow
from app.config import get_settings
from app.db import hq_session
from app.deps import cookie_names
from app.errors import ApiError, ErrorResponse
from app.security import csrf_token, new_token, token_hash
from app.staff import Staff, audit, current_staff

router = APIRouter(
    prefix="/api/v1/hq",
    tags=["hq"],
    responses={k: {"model": ErrorResponse} for k in (401, 403, 404, 409, 422)},
)

IMPERSONATION_TTL = timedelta(minutes=30)
Reason = Field(min_length=5, max_length=500, description="Why; stored in the audit log.")


class ReasonIn(BaseModel):
    reason: str = Reason


class Done(BaseModel):
    status: str


def _admin_emails(s: Session, workspace_id: UUID) -> list[str]:
    return list(s.execute(text("""SELECT u.email FROM memberships m JOIN users u ON u.id = m.user_id
                                  WHERE m.workspace_id = :w AND m.is_admin AND m.removed_at IS NULL
                                    AND u.deleted_at IS NULL"""), {"w": workspace_id}).scalars())


def _workspace_exists(s: Session, workspace_id: UUID) -> None:
    if s.execute(text("SELECT 1 FROM workspaces WHERE id = :w AND deleted_at IS NULL"), {"w": workspace_id}).first() is None:
        raise ApiError(404, "not_found", "Customer not found.")


# ---------- customer actions ----------


class ExtendTrialIn(BaseModel):
    days: int = Field(default=0, ge=0, le=180, description="Added to every trial listing's live period.")
    extra_listings: int = Field(default=0, ge=0, le=20)
    reason: str = Reason


@router.post("/customers/{workspace_id}/extend-trial", response_model=Done)
def extend_trial(workspace_id: UUID, body: ExtendTrialIn, staff: Staff = Depends(current_staff)) -> Done:
    staff.require("customers.manage")
    if not body.days and not body.extra_listings:
        raise ApiError(422, "nothing_to_extend", "Add days, listings or both.")
    with hq_session() as s:
        _workspace_exists(s, workspace_id)
        status = s.execute(text("SELECT hq_extend_trial(:w, :d, :n)"),
                           {"w": workspace_id, "d": body.days, "n": body.extra_listings}).scalar_one()
        if status != "extended":
            raise ApiError(409, "not_trialing", "This customer isn't on a trial.")
        audit(s, staff, "customer.trial_extended", workspace_id=workspace_id, reason=body.reason,
              days=body.days, extra_listings=body.extra_listings)
    return Done(status=status)


class GivePlanIn(BaseModel):
    plan_key: str = Field(max_length=30)
    reason: str = Reason


@router.post("/customers/{workspace_id}/give-plan", response_model=Done)
def give_plan(workspace_id: UUID, body: GivePlanIn, staff: Staff = Depends(current_staff)) -> Done:
    """A free (complimentary) plan with no payment. Not for customers already paying."""
    staff.require("customers.manage")
    with hq_session() as s:
        status = s.execute(text("SELECT hq_give_plan(:w, :p)"), {"w": workspace_id, "p": body.plan_key}).scalar_one()
        if status == "not_found":
            raise ApiError(404, "not_found", "Customer not found.")
        if status == "invalid_plan":
            raise ApiError(422, "invalid_plan", "Choose one of the plans.")
        if status == "has_subscription":
            raise ApiError(409, "has_subscription", "This customer pays through checkout; change the plan there.")
        audit(s, staff, "customer.plan_given", workspace_id=workspace_id, reason=body.reason, plan_key=body.plan_key)
    return Done(status=status)


@router.post("/customers/{workspace_id}/end-free-plan", response_model=Done)
def end_free_plan(workspace_id: UUID, body: ReasonIn, staff: Staff = Depends(current_staff)) -> Done:
    """Ends a free plan like a lapsed subscription: 30 days' grace, then offline."""
    staff.require("customers.manage")
    with hq_session() as s:
        _workspace_exists(s, workspace_id)
        status = s.execute(text("SELECT hq_end_free_plan(:w)"), {"w": workspace_id}).scalar_one()
        if status != "grace":
            raise ApiError(409, status, "This customer isn't on a free plan.")
        audit(s, staff, "customer.free_plan_ended", workspace_id=workspace_id, reason=body.reason)
        emails = _admin_emails(s, workspace_id)
        ends = s.execute(text("SELECT grace_ends_at FROM workspaces WHERE id = :w"), {"w": workspace_id}).scalar_one()
    mail.send(*(mail.lifecycle_email(to, "grace_start", get_settings().app_url,
                                     date=ends.strftime("%d %B %Y").lstrip("0")) for to in emails))
    return Done(status=status)


class FreezeIn(BaseModel):
    frozen: bool
    reason: str = Reason


@router.post("/customers/{workspace_id}/freeze", response_model=Done)
def freeze(workspace_id: UUID, body: FreezeIn, staff: Staff = Depends(current_staff)) -> Done:
    """Frozen: public pages disappear and the Studio refuses every change."""
    staff.require("customers.manage")
    with hq_session() as s:
        if not s.execute(text("SELECT hq_set_frozen(:w, :f, :r)"),
                         {"w": workspace_id, "f": body.frozen, "r": body.reason}).scalar():
            raise ApiError(404, "not_found", "Customer not found.")
        audit(s, staff, "customer.frozen" if body.frozen else "customer.unfrozen", workspace_id=workspace_id,
              reason=body.reason)
    return Done(status="frozen" if body.frozen else "active")


@router.post("/customers/{workspace_id}/delete", response_model=Done)
def schedule_deletion(workspace_id: UUID, body: ReasonIn, staff: Staff = Depends(current_staff)) -> Done:
    """Deletion request: offline now, permanently deleted after 7 days by the lifecycle job."""
    staff.require("customers.manage")
    with hq_session() as s:
        status = s.execute(text("SELECT hq_schedule_deletion(:w)"), {"w": workspace_id}).scalar_one()
        if status == "not_found":
            raise ApiError(404, "not_found", "Customer not found.")
        if status == "has_subscription":
            raise ApiError(409, "has_subscription", "Cancel their subscription first.")
        audit(s, staff, "customer.deletion_scheduled", workspace_id=workspace_id, reason=body.reason)
    return Done(status=status)


class BanIn(BaseModel):
    banned: bool
    reason: str = Reason


@router.post("/users/{user_id}/ban", response_model=Done)
def ban_user(user_id: UUID, body: BanIn, staff: Staff = Depends(current_staff)) -> Done:
    """Banning signs them out everywhere, blocks sign-in and freezes the workspaces they administer.
    Unbanning doesn't unfreeze; do that separately."""
    staff.require("content.moderate")
    with hq_session() as s:
        if not s.execute(text("SELECT hq_set_banned(:u, :b)"), {"u": user_id, "b": body.banned}).scalar():
            raise ApiError(404, "not_found", "User not found.")
        audit(s, staff, "user.banned" if body.banned else "user.unbanned", user_id=user_id, reason=body.reason)
    return Done(status="banned" if body.banned else "active")


@router.post("/users/{user_id}/sign-out", response_model=Done)
def sign_out_user(user_id: UUID, body: ReasonIn, staff: Staff = Depends(current_staff)) -> Done:
    """Ends every session (e.g. a customer who thinks someone else got in). They sign in again or reset
    their password."""
    staff.require("customers.manage")
    with hq_session() as s:
        count = s.execute(text("SELECT hq_revoke_sessions(:u)"), {"u": user_id}).scalar_one()
        audit(s, staff, "user.signed_out", user_id=user_id, reason=body.reason, sessions=count)
    return Done(status="signed_out")


class ImpersonateIn(BaseModel):
    reason: str = Field(min_length=10, max_length=500, description="Required, stored in the audit log.")


class ImpersonateOut(BaseModel):
    url: str
    expires_at: datetime


@router.post("/customers/{workspace_id}/impersonate", response_model=ImpersonateOut)
def impersonate(workspace_id: UUID, body: ImpersonateIn, response: Response,
                staff: Staff = Depends(current_staff)) -> ImpersonateOut:
    """"Log in as them": a 30-minute read-only Studio session as the workspace's Admin, set as the
    customer cookie in this browser. Every change is refused."""
    staff.require("customers.impersonate")
    token, session_id = new_token(), uuid4()
    with hq_session() as s:
        user_id = s.execute(text("SELECT hq_impersonate(:w, :st, :sid, :h, :ttl)"),
                            {"w": workspace_id, "st": staff.staff_id, "sid": session_id, "h": token_hash(token),
                             "ttl": IMPERSONATION_TTL}).scalar()
        if user_id is None:
            raise ApiError(404, "not_found", "Customer not found.")
        audit(s, staff, "customer.impersonated", workspace_id=workspace_id, user_id=user_id, reason=body.reason,
              session_id=str(session_id))
        expires = s.execute(text("SELECT now() + :ttl"), {"ttl": IMPERSONATION_TTL}).scalar_one()
    settings = get_settings()
    session_cookie, csrf_cookie = cookie_names()
    max_age = int(IMPERSONATION_TTL.total_seconds())
    response.set_cookie(session_cookie, token, max_age=max_age, path="/", secure=settings.cookie_secure,
                        httponly=True, samesite="lax")
    response.set_cookie(csrf_cookie, csrf_token(session_id), max_age=max_age, path="/",
                        secure=settings.cookie_secure, httponly=False, samesite="lax")
    return ImpersonateOut(url=f"{settings.app_url}/studio", expires_at=expires)


# ---------- payments, refunds and paid plan changes (through the merchant of record) ----------


class PaymentOut(BaseModel):
    id: UUID
    provider_payment_id: str
    kind: Literal["charge", "refund", "failed"]
    amount: Decimal
    fee: Decimal
    tax: Decimal
    currency: str
    occurred_at: datetime
    refunded: bool


@router.get("/customers/{workspace_id}/payments", response_model=list[PaymentOut])
def customer_payments(workspace_id: UUID, staff: Staff = Depends(current_staff)) -> list[PaymentOut]:
    staff.require("revenue.view")
    with hq_session() as s:
        rows = s.execute(text("""SELECT p.*, EXISTS (SELECT 1 FROM payments r WHERE r.kind = 'refund'
                                          AND r.provider = p.provider AND r.provider_payment_id = p.provider_payment_id)
                                          AS refunded
                                 FROM payments p WHERE p.workspace_id = :w ORDER BY p.occurred_at DESC LIMIT 200"""),
                         {"w": workspace_id}).all()
    return [PaymentOut(id=r.id, provider_payment_id=r.provider_payment_id, kind=r.kind, amount=r.amount, fee=r.fee,
                       tax=r.tax, currency=r.currency, occurred_at=r.occurred_at,
                       refunded=r.kind == "charge" and r.refunded) for r in rows]


def _subscription_ref(s: Session, workspace_id: UUID):
    from app.billing import _ref

    sub = s.execute(text("SELECT * FROM subscriptions WHERE workspace_id = :w"), {"w": workspace_id}).first()
    return sub, (_ref(sub) if sub else None)


class RefundIn(BaseModel):
    payment_id: UUID
    reason: str = Reason


@router.post("/customers/{workspace_id}/refund", response_model=Done)
def refund(workspace_id: UUID, body: RefundIn, staff: Staff = Depends(current_staff)) -> Done:
    """Full refund of one charge through the merchant of record. The plan itself isn't cancelled."""
    from app.billing import process_event
    from app.billing_providers import get_provider

    staff.require("billing.refund")
    provider = get_provider()
    with hq_session() as s:
        pay = s.execute(text("""SELECT * FROM payments WHERE id = :id AND workspace_id = :w AND kind = 'charge'"""),
                        {"id": body.payment_id, "w": workspace_id}).first()
        if pay is None:
            raise ApiError(404, "not_found", "Payment not found.")
        if pay.provider != provider.name:
            raise ApiError(409, "other_provider", "This payment was taken by a different provider.")
        if s.execute(text("""SELECT 1 FROM payments WHERE kind = 'refund' AND provider = :p
                             AND provider_payment_id = :id"""),
                     {"p": pay.provider, "id": pay.provider_payment_id}).first():
            raise ApiError(409, "already_refunded", "This payment was already refunded.")
        _, ref = _subscription_ref(s, workspace_id)
        if ref is None:
            raise ApiError(409, "no_subscription", "This customer has no subscription.")
    if process_event(provider.name, provider.refund(ref, pay.provider_payment_id, str(pay.amount))) == "rejected":
        raise ApiError(502, "refund_failed", "The payment provider didn't accept the refund.")
    with hq_session() as s:
        audit(s, staff, "customer.refunded", workspace_id=workspace_id, reason=body.reason,
              payment_id=str(body.payment_id), amount=str(pay.amount))
    return Done(status="refunded")


class ChangePlanIn(BaseModel):
    plan_key: str = Field(max_length=30)
    interval: Literal["month", "year"]
    reason: str = Reason


@router.post("/customers/{workspace_id}/change-plan", response_model=Done)
def change_paid_plan(workspace_id: UUID, body: ChangePlanIn, staff: Staff = Depends(current_staff)) -> Done:
    """Moves a paying customer to another plan through the merchant of record (it prorates).
    For customers without a subscription use give-plan."""
    from app.billing import process_event
    from app.billing_providers import get_provider

    staff.require("customers.manage")
    provider = get_provider()
    with hq_session() as s:
        sub, ref = _subscription_ref(s, workspace_id)
        if sub is None or sub.status not in ("active", "past_due"):
            raise ApiError(409, "no_subscription", "This customer isn't paying; use give-plan instead.")
        plan = s.execute(text("SELECT * FROM plans WHERE key = :k"), {"k": body.plan_key}).first()
        if plan is None:
            raise ApiError(422, "invalid_plan", "Choose one of the plans.")
        if sub.plan_key == plan.key and sub.billing_interval == body.interval:
            raise ApiError(409, "same_plan", "They're already on this plan.")
        price_id = (plan.provider_price_ids or {}).get(body.interval)
        if provider.name != "stub" and not price_id:
            raise ApiError(409, "plan_unavailable", "This plan has no price at the payment provider yet.")
    event = provider.change_plan(ref, plan.key, body.interval, price_id)
    if event is not None and process_event(provider.name, event) == "rejected":
        raise ApiError(502, "change_failed", "The payment provider didn't accept the change.")
    with hq_session() as s:
        audit(s, staff, "customer.plan_changed", workspace_id=workspace_id, reason=body.reason,
              plan_key=plan.key, interval=body.interval, previous=sub.plan_key)
    return Done(status="changed")


# ---------- reports and takedowns ----------


class ReportOut(BaseModel):
    id: UUID
    workspace_id: UUID
    username: str | None
    listing_id: UUID
    listing_title: str
    listing_path: str | None
    listing_taken_down: bool
    category: str
    details: str
    reporter_name: str
    reporter_email: str
    status: Literal["open", "dismissed", "actioned"]
    created_at: datetime
    resolved_at: datetime | None
    resolution: str


_REPORTS = """SELECT r.*, w.username, l.title AS listing_title, l.live_slug, l.taken_down_at
              FROM listing_reports r JOIN workspaces w ON w.id = r.workspace_id JOIN listings l ON l.id = r.listing_id"""


def _report_out(r) -> ReportOut:
    return ReportOut(id=r.id, workspace_id=r.workspace_id, username=r.username, listing_id=r.listing_id,
                     listing_title=r.listing_title,
                     listing_path=f"/{r.username}/{r.live_slug}" if r.username and r.live_slug else None,
                     listing_taken_down=r.taken_down_at is not None, category=r.category, details=r.details,
                     reporter_name=r.reporter_name, reporter_email=r.reporter_email, status=r.status,
                     created_at=r.created_at, resolved_at=r.resolved_at, resolution=r.resolution)


@router.get("/reports", response_model=list[ReportOut])
def list_reports(status: Literal["open", "dismissed", "actioned"] | None = "open",
                 staff: Staff = Depends(current_staff)) -> list[ReportOut]:
    staff.require("content.moderate")
    with hq_session() as s:
        rows = s.execute(text(f"{_REPORTS} WHERE CAST(:st AS text) IS NULL OR r.status = :st "
                              "ORDER BY r.created_at LIMIT 500"), {"st": status}).all()
    return [_report_out(r) for r in rows]


def _takedown(s: Session, staff: Staff, listing_id: UUID, reason: str) -> list[mail.Email]:
    row = s.execute(text("""SELECT l.title, l.workspace_id, l.live_slug, w.username FROM listings l
                            JOIN workspaces w ON w.id = l.workspace_id WHERE l.id = :l AND l.deleted_at IS NULL"""),
                    {"l": listing_id}).first()
    if row is None:
        raise ApiError(404, "not_found", "Listing not found.")
    s.execute(text("SELECT hq_takedown_listing(:l, :r)"), {"l": listing_id, "r": reason})
    if row.username and row.live_slug:
        indexnow.submit(f"/{row.username}/{row.live_slug}")
    s.execute(text("""UPDATE listing_reports SET status = 'actioned', resolved_at = now(), resolved_by = :st,
                             resolution = :r WHERE listing_id = :l AND status = 'open'"""),
              {"st": staff.staff_id, "r": reason, "l": listing_id})
    audit(s, staff, "listing.taken_down", workspace_id=row.workspace_id, reason=reason, listing_id=str(listing_id))
    return [mail.Email(to=to, subject=f"\"{row.title or 'Your listing'}\" was taken down",
                       text=f"We've taken down \"{row.title or 'your listing'}\" after a report.\n\nReason: {reason}\n\n"
                            "It's no longer public. If you think this is a mistake, reply to this email or write to "
                            "support@scrollwalk.com.")
            for to in _admin_emails(s, row.workspace_id)]


class ResolveIn(BaseModel):
    action: Literal["dismiss", "takedown"]
    reason: str = Reason


@router.post("/reports/{report_id}/resolve", response_model=ReportOut)
def resolve_report(report_id: UUID, body: ResolveIn, staff: Staff = Depends(current_staff)) -> ReportOut:
    staff.require("content.moderate")
    outgoing: list[mail.Email] = []
    with hq_session() as s:
        report = s.execute(text("SELECT * FROM listing_reports WHERE id = :id FOR UPDATE"), {"id": report_id}).first()
        if report is None:
            raise ApiError(404, "not_found", "Report not found.")
        if report.status != "open":
            raise ApiError(409, "already_resolved", "This report has already been handled.")
        if body.action == "takedown":
            outgoing = _takedown(s, staff, report.listing_id, body.reason)
        else:
            s.execute(text("""UPDATE listing_reports SET status = 'dismissed', resolved_at = now(), resolved_by = :st,
                                     resolution = :r WHERE id = :id"""),
                      {"st": staff.staff_id, "r": body.reason, "id": report_id})
            audit(s, staff, "report.dismissed", workspace_id=report.workspace_id, reason=body.reason,
                  report_id=str(report_id))
        out = _report_out(s.execute(text(f"{_REPORTS} WHERE r.id = :id"), {"id": report_id}).one())
    mail.send(*outgoing)
    return out


@router.post("/listings/{listing_id}/takedown", response_model=Done)
def takedown_listing(listing_id: UUID, body: ReasonIn, staff: Staff = Depends(current_staff)) -> Done:
    staff.require("content.moderate")
    with hq_session() as s:
        outgoing = _takedown(s, staff, listing_id, body.reason)
    mail.send(*outgoing)
    return Done(status="taken_down")


@router.post("/listings/{listing_id}/restore", response_model=Done)
def restore_listing(listing_id: UUID, body: ReasonIn, staff: Staff = Depends(current_staff)) -> Done:
    """Lets the realtor publish it again (it stays a draft until they do)."""
    staff.require("content.moderate")
    with hq_session() as s:
        workspace_id = s.execute(text("SELECT hq_restore_listing(:l)"), {"l": listing_id}).scalar()
        if workspace_id is None:
            raise ApiError(404, "not_found", "No taken-down listing with that id.")
        audit(s, staff, "listing.restored", workspace_id=workspace_id, reason=body.reason, listing_id=str(listing_id))
    return Done(status="restored")


# ---------- plans and settings ----------


class PlanIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    seats: int = Field(ge=1, le=1000)
    listing_limit: int | None = Field(ge=1, le=100000, description="null = unlimited")
    features: list[str] = Field(default_factory=list, max_length=30)
    price_month: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    price_year: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    provider_price_ids: dict[Literal["month", "year"], str] = Field(default_factory=dict)
    sales_led: bool = False
    is_public: bool = True
    sort_order: int = Field(default=0, ge=0, le=1000)


class PlanAdminOut(PlanIn):
    key: str
    workspaces: int = Field(description="Workspaces currently on this plan.")


def _plans(s: Session) -> list[PlanAdminOut]:
    rows = s.execute(text("""SELECT p.*, (SELECT count(*) FROM workspaces w WHERE w.plan_key = p.key
                                         AND w.deleted_at IS NULL) AS workspaces
                             FROM plans p ORDER BY p.sort_order, p.key""")).all()
    return [PlanAdminOut(key=r.key, name=r.name, seats=r.seats, listing_limit=r.listing_limit,
                         features=list(r.features), price_month=r.price_month, price_year=r.price_year,
                         currency=r.currency, provider_price_ids=dict(r.provider_price_ids or {}),
                         sales_led=r.sales_led, is_public=r.is_public, sort_order=r.sort_order,
                         workspaces=r.workspaces) for r in rows]


@router.get("/plans", response_model=list[PlanAdminOut])
def list_plans(staff: Staff = Depends(current_staff)) -> list[PlanAdminOut]:
    staff.require("pricing.edit")
    with hq_session() as s:
        return _plans(s)


_PLAN_PARAMS = """name = :name, seats = :seats, listing_limit = :listing_limit, features = CAST(:features AS jsonb),
                  price_month = :price_month, price_year = :price_year, currency = :currency,
                  provider_price_ids = CAST(:ids AS jsonb), sales_led = :sales_led, is_public = :is_public,
                  sort_order = :sort_order, updated_at = now()"""


def _plan_params(body: PlanIn) -> dict:
    import json

    data = body.model_dump()
    data["features"] = json.dumps(data["features"])
    data["ids"] = json.dumps(data.pop("provider_price_ids"))
    return data


@router.put("/plans/{key}", response_model=list[PlanAdminOut])
def update_plan(key: str, body: PlanIn, staff: Staff = Depends(current_staff)) -> list[PlanAdminOut]:
    """Takes effect immediately for everyone on the plan. To keep current customers on old terms, hide this
    plan (`is_public: false`) and create a new one."""
    staff.require("pricing.edit")
    with hq_session() as s:
        before = s.execute(text("SELECT * FROM plans WHERE key = :k FOR UPDATE"), {"k": key}).first()
        if before is None:
            raise ApiError(404, "not_found", "Plan not found.")
        s.execute(text(f"UPDATE plans SET {_PLAN_PARAMS} WHERE key = :key"), {**_plan_params(body), "key": key})
        audit(s, staff, "plan.updated", plan_key=key,
              before={k: before._mapping[k] for k in ("seats", "listing_limit", "price_month", "price_year", "is_public")},
              after=body.model_dump(include={"seats", "listing_limit", "price_month", "price_year", "is_public"}))
        return _plans(s)


class PlanCreateIn(PlanIn):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,29}$")


@router.post("/plans", status_code=201, response_model=list[PlanAdminOut])
def create_plan(body: PlanCreateIn, staff: Staff = Depends(current_staff)) -> list[PlanAdminOut]:
    staff.require("pricing.edit")
    try:
        with hq_session() as s:
            columns = "key, name, seats, listing_limit, features, price_month, price_year, currency, " \
                      "provider_price_ids, sales_led, is_public, sort_order"
            s.execute(text(f"""INSERT INTO plans ({columns}) VALUES (:key, :name, :seats, :listing_limit,
                               CAST(:features AS jsonb), :price_month, :price_year, :currency, CAST(:ids AS jsonb),
                               :sales_led, :is_public, :sort_order)"""), {**_plan_params(body), "key": body.key})
            audit(s, staff, "plan.created", plan_key=body.key)
            return _plans(s)
    except IntegrityError:
        raise ApiError(409, "plan_exists", "A plan with this key already exists.") from None


class SettingsIO(BaseModel):
    trial_video_max_mb: int = Field(ge=50, le=5000, description="Largest walkthrough video on a trial or free preview.")


@router.get("/settings", response_model=SettingsIO)
def get_platform_settings(staff: Staff = Depends(current_staff)) -> SettingsIO:
    staff.require("pricing.edit")
    with hq_session() as s:
        values = dict(s.execute(text("SELECT key, value FROM platform_settings")).all())
    return SettingsIO(trial_video_max_mb=int(values.get("trial_video_max_mb", 500)))


@router.put("/settings", response_model=SettingsIO)
def put_platform_settings(body: SettingsIO, staff: Staff = Depends(current_staff)) -> SettingsIO:
    staff.require("pricing.edit")
    with hq_session() as s:
        for key, value in body.model_dump().items():
            s.execute(text("""INSERT INTO platform_settings (key, value) VALUES (:k, to_jsonb(:v))
                              ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()"""),
                      {"k": key, "v": value})
        audit(s, staff, "settings.updated", **body.model_dump())
    return body


# ---------- announcements ----------


class AnnouncementIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=4000)
    channel: Literal["banner", "email", "both"]
    audience: Literal["all", "paying", "trialing"] = "all"
    starts_at: datetime | None = None
    ends_at: datetime | None = None


class AnnouncementOut(AnnouncementIn):
    id: UUID
    emails_sent: int
    created_by: str
    created_at: datetime


_ANNOUNCEMENTS = """SELECT a.*, st.email AS creator FROM announcements a JOIN staff st ON st.id = a.created_by"""


def _announcement_out(r) -> AnnouncementOut:
    return AnnouncementOut(id=r.id, title=r.title, body=r.body, channel=r.channel, audience=r.audience,
                           starts_at=r.starts_at, ends_at=r.ends_at, emails_sent=r.emails_sent, created_by=r.creator,
                           created_at=r.created_at)


@router.get("/announcements", response_model=list[AnnouncementOut])
def list_announcements(staff: Staff = Depends(current_staff)) -> list[AnnouncementOut]:
    staff.require("announcements.send")
    with hq_session() as s:
        return [_announcement_out(r) for r in s.execute(text(f"{_ANNOUNCEMENTS} ORDER BY a.created_at DESC LIMIT 100"))]


_AUDIENCE = {"all": ("trialing", "active", "grace", "none", "offline"), "paying": ("active", "grace"),
             "trialing": ("trialing",)}


@router.post("/announcements", status_code=201, response_model=AnnouncementOut)
def create_announcement(body: AnnouncementIn, staff: Staff = Depends(current_staff)) -> AnnouncementOut:
    """Banners show in the Studio between `starts_at` and `ends_at`. Emails go to every workspace Admin in
    the audience straight away (service announcements only, not marketing)."""
    staff.require("announcements.send")
    outgoing: list[mail.Email] = []
    with hq_session() as s:
        announcement_id = s.execute(
            text("""INSERT INTO announcements (title, body, channel, audience, starts_at, ends_at, created_by)
                    VALUES (:t, :b, :c, :a, coalesce(:s, now()), :e, :by) RETURNING id"""),
            {"t": body.title, "b": body.body, "c": body.channel, "a": body.audience, "s": body.starts_at,
             "e": body.ends_at, "by": staff.staff_id}).scalar_one()
        if body.channel in ("email", "both"):
            recipients = s.execute(text("""SELECT DISTINCT u.email FROM workspaces w
                JOIN memberships m ON m.workspace_id = w.id AND m.is_admin AND m.removed_at IS NULL
                JOIN users u ON u.id = m.user_id
                WHERE w.deleted_at IS NULL AND w.frozen_at IS NULL AND w.subscription_state = ANY(:states)
                  AND u.deleted_at IS NULL AND u.banned_at IS NULL AND u.email_verified_at IS NOT NULL"""),
                {"states": list(_AUDIENCE[body.audience])}).scalars().all()
            outgoing = [mail.Email(to=to, subject=body.title, text=body.body) for to in recipients]
            s.execute(text("UPDATE announcements SET emails_sent = :n WHERE id = :id"),
                      {"n": len(outgoing), "id": announcement_id})
        audit(s, staff, "announcement.created", announcement_id=str(announcement_id), channel=body.channel,
              audience=body.audience, emails=len(outgoing))
        out = _announcement_out(s.execute(text(f"{_ANNOUNCEMENTS} WHERE a.id = :id"), {"id": announcement_id}).one())
    mail.send(*outgoing)
    return out


@router.post("/announcements/{announcement_id}/end", response_model=AnnouncementOut)
def end_announcement(announcement_id: UUID, staff: Staff = Depends(current_staff)) -> AnnouncementOut:
    staff.require("announcements.send")
    with hq_session() as s:
        if not s.execute(text("UPDATE announcements SET ends_at = now() WHERE id = :id AND (ends_at IS NULL OR ends_at > now())"),
                         {"id": announcement_id}).rowcount:
            raise ApiError(404, "not_found", "No running announcement with that id.")
        audit(s, staff, "announcement.ended", announcement_id=str(announcement_id))
        return _announcement_out(s.execute(text(f"{_ANNOUNCEMENTS} WHERE a.id = :id"), {"id": announcement_id}).one())


# ---------- legal versions (Super-Admin only) ----------


class LegalVersionIn(BaseModel):
    document: Literal["terms", "privacy"]
    version: str = Field(pattern=r"^[A-Za-z0-9._-]{1,40}$")
    material: bool = Field(description="Material changes must be re-accepted by every user.")
    summary: str = Field(default="", max_length=2000, description="What changed, shown to users.")
    effective_in_days: int = Field(default=30, ge=0, le=90, description="Scope: 30 days' notice for material changes.")
    notify: bool = Field(default=True, description="Email every user about a material change now.")


class LegalVersionOut(BaseModel):
    document: str
    version: str
    material: bool
    summary: str
    published_at: datetime
    accepted_by: int


@router.get("/legal", response_model=list[LegalVersionOut])
def list_legal(staff: Staff = Depends(current_staff)) -> list[LegalVersionOut]:
    staff.require_super()
    with hq_session() as s:
        rows = s.execute(text("""SELECT v.*, (SELECT count(DISTINCT a.user_id) FROM legal_acceptances a
                                              WHERE a.document = v.document AND a.version = v.version) AS accepted_by
                                 FROM legal_versions v ORDER BY v.document, v.published_at DESC""")).all()
    return [LegalVersionOut(document=r.document, version=r.version, material=r.material, summary=r.summary,
                            published_at=r.published_at, accepted_by=r.accepted_by) for r in rows]


@router.post("/legal", status_code=201, response_model=list[LegalVersionOut])
def publish_legal(body: LegalVersionIn, staff: Staff = Depends(current_staff)) -> list[LegalVersionOut]:
    """Records a new Terms or Privacy Policy version, effective after `effective_in_days`. New sign-ups accept
    it from then on; with `material`, existing users are asked to accept it (`Me.legal_pending`)."""
    staff.require_super()
    outgoing: list[mail.Email] = []
    try:
        with hq_session() as s:
            effective = s.execute(text("""INSERT INTO legal_versions (document, version, material, summary, published_at, created_by)
                                          VALUES (:d, :v, :m, :s, now() + :days, :by) RETURNING published_at"""),
                                  {"d": body.document, "v": body.version, "m": body.material, "s": body.summary,
                                   "days": timedelta(days=body.effective_in_days), "by": staff.staff_id}).scalar_one()
            if body.material and body.notify:
                name = "Terms of Service" if body.document == "terms" else "Privacy Policy"
                recipients = s.execute(text("""SELECT email FROM users WHERE deleted_at IS NULL AND banned_at IS NULL
                                               AND email_verified_at IS NOT NULL""")).scalars().all()
                when = effective.strftime("%d %B %Y").lstrip("0")
                outgoing = [mail.Email(to=to, subject=f"We're updating our {name}",
                                       text=f"Our {name} changes on {when}.\n\n{body.summary}\n\n"
                                            f"Read it at {get_settings().site_url}/{body.document}. "
                                            "You'll be asked to accept it the next time you sign in after that date.")
                            for to in recipients]
            audit(s, staff, "legal.published", document=body.document, version=body.version, material=body.material,
                  emails=len(outgoing))
    except IntegrityError:
        raise ApiError(409, "version_exists", "That version already exists.") from None
    mail.send(*outgoing)
    return list_legal(staff)

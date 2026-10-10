"""Plans, checkout, subscriptions and the account lifecycle (docs/SCOPE.md 11).

The merchant of record is the source of truth: its signed webhooks move a workspace between
active and lapsed. Lapsed accounts get 30 days' grace (live, no new listings), then go offline
(503 pages, read-only Studio), and are permanently deleted 6 months after lapsing unless they
resubscribe, which restores everything at the same addresses.
"""

import json
import logging
from collections import Counter
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import Row, text
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app import email as mail
from app.billing_providers import BillingEvent, SubscriptionRef, WebhookError, get_provider
from app.config import get_settings
from app.db import public_session, tenant_session
from app.deps import Auth, in_workspace
from app.errors import ApiError, ErrorResponse
from app.permissions import load_access
from app.plans import DELETE_AFTER, GRACE, TEAM_PLANS
from app.storage import get_storage

log = logging.getLogger("scrollwalk.billing")

router = APIRouter(
    prefix="/api/v1/billing",
    tags=["billing"],
    responses={k: {"model": ErrorResponse} for k in (400, 401, 403, 404, 409, 422)},
)
public_router = APIRouter(prefix="/api/v1/public", tags=["public"])

TERMS = ("Renews automatically each {interval} until you cancel. Cancel anytime in the Studio and keep access until "
         "the end of the period you've paid for. No refunds, except where required by law. For business use only.")
LIVE_STATUSES = frozenset({"active", "past_due"})
Interval = Literal["month", "year"]


# ---------- schemas ----------


class PlanOut(BaseModel):
    key: str
    name: str
    seats: int
    listing_limit: int | None = Field(description="null = unlimited")
    features: list[str]
    price_month: float | None = Field(description="null until pricing is set")
    price_year: float | None
    currency: str
    sales_led: bool = Field(description="true = 'Talk to us' instead of checkout")


class SubscriptionOut(BaseModel):
    plan_key: str
    interval: Interval
    status: Literal["active", "past_due", "canceled", "expired"]
    current_period_end: datetime | None
    cancel_at_period_end: bool


class UsageOut(BaseModel):
    active_listings: int
    members: int


class BillingOut(BaseModel):
    provider: str
    state: Literal["none", "trialing", "active", "grace", "offline"]
    plan_key: str | None
    subscription: SubscriptionOut | None
    grace_ends_at: datetime | None
    offline_at: datetime | None
    delete_after: datetime | None
    usage: UsageOut
    plans: list[PlanOut]
    terms: dict[str, str] = Field(description="Checkout wording per interval (auto-renewal, cancellation, refunds).")


class CheckoutIn(BaseModel):
    plan_key: str = Field(max_length=30)
    interval: Interval = "month"


class UrlOut(BaseModel):
    url: str


class StubCheckoutIn(BaseModel):
    token: str = Field(max_length=500)


class SimulateIn(BaseModel):
    event: Literal["renew", "payment_failed", "end"]


# ---------- helpers ----------


def _plans(s: Session) -> list[PlanOut]:
    rows = s.execute(text("SELECT * FROM plans WHERE is_public ORDER BY sort_order, key")).all()
    return [PlanOut(key=r.key, name=r.name, seats=r.seats, listing_limit=r.listing_limit, features=list(r.features),
                    price_month=float(r.price_month) if r.price_month is not None else None,
                    price_year=float(r.price_year) if r.price_year is not None else None,
                    currency=r.currency, sales_led=r.sales_led) for r in rows]


def _subscription(s: Session) -> Row | None:
    return s.execute(text("SELECT * FROM subscriptions WHERE workspace_id = app_workspace_id()")).first()


def _ref(sub: Row) -> SubscriptionRef:
    return SubscriptionRef(workspace_id=sub.workspace_id, subscription_id=sub.provider_subscription_id,
                           customer_id=sub.provider_customer_id, plan_key=sub.plan_key, interval=sub.billing_interval,
                           status=sub.status, current_period_end=sub.current_period_end,
                           cancel_at_period_end=sub.cancel_at_period_end)


def _usage(s: Session) -> UsageOut:
    row = s.execute(text("""SELECT
        (SELECT count(*) FROM listings WHERE deleted_at IS NULL AND status <> 'sold') AS listings,
        (SELECT count(*) FROM memberships WHERE workspace_id = app_workspace_id() AND removed_at IS NULL) AS members""")).one()
    return UsageOut(active_listings=row.listings, members=row.members)


def _billing(s: Session, workspace_id: UUID) -> BillingOut:
    ws = s.execute(text("SELECT * FROM workspaces WHERE id = :w"), {"w": workspace_id}).one()
    sub = _subscription(s)
    return BillingOut(
        provider=get_provider().name, state=ws.subscription_state, plan_key=ws.plan_key,
        subscription=SubscriptionOut(plan_key=sub.plan_key, interval=sub.billing_interval, status=sub.status,
                                     current_period_end=sub.current_period_end,
                                     cancel_at_period_end=sub.cancel_at_period_end) if sub else None,
        grace_ends_at=ws.grace_ends_at, offline_at=ws.offline_at, delete_after=ws.delete_after,
        usage=_usage(s), plans=_plans(s),
        terms={i: TERMS.format(interval=i) for i in ("month", "year")},
    )


def _admin(s: Session, auth: Auth) -> None:
    load_access(s, auth.user_id, auth.workspace_id).require_admin()


def _target_plan(s: Session, plan_key: str, interval: str) -> tuple[Row, str | None]:
    plan = s.execute(text("SELECT * FROM plans WHERE key = :k AND is_public"), {"k": plan_key}).first()
    if plan is None:
        raise ApiError(422, "invalid_plan", "Choose one of the plans.")
    if plan.sales_led:
        raise ApiError(409, "contact_sales", "Talk to us about the Brokerage plan and we'll set it up for you.")
    usage = _usage(s)
    if plan.listing_limit is not None and usage.active_listings > plan.listing_limit:
        raise ApiError(409, "plan_too_small", f"{plan.name} allows {plan.listing_limit} active listings and you have "
                                              f"{usage.active_listings}. Mark some as sold or delete them first.")
    if usage.members > plan.seats:
        raise ApiError(409, "plan_too_small", f"{plan.name} has {plan.seats} seats and your team has {usage.members} "
                                              "people. Remove some members first.")
    price_id = (plan.provider_price_ids or {}).get(interval)
    if get_provider().name != "stub" and not price_id:
        raise ApiError(409, "plan_unavailable", "This plan isn't available to buy yet.")
    return plan, price_id


def _admin_emails(s: Session) -> list[str]:
    return list(s.execute(text("""SELECT u.email FROM memberships m JOIN users u ON u.id = m.user_id
                                  WHERE m.workspace_id = app_workspace_id() AND m.is_admin AND m.removed_at IS NULL
                                    AND u.deleted_at IS NULL""")).scalars())


def _notice(s: Session, workspace_id: UUID, key: str, kind: str, **ctx) -> list[mail.Email]:
    """Records a reminder and returns its emails, or nothing if it was already sent."""
    new = s.execute(text("""INSERT INTO lifecycle_notices (workspace_id, notice) VALUES (:w, :n)
                            ON CONFLICT DO NOTHING RETURNING notice"""), {"w": workspace_id, "n": key}).first()
    if new is None:
        return []
    app_url = get_settings().app_url
    return [mail.lifecycle_email(to, kind, app_url, **ctx) for to in _admin_emails(s)]


def _date(value: datetime) -> str:
    return value.strftime("%d %B %Y").lstrip("0")


# ---------- applying provider events ----------


def _activate(s: Session, workspace_id: UUID, plan_key: str) -> None:
    s.execute(
        text("""UPDATE workspaces SET subscription_state = 'active', plan_key = :p, lapsed_at = NULL,
                       grace_ends_at = NULL, offline_at = NULL, delete_after = NULL,
                       kind = CASE WHEN :p = ANY(:team) THEN 'team' ELSE kind END
                WHERE id = :w"""),
        {"p": plan_key, "team": list(TEAM_PLANS), "w": workspace_id},
    )
    s.execute(text("""DELETE FROM lifecycle_notices WHERE workspace_id = :w
                      AND (notice LIKE 'grace%' OR notice LIKE 'delete%' OR notice = 'offline')"""), {"w": workspace_id})
    s.execute(text("SELECT trial_converted()"))


def _lapse(s: Session, ws: Row) -> list[mail.Email]:
    if ws.subscription_state != "active":
        return []
    now = s.execute(text("SELECT now()")).scalar_one()
    s.execute(
        text("""UPDATE workspaces SET subscription_state = 'grace', lapsed_at = :now, grace_ends_at = :g,
                       delete_after = :d, offline_at = NULL WHERE id = :w"""),
        {"now": now, "g": now + GRACE, "d": now + DELETE_AFTER, "w": ws.id},
    )
    return _notice(s, ws.id, "grace_start", "grace_start", date=_date(now + GRACE))


def process_event(provider: str, event: BillingEvent) -> str:
    """Applies one provider event exactly once. Returns what happened, for logs and tests."""
    with tenant_session() as s:
        record_id = s.execute(
            text("SELECT billing_event_record(:p, :e, :t, :w, CAST(:payload AS jsonb))"),
            {"p": provider, "e": event.event_id, "t": event.type, "w": event.workspace_id,
             "payload": json.dumps(event.payload())},
        ).scalar()
    if record_id is None:
        return "duplicate"
    outgoing: list[mail.Email] = []
    result, error = "applied", ""
    try:
        with tenant_session(None, event.workspace_id) as s:
            ws = s.execute(text("SELECT * FROM workspaces WHERE id = :w FOR UPDATE"), {"w": event.workspace_id}).first()
            if ws is None or ws.deleted_at is not None:
                raise ValueError("unknown or deleted workspace")
            if s.execute(text("SELECT 1 FROM plans WHERE key = :k"), {"k": event.plan_key}).first() is None:
                raise ValueError(f"unknown plan {event.plan_key}")
            sub = _subscription(s)
            if sub and event.occurred_at < sub.last_event_at:
                result = "stale"
            else:
                s.execute(
                    text("""INSERT INTO subscriptions (workspace_id, provider, provider_customer_id, provider_subscription_id,
                                                       plan_key, billing_interval, status, current_period_end,
                                                       cancel_at_period_end, last_event_at)
                            VALUES (:w, :p, :c, :sid, :plan, :i, :st, :end, :cancel, :at)
                            ON CONFLICT (workspace_id) DO UPDATE SET provider = :p, provider_customer_id = :c,
                              provider_subscription_id = :sid, plan_key = :plan, billing_interval = :i, status = :st,
                              current_period_end = :end, cancel_at_period_end = :cancel, last_event_at = :at,
                              updated_at = now()"""),
                    {"w": event.workspace_id, "p": provider, "c": event.customer_id, "sid": event.subscription_id,
                     "plan": event.plan_key, "i": event.interval, "st": event.status, "end": event.current_period_end,
                     "cancel": event.cancel_at_period_end, "at": event.occurred_at},
                )
                if event.status in LIVE_STATUSES:
                    _activate(s, ws.id, event.plan_key)
                else:
                    outgoing = _lapse(s, ws)
    except ValueError as exc:
        result, error = "rejected", str(exc)
        log.warning("billing event %s rejected: %s", event.event_id, exc)
    with tenant_session() as s:
        s.execute(text("SELECT billing_event_done(:id, :e)"), {"id": record_id, "e": error})
    if outgoing:
        mail.send(*outgoing)
    return result


# ---------- lifecycle job ----------


def _days_left(until: datetime, now: datetime) -> int:
    return max(0, -(-int((until - now).total_seconds()) // 86400))


def run_lifecycle() -> dict:
    """Hourly: grace → offline → deletion, reminder emails, trial-listing and renewal reminders,
    expired downloads."""
    counts: Counter = Counter()
    with tenant_session() as s:
        workspace_ids = s.execute(text("SELECT * FROM lifecycle_workspaces()")).scalars().all()
        stale_exports = [k for k in s.execute(text("SELECT * FROM exports_expire()")).scalars() if k]
    storage = get_storage()
    if stale_exports:
        storage.delete(stale_exports)
        counts["exports_expired"] += len(stale_exports)
    for workspace_id in workspace_ids:
        outgoing: list[mail.Email] = []
        purge = False
        with tenant_session(None, workspace_id) as s:
            ws = s.execute(text("SELECT * FROM workspaces WHERE id = :w FOR UPDATE"), {"w": workspace_id}).one()
            now = s.execute(text("SELECT now()")).scalar_one()
            if ws.subscription_state == "grace":
                if ws.grace_ends_at <= now:
                    s.execute(text("UPDATE workspaces SET subscription_state = 'offline', offline_at = now() WHERE id = :w"),
                              {"w": workspace_id})
                    outgoing += _notice(s, workspace_id, "offline", "offline", date=_date(ws.delete_after))
                    counts["offline"] += 1
                else:
                    left = _days_left(ws.grace_ends_at, now)
                    if left <= 7:
                        kind = "grace_1" if left <= 1 else "grace_7"
                        outgoing += _notice(s, workspace_id, kind, kind, date=_date(ws.grace_ends_at))
            elif ws.subscription_state == "offline":
                if ws.delete_after <= now:
                    purge = True
                else:
                    left = _days_left(ws.delete_after, now)
                    if left <= 30:
                        kind = "delete_7" if left <= 7 else "delete_30"
                        outgoing += _notice(s, workspace_id, kind, kind, date=_date(ws.delete_after))
            if not purge:
                if ws.subscription_state != "active":
                    trials = s.execute(text("""SELECT id, title, trial_expires_at FROM listings
                                               WHERE is_trial AND deleted_at IS NULL AND status = 'published'
                                                 AND trial_expires_at BETWEEN now() AND now() + interval '8 days'""")).all()
                    for listing in trials:
                        left = _days_left(listing.trial_expires_at, now)
                        if left <= 7:
                            kind = "trial_1" if left <= 1 else "trial_7"
                            outgoing += _notice(s, workspace_id, f"{kind}:{listing.id}", kind,
                                                title=listing.title or "Your listing",
                                                date=_date(listing.trial_expires_at))
                sub = _subscription(s)
                if (sub and sub.billing_interval == "year" and sub.status == "active" and not sub.cancel_at_period_end
                        and sub.current_period_end and _days_left(sub.current_period_end, now) <= 7):
                    outgoing += _notice(s, workspace_id, f"renewal:{sub.current_period_end.date()}", "renewal",
                                        date=_date(sub.current_period_end))
        if purge:
            with tenant_session(None, workspace_id) as s:
                purged = s.execute(text("SELECT workspace_purge(:w)"), {"w": workspace_id}).scalar_one()
            if purged:
                storage.delete_prefix(f"private/ws/{workspace_id}/")
                storage.delete_prefix(f"public/ws/{workspace_id}/")
                counts["deleted"] += 1
        if outgoing:
            mail.send(*outgoing)
            counts["emails"] += len(outgoing)
    return dict(counts)


# ---------- endpoints ----------


@public_router.get("/plans", response_model=list[PlanOut])
def public_plans() -> list[PlanOut]:
    with public_session() as s:
        return _plans(s)


@router.get("", response_model=BillingOut)
def billing_overview(auth: Auth = Depends(in_workspace)) -> BillingOut:
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        _admin(s, auth)
        return _billing(s, auth.workspace_id)


@router.post("/checkout", response_model=UrlOut)
def checkout(body: CheckoutIn, auth: Auth = Depends(in_workspace)) -> UrlOut:
    """Starts checkout on the merchant of record's page (any state, including grace and offline)."""
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        _admin(s, auth)
        sub = _subscription(s)
        if sub and sub.status in LIVE_STATUSES:
            raise ApiError(409, "already_subscribed", "You already have a plan. Change it instead.")
        plan, price_id = _target_plan(s, body.plan_key, body.interval)
        email = s.execute(text("SELECT email FROM users WHERE id = :u"), {"u": auth.user_id}).scalar_one()
    return UrlOut(url=get_provider().checkout_url(auth.workspace_id, plan.key, body.interval, email, price_id))


def _live_subscription(s: Session) -> Row:
    sub = _subscription(s)
    if sub is None or sub.status not in LIVE_STATUSES:
        raise ApiError(409, "no_subscription", "You don't have an active plan.")
    return sub


def _apply_now(event: BillingEvent | None, auth: Auth) -> BillingOut:
    if event is not None:
        process_event(get_provider().name, event)
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        return _billing(s, auth.workspace_id)


@router.post("/change", response_model=BillingOut)
def change_plan(body: CheckoutIn, auth: Auth = Depends(in_workspace)) -> BillingOut:
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        _admin(s, auth)
        sub = _live_subscription(s)
        if sub.plan_key == body.plan_key and sub.billing_interval == body.interval:
            raise ApiError(409, "same_plan", "You're already on this plan.")
        plan, price_id = _target_plan(s, body.plan_key, body.interval)
        ref = _ref(sub)
    return _apply_now(get_provider().change_plan(ref, plan.key, body.interval, price_id), auth)


@router.post("/cancel", response_model=BillingOut)
def cancel(auth: Auth = Depends(in_workspace)) -> BillingOut:
    """Cancels at the end of the paid period; everything stays as it is until then."""
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        _admin(s, auth)
        sub = _live_subscription(s)
        if sub.cancel_at_period_end:
            raise ApiError(409, "already_cancelled", "Your plan is already set to end.")
        ref = _ref(sub)
    return _apply_now(get_provider().cancel(ref), auth)


@router.post("/resume", response_model=BillingOut)
def resume(auth: Auth = Depends(in_workspace)) -> BillingOut:
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        _admin(s, auth)
        sub = _live_subscription(s)
        if not sub.cancel_at_period_end:
            raise ApiError(409, "not_cancelled", "Your plan isn't set to end.")
        ref = _ref(sub)
    return _apply_now(get_provider().resume(ref), auth)


@router.post("/portal", response_model=UrlOut)
def portal(auth: Auth = Depends(in_workspace)) -> UrlOut:
    """Payment method, invoices and receipts on the merchant of record's own page."""
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        _admin(s, auth)
        sub = _subscription(s)
        if sub is None:
            raise ApiError(409, "no_subscription", "You don't have a plan yet.")
    return UrlOut(url=get_provider().portal_url(sub.provider_customer_id))


@router.post("/webhooks/{provider}", include_in_schema=False)
async def webhook(provider: str, request: Request) -> dict:
    """Signed provider events. Answers 200 for anything verified (even if rejected) so the provider
    doesn't retry forever; 400 only for bad signatures."""
    active = get_provider()
    if provider != active.name:
        raise ApiError(404, "not_found", "Unknown provider.")
    body = await request.body()
    try:
        event = active.parse_webhook(body, request.headers)
    except WebhookError:
        raise ApiError(400, "invalid_signature", "Signature check failed.") from None
    return {"status": await run_in_threadpool(process_event, active.name, event)}


# ----- development stand-in (refused in production and with a real provider) -----


def _stub():
    provider = get_provider()
    if provider.name != "stub":
        raise ApiError(404, "not_found", "Not available.")
    return provider


@router.post("/stub/checkout-complete", response_model=BillingOut)
def stub_checkout_complete(body: StubCheckoutIn, auth: Auth = Depends(in_workspace)) -> BillingOut:
    """The simulated checkout page's Pay button (`/studio/billing/checkout#<token>`)."""
    provider = _stub()
    event = provider.checkout_completed(body.token)
    if event is None or event.workspace_id != auth.workspace_id:
        raise ApiError(400, "invalid_checkout", "This checkout has expired. Start again.")
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        _admin(s, auth)
    return _apply_now(event, auth)


@router.post("/stub/simulate", response_model=BillingOut)
def stub_simulate(body: SimulateIn, auth: Auth = Depends(in_workspace)) -> BillingOut:
    """Pretends the provider renewed, failed a payment, or ended the subscription."""
    provider = _stub()
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        _admin(s, auth)
        sub = _subscription(s)
        if sub is None:
            raise ApiError(409, "no_subscription", "You don't have a plan yet.")
        ref = _ref(sub)
    return _apply_now(provider.simulate(ref, body.event), auth)

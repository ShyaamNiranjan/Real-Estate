"""Super-Admin dashboard (docs/SCOPE.md 12): growth, revenue, profit, usage, health, and the
monthly cost entries behind the profit numbers. One display currency (USD)."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import hq_session
from app.errors import ApiError, ErrorResponse
from app.staff import Staff, audit, current_staff

router = APIRouter(
    prefix="/api/v1/hq",
    tags=["hq"],
    responses={k: {"model": ErrorResponse} for k in (401, 403, 404, 422)},
)

CURRENCY = "USD"
COST_CATEGORIES = ("hosting", "database", "storage", "ai", "email", "worker", "domain", "other")
SOURCES = ("link", "google", "referral", "invite")
ZERO = Decimal(0)


def _money(value) -> Decimal:
    return Decimal(value or 0).quantize(Decimal("0.01"))


def _month_starts(s: Session, months: int) -> list[date]:
    return list(s.execute(text("""SELECT generate_series(date_trunc('month', now()) - make_interval(months => :n - 1),
                                                         date_trunc('month', now()), interval '1 month')::date"""),
                          {"n": months}).scalars())


def _next_month(d: date) -> date:
    return date(d.year + d.month // 12, d.month % 12 + 1, 1)


# ---------- growth ----------


class SignupDay(BaseModel):
    day: date
    total: int
    by_source: dict[str, int]


class Funnel(BaseModel):
    signed_up: int
    finished_setup: int
    first_listing_published: int
    paid: int


class TrialStats(BaseModel):
    started: int
    converted: int
    conversion_rate: float | None
    median_days_to_convert: float | None


class GrowthOut(BaseModel):
    days: int
    customers: int
    by_state: dict[str, int]
    by_plan: dict[str, int]
    most_popular_plan: str | None
    signups: list[SignupDay]
    signups_by_source: dict[str, int]
    top_referrals: list[dict]
    funnel: Funnel = Field(description="People who signed up in the period and how far they got.")
    trials: TrialStats
    waitlist: int


@router.get("/dashboard/growth", response_model=GrowthOut)
def growth(days: int = Query(30, ge=7, le=365), staff: Staff = Depends(current_staff)) -> GrowthOut:
    staff.require("customers.view")
    since = timedelta(days=days)
    with hq_session() as s:
        states = dict(s.execute(text("""SELECT subscription_state, count(*) FROM workspaces
                                        WHERE deleted_at IS NULL GROUP BY 1""")).all())
        plans = dict(s.execute(text("""SELECT plan_key, count(*) FROM workspaces WHERE deleted_at IS NULL
                                       AND plan_key IS NOT NULL AND subscription_state IN ('active', 'grace')
                                       GROUP BY 1""")).all())
        rows = s.execute(text("""
            SELECT d::date AS day, u.signup_source AS source, count(u.id) AS n
            FROM generate_series(date_trunc('day', now() - :since), date_trunc('day', now()), interval '1 day') d
            LEFT JOIN users u ON date_trunc('day', u.created_at) = d AND u.email_verified_at IS NOT NULL
                             AND u.deleted_at IS NULL
            GROUP BY 1, 2 ORDER BY 1"""), {"since": since}).all()
        series: dict[date, SignupDay] = {}
        for r in rows:
            day = series.setdefault(r.day, SignupDay(day=r.day, total=0, by_source=dict.fromkeys(SOURCES, 0)))
            if r.source:
                day.by_source[r.source] += r.n
                day.total += r.n
        referrals = [{"code": r.code, "signups": r.n} for r in s.execute(text("""
            SELECT signup_referral AS code, count(*) AS n FROM users
            WHERE signup_referral <> '' AND created_at > now() - :since AND email_verified_at IS NOT NULL
            GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 10"""), {"since": since})]
        funnel = s.execute(text("""
            WITH cohort AS (
              SELECT u.id, m.workspace_id FROM users u
              JOIN memberships m ON m.user_id = u.id AND m.is_admin AND m.removed_at IS NULL
              WHERE u.created_at > now() - :since AND u.email_verified_at IS NOT NULL AND u.deleted_at IS NULL)
            SELECT count(*) AS signed_up,
                   count(*) FILTER (WHERE p.setup ?& array['about_you', 'contact', 'style']) AS finished_setup,
                   count(*) FILTER (WHERE EXISTS (SELECT 1 FROM listings l WHERE l.workspace_id = c.workspace_id
                                                    AND l.published_at IS NOT NULL)) AS published,
                   count(*) FILTER (WHERE EXISTS (SELECT 1 FROM payments pay WHERE pay.workspace_id = c.workspace_id
                                                    AND pay.kind = 'charge')
                                       OR EXISTS (SELECT 1 FROM subscriptions sub
                                                  WHERE sub.workspace_id = c.workspace_id)) AS paid
            FROM cohort c LEFT JOIN workspace_profiles p ON p.workspace_id = c.workspace_id"""),
            {"since": since}).one()
        trials = s.execute(text("""
            SELECT count(*) AS started, count(converted_at) AS converted,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM converted_at - redeemed_at) / 86400)
                     FILTER (WHERE converted_at IS NOT NULL) AS median_days
            FROM trial_redemptions WHERE redeemed_at > now() - :since"""), {"since": since}).one()
        waitlist = s.execute(text("SELECT count(*) FROM waitlist")).scalar_one()
    by_source = {k: sum(d.by_source[k] for d in series.values()) for k in SOURCES}
    return GrowthOut(
        days=days, customers=sum(states.values()), by_state=states, by_plan=plans,
        most_popular_plan=max(plans, key=plans.get) if plans else None, signups=list(series.values()),
        signups_by_source=by_source, top_referrals=referrals,
        funnel=Funnel(signed_up=funnel.signed_up, finished_setup=funnel.finished_setup,
                      first_listing_published=funnel.published, paid=funnel.paid),
        trials=TrialStats(started=trials.started, converted=trials.converted,
                          conversion_rate=round(trials.converted / trials.started, 3) if trials.started else None,
                          median_days_to_convert=round(trials.median_days, 1) if trials.median_days is not None else None),
        waitlist=waitlist,
    )


# ---------- revenue ----------


class RevenueMonth(BaseModel):
    month: date
    gross: Decimal
    refunds: Decimal
    fees: Decimal
    tax: Decimal
    net: Decimal
    failed_payments: int
    mrr_new: Decimal
    mrr_expansion: Decimal
    mrr_contraction: Decimal
    mrr_churned: Decimal
    mrr_reactivation: Decimal
    mrr_end: Decimal
    customers_churned: int


class Renewal(BaseModel):
    workspace_id: UUID
    username: str | None
    plan_key: str
    interval: str
    renews_at: datetime
    amount: Decimal


class RevenueOut(BaseModel):
    currency: str = CURRENCY
    mrr: Decimal
    arr: Decimal
    paying_customers: int
    arpu: Decimal | None = Field(description="MRR per paying customer.")
    ltv: Decimal | None = Field(description="ARPU / monthly customer churn; null until there's churn to measure.")
    customer_churn_30d: float | None
    revenue_churn_30d: float | None
    total: dict[str, Decimal] = Field(description="All time: gross, refunds, fees, tax, net.")
    failed_payments_30d: dict[str, Decimal | int]
    refunds_30d: dict[str, Decimal | int]
    upcoming_renewals_30d: list[Renewal]
    months: list[RevenueMonth]


_MOVEMENTS = """
    SELECT c.workspace_id, c.mrr_before AS b, c.mrr_after AS a,
           EXISTS (SELECT 1 FROM mrr_changes e WHERE e.workspace_id = c.workspace_id AND e.mrr_after > 0
                     AND (e.occurred_at, e.id) < (c.occurred_at, c.id)) AS was_paying
    FROM mrr_changes c WHERE c.occurred_at >= :start AND c.occurred_at < :end"""

_MRR_AT = """
    SELECT coalesce(sum(a), 0) AS mrr, count(*) FILTER (WHERE a > 0) AS paying FROM (
      SELECT DISTINCT ON (workspace_id) mrr_after AS a FROM mrr_changes WHERE occurred_at < :at
      ORDER BY workspace_id, occurred_at DESC, id DESC) last"""


def _movements(s: Session, start, end) -> dict:
    out = dict.fromkeys(("new", "expansion", "contraction", "churned", "reactivation"), ZERO)
    churned = 0
    for r in s.execute(text(_MOVEMENTS), {"start": start, "end": end}):
        if r.b == 0 and r.a > 0:
            out["reactivation" if r.was_paying else "new"] += r.a
        elif r.b > 0 and r.a == 0:
            out["churned"] += r.b
            churned += 1
        elif r.a > r.b:
            out["expansion"] += r.a - r.b
        else:
            out["contraction"] += r.b - r.a
    return {**out, "customers_churned": churned}


def _payments(s: Session, start, end) -> dict:
    r = s.execute(text("""
        SELECT coalesce(sum(amount) FILTER (WHERE kind = 'charge'), 0) AS gross,
               coalesce(sum(amount) FILTER (WHERE kind = 'refund'), 0) AS refunds,
               coalesce(sum(fee) FILTER (WHERE kind = 'charge'), 0) AS fees,
               coalesce(sum(tax) FILTER (WHERE kind = 'charge'), 0) - coalesce(sum(tax) FILTER (WHERE kind = 'refund'), 0) AS tax,
               count(*) FILTER (WHERE kind = 'failed') AS failed,
               coalesce(sum(amount) FILTER (WHERE kind = 'failed'), 0) AS failed_amount,
               count(*) FILTER (WHERE kind = 'refund') AS refund_count
        FROM payments WHERE occurred_at >= :start AND occurred_at < :end"""), {"start": start, "end": end}).one()
    return {"gross": _money(r.gross), "refunds": _money(r.refunds), "fees": _money(r.fees), "tax": _money(r.tax),
            "net": _money(r.gross - r.refunds - r.fees - r.tax), "failed": r.failed,
            "failed_amount": _money(r.failed_amount), "refund_count": r.refund_count}


@router.get("/dashboard/revenue", response_model=RevenueOut)
def revenue(months: int = Query(12, ge=1, le=36), staff: Staff = Depends(current_staff)) -> RevenueOut:
    staff.require("revenue.view")
    with hq_session() as s:
        now = s.execute(text("SELECT now()")).scalar_one()
        current = s.execute(text("""SELECT coalesce(sum(mrr), 0) AS mrr, count(*) FILTER (WHERE mrr > 0) AS paying
                                    FROM subscriptions WHERE status IN ('active', 'past_due')""")).one()
        month_rows = []
        for start in _month_starts(s, months):
            end = _next_month(start)
            pay, mov = _payments(s, start, end), _movements(s, start, end)
            mrr_end = s.execute(text(_MRR_AT), {"at": min(end, now.date() + timedelta(days=1))}).one().mrr
            month_rows.append(RevenueMonth(
                month=start, gross=pay["gross"], refunds=pay["refunds"], fees=pay["fees"], tax=pay["tax"],
                net=pay["net"], failed_payments=pay["failed"], mrr_new=_money(mov["new"]),
                mrr_expansion=_money(mov["expansion"]), mrr_contraction=_money(mov["contraction"]),
                mrr_churned=_money(mov["churned"]), mrr_reactivation=_money(mov["reactivation"]),
                mrr_end=_money(mrr_end), customers_churned=mov["customers_churned"]))

        start_30 = now - timedelta(days=30)
        at_start = s.execute(text(_MRR_AT), {"at": start_30}).one()
        last_30 = _movements(s, start_30, now + timedelta(seconds=1))
        pay_30 = _payments(s, start_30, now + timedelta(seconds=1))
        total = _payments(s, datetime(2000, 1, 1), now + timedelta(seconds=1))
        renewals = s.execute(text("""
            SELECT sub.workspace_id, w.username, sub.plan_key, sub.billing_interval, sub.current_period_end, sub.mrr
            FROM subscriptions sub JOIN workspaces w ON w.id = sub.workspace_id
            WHERE sub.status IN ('active', 'past_due') AND NOT sub.cancel_at_period_end
              AND sub.current_period_end BETWEEN now() AND now() + interval '30 days'
            ORDER BY sub.current_period_end LIMIT 100""")).all()

    mrr = _money(current.mrr)
    arpu = _money(mrr / current.paying) if current.paying else None
    customer_churn = round(last_30["customers_churned"] / at_start.paying, 3) if at_start.paying else None
    revenue_churn = (round(float((last_30["churned"] + last_30["contraction"]) / at_start.mrr), 3)
                     if at_start.mrr else None)
    return RevenueOut(
        mrr=mrr, arr=mrr * 12, paying_customers=current.paying, arpu=arpu,
        ltv=_money(arpu / Decimal(str(customer_churn))) if arpu is not None and customer_churn else None,
        customer_churn_30d=customer_churn, revenue_churn_30d=revenue_churn,
        total={k: total[k] for k in ("gross", "refunds", "fees", "tax", "net")},
        failed_payments_30d={"count": pay_30["failed"], "amount": pay_30["failed_amount"]},
        refunds_30d={"count": pay_30["refund_count"], "amount": pay_30["refunds"]},
        upcoming_renewals_30d=[Renewal(workspace_id=r.workspace_id, username=r.username, plan_key=r.plan_key,
                                       interval=r.billing_interval, renews_at=r.current_period_end,
                                       amount=_money(r.mrr * 12 if r.billing_interval == "year" else r.mrr))
                               for r in renewals],
        months=month_rows,
    )


# ---------- costs and profit ----------


class CostIn(BaseModel):
    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="YYYY-MM")
    category: Literal["hosting", "database", "storage", "ai", "email", "worker", "domain", "other"]
    amount: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    note: str = Field(default="", max_length=200)


class CostOut(BaseModel):
    id: UUID
    month: date
    category: str
    amount: Decimal
    note: str
    created_at: datetime


def _cost_out(r) -> CostOut:
    return CostOut(id=r.id, month=r.month, category=r.category, amount=r.amount, note=r.note, created_at=r.created_at)


@router.get("/costs", response_model=list[CostOut])
def list_costs(months: int = Query(12, ge=1, le=36), staff: Staff = Depends(current_staff)) -> list[CostOut]:
    staff.require("revenue.view")
    with hq_session() as s:
        rows = s.execute(text("""SELECT * FROM cost_entries
                                 WHERE month >= date_trunc('month', now()) - make_interval(months => :n - 1)
                                 ORDER BY month DESC, category, created_at"""), {"n": months}).all()
    return [_cost_out(r) for r in rows]


@router.post("/costs", status_code=201, response_model=CostOut)
def add_cost(body: CostIn, staff: Staff = Depends(current_staff)) -> CostOut:
    """A bill for one month (hosting, database, ...). An `ai` entry for a month replaces the metered AI
    estimate for that month (reconciled against the invoice)."""
    staff.require("revenue.view")
    with hq_session() as s:
        row = s.execute(text("""INSERT INTO cost_entries (month, category, amount, note, created_by)
                                VALUES (CAST(:m AS date), :c, :a, :n, :by) RETURNING *"""),
                        {"m": f"{body.month}-01", "c": body.category, "a": body.amount, "n": body.note.strip(),
                         "by": staff.staff_id}).one()
        audit(s, staff, "cost.added", month=body.month, category=body.category, amount=str(body.amount))
    return _cost_out(row)


@router.delete("/costs/{cost_id}", status_code=204)
def delete_cost(cost_id: UUID, staff: Staff = Depends(current_staff)) -> None:
    staff.require("revenue.view")
    with hq_session() as s:
        row = s.execute(text("DELETE FROM cost_entries WHERE id = :id RETURNING month, category, amount"),
                        {"id": cost_id}).first()
        if row is None:
            raise ApiError(404, "not_found", "Cost entry not found.")
        audit(s, staff, "cost.deleted", month=str(row.month), category=row.category, amount=str(row.amount))


class ProfitMonth(BaseModel):
    month: date
    net_revenue: Decimal
    costs: dict[str, Decimal]
    ai_metered: Decimal = Field(description="AI cost from token counts; used unless an `ai` bill was entered.")
    costs_total: Decimal
    profit: Decimal


class CustomerProfit(BaseModel):
    workspace_id: UUID
    username: str | None
    display_name: str
    net_revenue: Decimal
    ai_cost: Decimal
    shared_costs: Decimal
    profit: Decimal


class ProfitOut(BaseModel):
    currency: str = CURRENCY
    months: list[ProfitMonth]
    net_revenue: Decimal
    costs_total: Decimal
    profit: Decimal
    per_customer: list[CustomerProfit] = Field(
        description="Paying customers over the whole period: their net revenue minus their own AI cost and an "
                    "equal share of every other cost.")


@router.get("/dashboard/profit", response_model=ProfitOut)
def profit(months: int = Query(6, ge=1, le=36), staff: Staff = Depends(current_staff)) -> ProfitOut:
    staff.require("revenue.view")
    with hq_session() as s:
        starts = _month_starts(s, months)
        out = []
        for start in starts:
            end = _next_month(start)
            net = _payments(s, start, end)["net"]
            costs = dict.fromkeys(COST_CATEGORIES, ZERO)
            billed_ai = False
            for r in s.execute(text("SELECT category, sum(amount) AS a FROM cost_entries WHERE month = :m GROUP BY 1"),
                               {"m": start}):
                costs[r.category] = _money(r.a)
                billed_ai = billed_ai or r.category == "ai"
            metered = _money(s.execute(text("""SELECT sum(cost_usd) FROM ai_generations
                                               WHERE created_at >= :s AND created_at < :e"""),
                                       {"s": start, "e": end}).scalar())
            if not billed_ai:
                costs["ai"] = metered
            total = sum(costs.values(), ZERO)
            out.append(ProfitMonth(month=start, net_revenue=net, costs=costs, ai_metered=metered, costs_total=total,
                                   profit=net - total))

        start, end = starts[0], _next_month(starts[-1])
        customers = s.execute(text("""
            SELECT w.id, w.username, w.display_name,
                   coalesce(sum(CASE p.kind WHEN 'charge' THEN p.amount - p.fee - p.tax
                                            WHEN 'refund' THEN -(p.amount - p.tax) ELSE 0 END), 0) AS net,
                   coalesce((SELECT sum(g.cost_usd) FROM ai_generations g WHERE g.workspace_id = w.id
                               AND g.created_at >= :s AND g.created_at < :e), 0) AS ai
            FROM payments p JOIN workspaces w ON w.id = p.workspace_id
            WHERE p.occurred_at >= :s AND p.occurred_at < :e
            GROUP BY w.id HAVING sum(CASE WHEN p.kind = 'charge' THEN 1 ELSE 0 END) > 0"""),
            {"s": start, "e": end}).all()

    net_total = sum((m.net_revenue for m in out), ZERO)
    costs_total = sum((m.costs_total for m in out), ZERO)
    ai_total = sum((m.costs["ai"] for m in out), ZERO)
    attributed_ai = sum((_money(c.ai) for c in customers), ZERO)
    shared = _money((costs_total - min(attributed_ai, ai_total)) / len(customers)) if customers else ZERO
    per_customer = sorted(
        (CustomerProfit(workspace_id=c.id, username=c.username, display_name=c.display_name,
                        net_revenue=_money(c.net), ai_cost=_money(c.ai), shared_costs=shared,
                        profit=_money(c.net) - _money(c.ai) - shared) for c in customers),
        key=lambda c: c.profit)
    return ProfitOut(months=out, net_revenue=net_total, costs_total=costs_total, profit=net_total - costs_total,
                     per_customer=per_customer[:500])


# ---------- usage ----------


class NearLimit(BaseModel):
    workspace_id: UUID
    username: str | None
    plan_key: str
    active_listings: int
    listing_limit: int | None
    members: int
    seats: int


class UsageOut(BaseModel):
    listings_live: int
    listings_total: int
    trial_listings_live: int
    views_30d: int
    visitors_30d: int
    enquiries_30d: int
    ai_requests_30d: int
    ai_failed_30d: int
    ai_cost_30d: Decimal
    storage_bytes: int
    database_bytes: int
    video_minutes_30d: float
    emails_sent_30d: int | None = Field(description="null until Resend is connected.")
    near_limits: list[NearLimit] = Field(description="80%+ of the listing limit, or every seat taken.")


@router.get("/dashboard/usage", response_model=UsageOut)
def usage(staff: Staff = Depends(current_staff)) -> UsageOut:
    staff.require("customers.view")
    with hq_session() as s:
        r = s.execute(text("""SELECT
            (SELECT count(*) FROM listings WHERE status IN ('published', 'sold') AND deleted_at IS NULL
               AND taken_down_at IS NULL) AS live,
            (SELECT count(*) FROM listings WHERE deleted_at IS NULL) AS total,
            (SELECT count(*) FROM listings WHERE status = 'published' AND deleted_at IS NULL AND is_trial
               AND trial_expires_at > now()) AS trial_live,
            (SELECT count(*) FROM analytics_events WHERE event = 'pageview' AND day > current_date - 30) AS views,
            (SELECT count(DISTINCT visitor_hash) FROM analytics_events WHERE day > current_date - 30) AS visitors,
            (SELECT count(*) FROM enquiries WHERE created_at > now() - interval '30 days') AS enquiries,
            (SELECT count(*) FROM ai_generations WHERE created_at > now() - interval '30 days') AS ai,
            (SELECT count(*) FROM ai_generations WHERE created_at > now() - interval '30 days'
               AND status = 'failed') AS ai_failed,
            (SELECT coalesce(sum(cost_usd), 0) FROM ai_generations
               WHERE created_at > now() - interval '30 days') AS ai_cost,
            (SELECT coalesce(sum(bytes), 0) FROM media) AS storage,
            pg_database_size(current_database()) AS db,
            (SELECT coalesce(sum(worker_seconds), 0) / 60 FROM processing_jobs
               WHERE finished_at > now() - interval '30 days') AS video_minutes""")).one()
        near = s.execute(text("""
            SELECT * FROM (
              SELECT w.id, w.username, w.plan_key, p.listing_limit, p.seats,
                     (SELECT count(*) FROM listings l WHERE l.workspace_id = w.id AND l.deleted_at IS NULL
                        AND l.status <> 'sold') AS listings,
                     (SELECT count(*) FROM memberships m WHERE m.workspace_id = w.id AND m.removed_at IS NULL) AS members
              FROM workspaces w JOIN plans p ON p.key = w.plan_key
              WHERE w.deleted_at IS NULL AND w.subscription_state = 'active') x
            WHERE (listing_limit IS NOT NULL AND listings >= listing_limit * 0.8) OR (seats > 1 AND members >= seats)
            ORDER BY listings DESC LIMIT 200""")).all()
    return UsageOut(
        listings_live=r.live, listings_total=r.total, trial_listings_live=r.trial_live, views_30d=r.views,
        visitors_30d=r.visitors, enquiries_30d=r.enquiries, ai_requests_30d=r.ai, ai_failed_30d=r.ai_failed,
        ai_cost_30d=_money(r.ai_cost), storage_bytes=r.storage, database_bytes=r.db,
        video_minutes_30d=round(float(r.video_minutes), 1), emails_sent_30d=None,
        near_limits=[NearLimit(workspace_id=n.id, username=n.username, plan_key=n.plan_key, active_listings=n.listings,
                               listing_limit=n.listing_limit, members=n.members, seats=n.seats) for n in near],
    )


# ---------- health ----------


class HealthOut(BaseModel):
    failed_jobs_24h: int
    stuck_jobs: int = Field(description="Running for over 30 minutes, or queued for over 15.")
    billing_errors_7d: int
    ai_failures_24h: int
    staff_failed_logins_24h: int
    sign_in_lockouts_24h: int = Field(description="Customer sign-in or code checks that hit the rate limit.")
    open_reports: int
    external: str


@router.get("/dashboard/health", response_model=HealthOut)
def health(staff: Staff = Depends(current_staff)) -> HealthOut:
    staff.require("customers.view")
    with hq_session() as s:
        r = s.execute(text("""SELECT
            (SELECT count(*) FROM processing_jobs WHERE status = 'failed'
               AND finished_at > now() - interval '24 hours') AS failed_jobs,
            (SELECT count(*) FROM processing_jobs WHERE (status = 'running' AND locked_at < now() - interval '30 minutes')
               OR (status = 'queued' AND run_after < now() - interval '15 minutes')) AS stuck,
            (SELECT count(*) FROM billing_events WHERE error <> '' AND received_at > now() - interval '7 days') AS billing,
            (SELECT count(*) FROM ai_generations WHERE status = 'failed'
               AND created_at > now() - interval '24 hours') AS ai,
            (SELECT count(*) FROM audit_log WHERE action = 'staff.login_failed'
               AND at > now() - interval '24 hours') AS staff_failed,
            (SELECT count(*) FROM rate_limits WHERE window_start > now() - interval '24 hours' AND (
               (key LIKE 'login-email:%' AND hits > 10) OR (key LIKE 'login-ip:%' AND hits > 30)
               OR (key LIKE 'code-check-email:%' AND hits > 10) OR (key LIKE 'code-check-ip:%' AND hits > 30))) AS lockouts,
            (SELECT count(*) FROM listing_reports WHERE status = 'open') AS reports""")).one()
    return HealthOut(
        failed_jobs_24h=r.failed_jobs, stuck_jobs=r.stuck, billing_errors_7d=r.billing, ai_failures_24h=r.ai,
        staff_failed_logins_24h=r.staff_failed, sign_in_lockouts_24h=r.lockouts, open_reports=r.reports,
        external="Uptime, server errors and slow pages come from the hosting monitor; bounced emails from Resend.",
    )

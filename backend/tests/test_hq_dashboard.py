from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db import tenant_session
from tests.auth_helpers import last_code
from tests.test_billing import simulate, subscribe
from tests.test_hq import H, add_staff, boss, hq_csrf, staff_login  # noqa: F401
from tests.test_listings import admin, new_listing, publish  # noqa: F401

REASON = "Support ticket 1234"


@pytest.fixture
def priced(owner_engine):
    with owner_engine.begin() as conn:
        conn.execute(text("""UPDATE plans SET price_month = d.m, price_year = d.y
                             FROM (VALUES ('agent', 29, 290), ('team', 79, 790)) AS d(key, m, y)
                             WHERE plans.key = d.key"""))


def D(value) -> Decimal:
    return Decimal(str(value))


def revenue(b):
    r = b.get(f"{H}/dashboard/revenue?months=3")
    assert r.status_code == 200, r.text
    return r.json()


def test_mrr_movements_payments_and_refunds(boss, admin, priced):
    b, c, ws = boss["client"], admin["client"], admin["workspace_id"]
    subscribe(c, "agent")
    data = revenue(b)
    assert D(data["mrr"]) == 29 and D(data["arr"]) == 348 and data["paying_customers"] == 1
    month = data["months"][-1]
    assert D(month["gross"]) == 29 and D(month["fees"]) == D("1.95") and D(month["mrr_new"]) == 29

    r = b.post(f"{H}/customers/{ws}/change-plan", json={"plan_key": "team", "interval": "month", "reason": REASON},
               headers=hq_csrf(b))
    assert r.status_code == 200, r.text
    simulate(c, "payment_failed")
    data = revenue(b)
    assert D(data["mrr"]) == 79 and D(data["months"][-1]["mrr_expansion"]) == 50
    assert data["failed_payments_30d"]["count"] == 1

    payments = b.get(f"{H}/customers/{ws}/payments").json()
    charge = next(p for p in payments if p["kind"] == "charge")
    r = b.post(f"{H}/customers/{ws}/refund", json={"payment_id": charge["id"], "reason": REASON}, headers=hq_csrf(b))
    assert r.status_code == 200, r.text
    r = b.post(f"{H}/customers/{ws}/refund", json={"payment_id": charge["id"], "reason": REASON}, headers=hq_csrf(b))
    assert r.status_code == 409 and r.json()["error"]["code"] == "already_refunded"
    assert next(p for p in b.get(f"{H}/customers/{ws}/payments").json() if p["id"] == charge["id"])["refunded"]
    data = revenue(b)
    assert D(data["refunds_30d"]["amount"]) == 29
    assert D(data["total"]["net"]) == D(29 - 29 - D("1.95"))

    simulate(c, "end")
    data = revenue(b)
    assert D(data["mrr"]) == 0 and D(data["months"][-1]["mrr_churned"]) == 79
    assert data["months"][-1]["customers_churned"] == 1

    subscribe(c, "agent")
    assert D(revenue(b)["months"][-1]["mrr_reactivation"]) == 29


def test_yearly_plans_count_a_twelfth(boss, admin, priced):
    subscribe(admin["client"], "agent", "year")
    data = revenue(boss["client"])
    assert D(data["mrr"]) == D("24.17") and D(data["months"][-1]["gross"]) == 290
    renewals = data["upcoming_renewals_30d"]
    assert renewals == []  # a year away


def test_duplicate_webhooks_record_one_payment(admin, priced, owner_engine):
    from app.billing import process_event
    from app.billing_providers import StubProvider

    event = StubProvider()._event
    with owner_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM payments")).scalar() == 0
    subscribe(admin["client"])
    with owner_engine.connect() as conn:
        sub = conn.execute(text("SELECT * FROM subscriptions")).one()
    from app.billing import _ref

    renewal = event(_ref(sub), "subscription.renewed", payment={"id": "stub_pay_same", "kind": "charge"})
    assert process_event("stub", renewal) == "applied"
    assert process_event("stub", renewal) == "duplicate"
    with owner_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM payments WHERE kind = 'charge'")).scalar() == 2


def test_customers_cannot_read_money_tables(admin, priced):
    subscribe(admin["client"])
    for table in ("payments", "mrr_changes", "cost_entries"):
        with pytest.raises(DBAPIError):
            with tenant_session(admin["user_id"], admin["workspace_id"]) as s:
                s.execute(text(f"SELECT * FROM {table}")).all()


def test_staff_change_plan_needs_a_subscription(boss, admin):
    r = boss["client"].post(f"{H}/customers/{admin['workspace_id']}/change-plan",
                            json={"plan_key": "team", "interval": "month", "reason": REASON},
                            headers=hq_csrf(boss["client"]))
    assert r.status_code == 409 and r.json()["error"]["code"] == "no_subscription"


def test_costs_and_profit(boss, admin, priced):
    b = boss["client"]
    subscribe(admin["client"], "agent")
    month = revenue(b)["months"][-1]["month"][:7]
    r = b.post(f"{H}/costs", json={"month": month, "category": "hosting", "amount": "20.00", "note": "Server"},
               headers=hq_csrf(b))
    assert r.status_code == 201, r.text
    assert b.post(f"{H}/costs", json={"month": "2026-13", "category": "hosting", "amount": "1"},
                  headers=hq_csrf(b)).status_code == 422

    data = b.get(f"{H}/dashboard/profit?months=2").json()
    this = data["months"][-1]
    assert D(this["costs"]["hosting"]) == 20 and D(this["net_revenue"]) == D("27.05")
    assert D(this["profit"]) == D("7.05")
    [customer] = data["per_customer"]
    assert customer["username"] == "ana" and D(customer["shared_costs"]) == 20 and D(customer["profit"]) == D("7.05")

    cost_id = b.get(f"{H}/costs").json()[0]["id"]
    assert b.delete(f"{H}/costs/{cost_id}", headers=hq_csrf(b)).status_code == 204
    assert b.get(f"{H}/costs").json() == []


def test_entered_ai_bill_replaces_the_metered_estimate(boss, admin, owner_engine):
    b = boss["client"]
    listing = new_listing(admin["client"])
    with owner_engine.begin() as conn:
        conn.execute(text("""INSERT INTO ai_generations (id, workspace_id, listing_id, user_id, kind, provider, model,
                                                         prompt_version, cost_usd, status)
                             VALUES (gen_random_uuid(), :w, :l, :u, 'full', 'stub', 'stub', 'v1', 1.25, 'ok')"""),
                     {"w": admin["workspace_id"], "l": listing["id"], "u": admin["user_id"]})
    this = b.get(f"{H}/dashboard/profit?months=1").json()["months"][-1]
    assert D(this["ai_metered"]) == D("1.25") and D(this["costs"]["ai"]) == D("1.25")
    b.post(f"{H}/costs", json={"month": this["month"][:7], "category": "ai", "amount": "2.00"}, headers=hq_csrf(b))
    this = b.get(f"{H}/dashboard/profit?months=1").json()["months"][-1]
    assert D(this["costs"]["ai"]) == 2 and D(this["ai_metered"]) == D("1.25")


def test_growth_sources_funnel_and_waitlist(boss, admin, make_client, owner_engine):
    c = make_client()
    r = c.post("/api/v1/auth/signup", json={"email": "ref@example.com", "password": "correct horse battery",
                                            "accept_terms": True, "referral": "REZA"})
    assert r.status_code == 202
    c.post("/api/v1/auth/verify", json={"email": "ref@example.com", "code": last_code("ref@example.com")})
    publish(admin["client"], new_listing(admin["client"])["id"])
    make_client().post("/api/v1/waitlist", json={"name": "W", "email": "w@example.com", "instagram_handle": "",
                                                 "market": "Austin"})

    data = boss["client"].get(f"{H}/dashboard/growth?days=30").json()
    assert data["signups_by_source"]["link"] == 1 and data["signups_by_source"]["referral"] == 1
    assert data["top_referrals"] == [{"code": "REZA", "signups": 1}]
    assert sum(d["total"] for d in data["signups"]) == 2
    assert data["funnel"]["signed_up"] == 2 and data["funnel"]["first_listing_published"] == 1
    assert data["funnel"]["paid"] == 0
    assert data["customers"] == 2 and data["waitlist"] == 1


def test_usage_and_near_limits(boss, admin, owner_engine):
    c = admin["client"]
    publish(c, new_listing(c, "One")["id"])
    new_listing(c, "Two")
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE plans SET listing_limit = 2 WHERE key = 'agent'"))
    data = boss["client"].get(f"{H}/dashboard/usage").json()
    assert data["listings_live"] == 1 and data["listings_total"] == 2
    assert data["database_bytes"] > 0 and data["emails_sent_30d"] is None
    assert [n["username"] for n in data["near_limits"]] == ["ana"]


def test_health(boss, make_client):
    staff_login(make_client(), "founder@scrollwalk.com", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")
    data = boss["client"].get(f"{H}/dashboard/health").json()
    assert data["staff_failed_logins_24h"] == 1 and data["stuck_jobs"] == 0 and data["open_reports"] == 0


def test_dashboard_permissions(boss, make_client):
    helper, _ = add_staff(boss, make_client, permissions=("customers.view",))
    assert helper.get(f"{H}/dashboard/growth").status_code == 200
    assert helper.get(f"{H}/dashboard/usage").status_code == 200
    for path in ("/dashboard/revenue", "/dashboard/profit", "/costs"):
        assert helper.get(f"{H}{path}").status_code == 403
    r = helper.post(f"{H}/customers/00000000-0000-0000-0000-000000000000/refund",
                    json={"payment_id": "00000000-0000-0000-0000-000000000000", "reason": REASON},
                    headers=hq_csrf(helper))
    assert r.status_code == 403


def test_customer_cannot_reach_hq_dashboard(admin):
    assert admin["client"].get(f"{H}/dashboard/revenue").status_code == 401

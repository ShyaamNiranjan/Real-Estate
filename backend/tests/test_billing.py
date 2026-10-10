import io
import json
import zipfile
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app import email
from app.billing import process_event, run_lifecycle
from app.billing_providers import BillingEvent, StubProvider
from app.db import tenant_session
from app.exports import run_exports
from app.storage import get_storage
from tests.auth_helpers import PASSWORD, csrf, mails_to, set_workspace, sign_up
from tests.test_enquiries import enquire
from tests.test_listings import _member, admin, make_ready, new_listing, publish  # noqa: F401
from tests.test_media import add_image

B = "/api/v1/billing"
X = "/api/v1/export"


def subscribe(c, plan="agent", interval="month"):
    r = c.post(f"{B}/checkout", json={"plan_key": plan, "interval": interval}, headers=csrf(c))
    assert r.status_code == 200, r.text
    token = r.json()["url"].split("#", 1)[1]
    r = c.post(f"{B}/stub/checkout-complete", json={"token": token}, headers=csrf(c))
    assert r.status_code == 200, r.text
    return r.json()


def simulate(c, event):
    r = c.post(f"{B}/stub/simulate", json={"event": event}, headers=csrf(c))
    assert r.status_code == 200, r.text
    return r.json()


def workspace(owner_engine, workspace_id):
    with owner_engine.connect() as conn:
        return conn.execute(text("SELECT * FROM workspaces WHERE id = :w"), {"w": workspace_id}).one()


def backdate(owner_engine, workspace_id, **columns):
    """Moves lifecycle dates into the past or near future, e.g. grace_ends_at=timedelta(days=-1)."""
    now = datetime.now(UTC)
    sets = ", ".join(f"{k} = :{k}" for k in columns)
    with owner_engine.begin() as conn:
        conn.execute(text(f"UPDATE workspaces SET {sets} WHERE id = :w"),
                     {**{k: now + v for k, v in columns.items()}, "w": workspace_id})


def subjects(address):
    return [m.subject for m in mails_to(address)]


@pytest.fixture
def lapsed(admin):
    """A published listing, then the subscription ended: 30 days' grace has started."""
    c = admin["client"]
    listing = new_listing(c)
    add_image(c, listing["id"])
    assert publish(c, listing["id"]).status_code == 200
    subscribe(c)
    email.outbox.clear()
    simulate(c, "end")
    return {**admin, "listing": listing}


# ---------- plans and checkout ----------


def test_public_plans_list_seats_and_limits(client):
    plans = {p["key"]: p for p in client.get("/api/v1/public/plans").json()}
    assert plans["agent"]["seats"] == 1 and plans["agent"]["listing_limit"] == 15
    assert plans["team"]["seats"] == 10 and plans["team"]["listing_limit"] == 50
    assert plans["brokerage"]["sales_led"] and plans["brokerage"]["listing_limit"] is None


def test_checkout_activates_the_workspace(client, owner_engine):
    me = sign_up(client, "ana@example.com")
    ws = me["current_workspace_id"]
    set_workspace(owner_engine, ws, subscription_state="trialing")
    data = subscribe(client, "team", "year")
    assert data["state"] == "active" and data["plan_key"] == "team"
    assert data["subscription"]["interval"] == "year" and data["subscription"]["status"] == "active"
    assert "Renews automatically" in data["terms"]["year"]
    assert workspace(owner_engine, ws).kind == "team"
    r = client.post(f"{B}/checkout", json={"plan_key": "agent"}, headers=csrf(client))
    assert r.json()["error"]["code"] == "already_subscribed"


def test_checkout_rules(admin, owner_engine):
    c = admin["client"]
    assert c.post(f"{B}/checkout", json={"plan_key": "brokerage"}, headers=csrf(c)).json()["error"]["code"] == "contact_sales"
    assert c.post(f"{B}/checkout", json={"plan_key": "gold"}, headers=csrf(c)).json()["error"]["code"] == "invalid_plan"
    new_listing(c, "One")
    new_listing(c, "Two")
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE plans SET listing_limit = 1 WHERE key = 'agent'"))
    r = c.post(f"{B}/checkout", json={"plan_key": "agent"}, headers=csrf(c))
    assert r.status_code == 409 and r.json()["error"]["code"] == "plan_too_small"


def test_checkout_token_is_bound_to_the_workspace(admin, make_client, owner_engine):
    url = admin["client"].post(f"{B}/checkout", json={"plan_key": "agent"}, headers=csrf(admin["client"])).json()["url"]
    token = url.split("#", 1)[1]
    other = make_client()
    sign_up(other, "eve@example.com")
    r = other.post(f"{B}/stub/checkout-complete", json={"token": token}, headers=csrf(other))
    assert r.status_code == 400
    r = admin["client"].post(f"{B}/stub/checkout-complete", json={"token": token[:-2] + "xx"},
                             headers=csrf(admin["client"]))
    assert r.status_code == 400


def test_billing_is_admin_only(admin, make_client, owner_engine):
    agent, _ = _member(make_client, owner_engine, admin, ["listings.create", "team.manage_members"])
    for method, path in (("get", B), ("post", f"{B}/checkout"), ("post", f"{B}/cancel"), ("post", f"{B}/portal")):
        kwargs = {"json": {"plan_key": "agent"}} if path.endswith("checkout") else {}
        r = getattr(agent, method)(path, headers=csrf(agent), **kwargs)
        assert r.status_code == 403, (path, r.text)


def test_change_cancel_and_resume(admin, make_client, owner_engine):
    c = admin["client"]
    subscribe(c)
    r = c.post(f"{B}/change", json={"plan_key": "agent"}, headers=csrf(c))
    assert r.json()["error"]["code"] == "same_plan"
    data = c.post(f"{B}/change", json={"plan_key": "team", "interval": "year"}, headers=csrf(c)).json()
    assert data["plan_key"] == "team" and data["subscription"]["interval"] == "year"

    # Downgrading needs to fit: two people can't go back to a one-seat plan.
    _member(make_client, owner_engine, admin, ["listings.create"])
    r = c.post(f"{B}/change", json={"plan_key": "agent"}, headers=csrf(c))
    assert r.status_code == 409 and r.json()["error"]["code"] == "plan_too_small"

    data = c.post(f"{B}/cancel", headers=csrf(c)).json()
    assert data["subscription"]["cancel_at_period_end"] and data["state"] == "active"
    assert c.post(f"{B}/cancel", headers=csrf(c)).json()["error"]["code"] == "already_cancelled"
    data = c.post(f"{B}/resume", headers=csrf(c)).json()
    assert not data["subscription"]["cancel_at_period_end"]
    assert c.post(f"{B}/portal", headers=csrf(c)).json()["url"].startswith("https://testserver/studio/billing")


# ---------- provider events ----------


def _event(workspace_id, **changes) -> BillingEvent:
    now = datetime.now(UTC)
    base = dict(event_id="evt_1", type="subscription.created", occurred_at=now, workspace_id=workspace_id,
                subscription_id="sub_1", customer_id="cus_1", plan_key="agent", interval="month", status="active",
                current_period_end=now + timedelta(days=30), cancel_at_period_end=False)
    return BillingEvent(**{**base, **changes})


def test_events_apply_once_and_stale_events_are_ignored(client, owner_engine):
    from uuid import UUID

    me = sign_up(client, "ana@example.com")
    ws = UUID(me["current_workspace_id"])
    assert process_event("stub", _event(ws)) == "applied"
    assert process_event("stub", _event(ws)) == "duplicate"
    old = datetime.now(UTC) - timedelta(hours=1)
    assert process_event("stub", _event(ws, event_id="evt_0", occurred_at=old, status="expired")) == "stale"
    assert workspace(owner_engine, ws).subscription_state == "active"
    assert process_event("stub", _event(ws, event_id="evt_2", plan_key="gold")) == "rejected"
    with owner_engine.connect() as conn:
        rows = conn.execute(text("SELECT provider_event_id, processed_at IS NOT NULL AS done, error FROM billing_events "
                                 "ORDER BY received_at")).all()
    assert [(r.provider_event_id, r.done) for r in rows] == [("evt_1", True), ("evt_0", True), ("evt_2", False)]
    assert "unknown plan" in rows[2].error


def test_webhook_needs_a_valid_signature(client, owner_engine):
    me = sign_up(client, "ana@example.com")
    from uuid import UUID

    body = json.dumps(_event(UUID(me["current_workspace_id"])).payload()).encode()
    url = f"{B}/webhooks/stub"
    assert client.post(url, content=body).status_code == 400
    assert client.post(url, content=body, headers={"x-stub-signature": "nope"}).status_code == 400
    assert client.post(f"{B}/webhooks/paddle", content=body).status_code == 404
    signed = {"x-stub-signature": StubProvider().sign_webhook(body)}
    r = client.post(url, content=body, headers=signed)
    assert r.status_code == 200 and r.json() == {"status": "applied"}
    assert client.post(url, content=body, headers=signed).json() == {"status": "duplicate"}
    assert workspace(owner_engine, me["current_workspace_id"]).subscription_state == "active"


def test_api_role_cannot_read_billing_events(admin):
    with tenant_session(admin["user_id"], admin["workspace_id"]) as s:
        with pytest.raises(ProgrammingError):
            s.execute(text("SELECT * FROM billing_events")).all()


def test_payment_failure_keeps_the_site_live(admin, owner_engine):
    subscribe(admin["client"])
    data = simulate(admin["client"], "payment_failed")
    assert data["subscription"]["status"] == "past_due" and data["state"] == "active"
    data = simulate(admin["client"], "renew")
    assert data["subscription"]["status"] == "active"


# ---------- lapse → grace → offline → deletion ----------


def test_lapse_starts_thirty_days_grace(lapsed, owner_engine):
    ws = workspace(owner_engine, lapsed["workspace_id"])
    assert ws.subscription_state == "grace"
    assert timedelta(days=29) < ws.grace_ends_at - ws.lapsed_at <= timedelta(days=30)
    assert timedelta(days=181) < ws.delete_after - ws.lapsed_at <= timedelta(days=182)
    assert subjects("admin@example.com") == ["Your Scrollwalk subscription has ended"]
    c = lapsed["client"]
    r = c.post("/api/v1/listings", json={"title": "New", "experience_type": "photo"}, headers=csrf(c))
    assert r.status_code == 403


def test_grace_reminders_then_offline_then_deletion_warnings(lapsed, owner_engine):
    ws_id, c = lapsed["workspace_id"], lapsed["client"]
    assert c.get("/api/v1/public/sites/ana/listings/villa-aurelia").status_code == 200
    email.outbox.clear()

    backdate(owner_engine, ws_id, grace_ends_at=timedelta(days=6, hours=12))
    run_lifecycle()
    run_lifecycle()
    assert subjects("admin@example.com") == ["Your site goes offline in 7 days"]
    backdate(owner_engine, ws_id, grace_ends_at=timedelta(hours=12))
    run_lifecycle()
    assert subjects("admin@example.com")[-1] == "Your site goes offline tomorrow"

    backdate(owner_engine, ws_id, grace_ends_at=timedelta(minutes=-1))
    assert run_lifecycle()["offline"] == 1
    assert workspace(owner_engine, ws_id).subscription_state == "offline"
    assert subjects("admin@example.com")[-1] == "Your site is offline"
    assert c.get("/api/v1/public/sites/ana").status_code == 503

    backdate(owner_engine, ws_id, delete_after=timedelta(days=29))
    run_lifecycle()
    backdate(owner_engine, ws_id, delete_after=timedelta(days=6))
    run_lifecycle()
    run_lifecycle()
    assert subjects("admin@example.com")[-2:] == ["Your Scrollwalk account will be deleted in 30 days",
                                                  "Your Scrollwalk account will be deleted in 7 days"]
    assert len(mails_to("admin@example.com")) == 5


def test_resubscribing_restores_everything(lapsed, owner_engine):
    ws_id, c = lapsed["workspace_id"], lapsed["client"]
    backdate(owner_engine, ws_id, grace_ends_at=timedelta(minutes=-1))
    run_lifecycle()
    data = subscribe(c)
    assert data["state"] == "active" and data["grace_ends_at"] is None and data["delete_after"] is None
    with owner_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM lifecycle_notices WHERE workspace_id = :w"),
                            {"w": ws_id}).scalar() == 0

    # Lapsing again sends the grace email again.
    email.outbox.clear()
    simulate(c, "end")
    assert subjects("admin@example.com") == ["Your Scrollwalk subscription has ended"]


def test_deletion_removes_everything_and_holds_the_username(lapsed, owner_engine, make_client):
    ws_id, c = lapsed["workspace_id"], lapsed["client"]
    assert enquire(c, ws_id, slug=lapsed["listing"]["slug"]).status_code == 202
    c.post(X, headers=csrf(c))
    run_exports()
    storage = get_storage()
    assert storage.list_prefix(f"private/ws/{ws_id}/")

    backdate(owner_engine, ws_id, grace_ends_at=timedelta(minutes=-1))
    run_lifecycle()
    backdate(owner_engine, ws_id, delete_after=timedelta(minutes=-1))
    assert run_lifecycle()["deleted"] == 1

    with owner_engine.connect() as conn:
        for table in ("listings", "media", "enquiries", "listing_sections", "exports", "subscriptions",
                      "roles", "workspace_profiles"):
            n = conn.execute(text(f"SELECT count(*) FROM {table} WHERE workspace_id = :w"), {"w": ws_id}).scalar()
            assert n == 0, table
        ws = conn.execute(text("SELECT * FROM workspaces WHERE id = :w"), {"w": ws_id}).one()
        assert ws.deleted_at is not None and ws.username is None
    assert storage.list_prefix(f"private/ws/{ws_id}/") == []
    assert storage.list_prefix(f"public/ws/{ws_id}/") == []

    # For 60 days the address says "no longer available" and only the previous owner can reclaim it.
    r = c.get("/api/v1/public/sites/ana")
    assert r.status_code == 410 and r.json()["error"]["code"] == "no_longer_available"
    assert c.get("/api/v1/public/sites/nobody-here").status_code == 404

    other = make_client()
    other_ws = sign_up(other, "eve@example.com")["current_workspace_id"]
    set_workspace(owner_engine, other_ws, subscription_state="active")
    claim = {"username": "ana", "confirm_permanent": True}
    r = other.post("/api/v1/workspace/username", json=claim, headers=csrf(other))
    assert r.status_code == 409 and r.json()["error"]["code"] == "username_taken"

    r = c.post("/api/v1/auth/login", json={"email": "admin@example.com", "password": PASSWORD})
    assert r.status_code == 200, r.text
    new_ws = r.json()["current_workspace_id"]
    assert new_ws != ws_id
    set_workspace(owner_engine, new_ws, subscription_state="active")
    r = c.post("/api/v1/workspace/username", json=claim, headers=csrf(c))
    assert r.status_code == 200, r.text
    assert c.get("/api/v1/public/sites/ana").status_code != 410


def test_purge_refuses_workspaces_that_are_not_due(admin):
    with tenant_session(None, admin["workspace_id"]) as s:
        assert s.execute(text("SELECT workspace_purge(:w)"), {"w": admin["workspace_id"]}).scalar() is False


def test_trial_and_renewal_reminders(client, owner_engine):
    me = sign_up(client, "ana@example.com")
    ws = me["current_workspace_id"]
    make_ready(client, owner_engine, ws, state="trialing", plan="agent")
    listing = new_listing(client, "Trial Villa")
    assert publish(client, listing["id"]).status_code == 200
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE listings SET trial_expires_at = now() + interval '6 days 12 hours' WHERE id = :l"),
                     {"l": listing["id"]})
    run_lifecycle()
    run_lifecycle()
    assert subjects("ana@example.com")[-1] == '"Trial Villa" goes offline in 7 days'
    assert subjects("ana@example.com").count('"Trial Villa" goes offline in 7 days') == 1

    subscribe(client, "agent", "year")
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE subscriptions SET current_period_end = now() + interval '5 days'"))
    run_lifecycle()
    run_lifecycle()
    assert subjects("ana@example.com").count("Your annual Scrollwalk plan renews soon") == 1


# ---------- download everything ----------


def test_export_contains_listings_media_and_enquiries(admin):
    c = admin["client"]
    listing = new_listing(c)
    add_image(c, listing["id"])
    publish(c, listing["id"])
    assert enquire(c, admin["workspace_id"], slug=listing["slug"]).status_code == 202

    r = c.post(X, headers=csrf(c))
    assert r.status_code == 202 and r.json()["status"] == "queued"
    assert c.post(X, headers=csrf(c)).json()["error"]["code"] == "export_in_progress"
    assert run_exports() == 1
    [item] = c.get(X).json()
    assert item["status"] == "ready" and item["bytes"] > 0 and item["download_url"]
    assert subjects("admin@example.com")[-1] == "Your Scrollwalk download is ready"

    z = zipfile.ZipFile(io.BytesIO(finished_zip(admin)))
    names = z.namelist()
    assert {"README.txt", "workspace.json", "enquiries.csv"} <= set(names)
    assert f"listings/{listing['slug']}/listing.json" in names
    assert any(n.startswith(f"listings/{listing['slug']}/gallery/") for n in names)
    assert "bea@example.com" in z.read("enquiries.csv").decode("utf-8-sig")
    info = json.loads(z.read(f"listings/{listing['slug']}/listing.json"))
    assert info["title"] == "Villa Aurelia" and info["sections"]


def finished_zip(admin) -> bytes:
    with tenant_session(admin["user_id"], admin["workspace_id"]) as s:
        key = s.execute(text("SELECT key FROM exports WHERE status = 'ready'")).scalar_one()
    return get_storage().read(key)


def test_exports_are_limited_per_day(admin, owner_engine):
    c = admin["client"]
    for _ in range(3):
        assert c.post(X, headers=csrf(c)).status_code == 202
        run_exports()
    r = c.post(X, headers=csrf(c))
    assert r.status_code == 429 and r.json()["error"]["code"] == "export_limit"


def test_exports_are_admin_only_even_in_the_database(admin, make_client, owner_engine):
    c = admin["client"]
    c.post(X, headers=csrf(c))
    agent, _ = _member(make_client, owner_engine, admin, ["listings.create", "enquiries.view_all"])
    assert agent.post(X, headers=csrf(agent)).status_code == 403
    assert agent.get(X).status_code == 403
    with owner_engine.connect() as conn:
        agent_id = conn.execute(text("SELECT id FROM users WHERE email = 'agent@example.com'")).scalar_one()
    with tenant_session(agent_id, admin["workspace_id"]) as s:
        assert s.execute(text("SELECT count(*) FROM exports")).scalar() == 0


def test_exports_are_invisible_to_other_workspaces(admin, make_client):
    c = admin["client"]
    c.post(X, headers=csrf(c))
    run_exports()
    other = make_client()
    me = sign_up(other, "eve@example.com")
    assert other.get(X).json() == []
    with tenant_session(me["user"]["id"], me["current_workspace_id"]) as s:
        assert s.execute(text("SELECT count(*) FROM exports")).scalar() == 0
        assert s.execute(text("SELECT count(*) FROM subscriptions")).scalar() == 0


def test_export_still_works_when_offline(lapsed, owner_engine):
    backdate(owner_engine, lapsed["workspace_id"], grace_ends_at=timedelta(minutes=-1))
    run_lifecycle()
    c = lapsed["client"]
    assert c.post(X, headers=csrf(c)).status_code == 202
    assert run_exports() == 1


def test_downloads_expire_after_seven_days(admin, owner_engine):
    c = admin["client"]
    c.post(X, headers=csrf(c))
    run_exports()
    with owner_engine.begin() as conn:
        key = conn.execute(text("UPDATE exports SET expires_at = now() - interval '1 minute' RETURNING key")).scalar_one()
    assert run_lifecycle()["exports_expired"] == 1
    assert c.get(X).json()[0]["status"] == "expired"
    assert get_storage().head(key) is None

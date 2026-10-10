from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app import email, indexnow
from app.billing import run_lifecycle
from app.config import get_settings
from app.db import public_session, tenant_session
from tests.auth_helpers import PASSWORD, csrf, mails_to, set_workspace, sign_up
from tests.test_billing import backdate, subscribe
from tests.test_hq import H, add_staff, audit_actions, boss, hq_csrf  # noqa: F401
from tests.test_listings import _member, admin, edit, new_listing, publish  # noqa: F401

W = "/api/v1/workspace"
REASON = {"reason": "Support ticket 1234"}


def live_listing(c, title="Villa Aurelia"):
    listing = new_listing(c, title)
    r = publish(c, listing["id"])
    assert r.status_code == 200, r.text
    return listing


def hq_post(b, path, body=None):
    return b.post(f"{H}{path}", json=body if body is not None else REASON, headers=hq_csrf(b))


# ---------- freeze, ban, sign-out ----------


def test_freeze_hides_public_pages_and_blocks_changes(boss, admin):
    c, ws = admin["client"], admin["workspace_id"]
    listing = live_listing(c)
    assert c.get(f"/api/v1/public/sites/ana/listings/{listing['slug']}").status_code == 200

    r = hq_post(boss["client"], f"/customers/{ws}/freeze", {"frozen": True, "reason": "Fraud report"})
    assert r.status_code == 200 and r.json()["status"] == "frozen"
    assert c.get(f"/api/v1/public/sites/ana/listings/{listing['slug']}").status_code == 404
    assert c.get("/api/v1/public/sites/ana").status_code == 404
    assert c.get("/api/v1/listings").status_code == 200  # can still look
    r = edit(c, listing["id"], title="New title")
    assert r.status_code == 403 and r.json()["error"]["code"] == "account_frozen"

    assert hq_post(boss["client"], f"/customers/{ws}/freeze", {"frozen": False, "reason": "Cleared"}).status_code == 200
    assert edit(c, listing["id"], title="New title").status_code == 200
    assert c.get(f"/api/v1/public/sites/ana/listings/{listing['slug']}").status_code == 200
    assert audit_actions()[-2:] == ["customer.frozen", "customer.unfrozen"]


def test_ban_signs_out_and_blocks_sign_in(boss, admin, make_client):
    c = admin["client"]
    r = hq_post(boss["client"], f"/users/{admin['user_id']}/ban", {"banned": True, "reason": "Spam listings"})
    assert r.status_code == 200
    assert c.get("/api/v1/auth/me").status_code == 401
    other = make_client()
    r = other.post("/api/v1/auth/login", json={"email": "admin@example.com", "password": PASSWORD})
    assert r.status_code == 403 and r.json()["error"]["code"] == "account_banned"
    with public_session() as s:  # their workspace is frozen too
        assert s.execute(text("SELECT count(*) FROM workspaces WHERE id = :w"), {"w": admin["workspace_id"]}).scalar() == 0

    assert hq_post(boss["client"], f"/users/{admin['user_id']}/ban", {"banned": False, "reason": "Appeal"}).status_code == 200
    r = other.post("/api/v1/auth/login", json={"email": "admin@example.com", "password": PASSWORD})
    assert r.status_code == 200


def test_sign_out_everywhere(boss, admin):
    r = hq_post(boss["client"], f"/users/{admin['user_id']}/sign-out")
    assert r.status_code == 200
    assert admin["client"].get("/api/v1/auth/me").status_code == 401
    assert audit_actions()[-1] == "user.signed_out"


def test_actions_need_a_reason(boss, admin):
    r = hq_post(boss["client"], f"/customers/{admin['workspace_id']}/freeze", {"frozen": True, "reason": ""})
    assert r.status_code == 422


# ---------- "log in as them" ----------


def test_impersonation_is_read_only_and_audited(boss, admin, make_client):
    listing = new_listing(admin["client"])
    b = boss["client"]
    r = hq_post(b, f"/customers/{admin['workspace_id']}/impersonate", {"reason": "Customer asked for help"})
    assert r.status_code == 200, r.text
    assert r.json()["url"].endswith("/studio")

    me = b.get("/api/v1/auth/me").json()
    assert me["read_only"] is True and me["user"]["id"] == admin["user_id"]
    assert b.get("/api/v1/listings").status_code == 200
    r = b.patch(f"/api/v1/listings/{listing['id']}", json={"title": "Hijack"}, headers=csrf(b))
    assert r.status_code == 403 and r.json()["error"]["code"] == "read_only_session"
    r = b.post("/api/v1/auth/logout-all", headers=csrf(b))
    assert r.status_code == 403
    assert audit_actions()[-1] == "customer.impersonated"
    assert admin["client"].get("/api/v1/auth/me").json()["read_only"] is False


def test_impersonation_needs_its_own_permission(boss, admin, make_client):
    helper, _ = add_staff(boss, make_client, permissions=("customers.view", "customers.manage"))
    r = hq_post(helper, f"/customers/{admin['workspace_id']}/impersonate", {"reason": "Customer asked for help"})
    assert r.status_code == 403


# ---------- staff-only columns ----------


@pytest.mark.parametrize("statement", [
    "UPDATE workspaces SET frozen_at = NULL WHERE id = :w",
    "UPDATE workspaces SET deletion_requested_at = NULL WHERE id = :w",
    "UPDATE users SET banned_at = NULL WHERE id = :u",
    "UPDATE listings SET taken_down_at = NULL WHERE workspace_id = :w",
    "UPDATE memberships SET is_admin = false WHERE workspace_id = :w",
    "UPDATE sessions SET read_only = false WHERE user_id = :u",
])
def test_customers_cannot_change_staff_only_columns(admin, owner_engine, statement):
    new_listing(admin["client"])
    with owner_engine.begin() as conn:  # make every guarded column non-null so the UPDATE is a real change
        conn.execute(text("UPDATE workspaces SET frozen_at = now(), deletion_requested_at = now()"))
        conn.execute(text("UPDATE users SET banned_at = NULL"))
        conn.execute(text("UPDATE listings SET taken_down_at = now()"))
        conn.execute(text("ALTER TABLE sessions DISABLE TRIGGER sessions_guard"))
        conn.execute(text("UPDATE sessions SET read_only = true"))
        conn.execute(text("ALTER TABLE sessions ENABLE TRIGGER sessions_guard"))
    if "banned_at" in statement:
        statement = "UPDATE users SET banned_at = now() WHERE id = :u"
    with pytest.raises(DBAPIError):
        with tenant_session(admin["user_id"], admin["workspace_id"]) as s:
            s.execute(text(statement), {"w": admin["workspace_id"], "u": admin["user_id"]})


def test_customers_cannot_create_read_only_sessions(admin):
    with pytest.raises(DBAPIError):
        with tenant_session(admin["user_id"], admin["workspace_id"]) as s:
            s.execute(text("""INSERT INTO sessions (token_hash, user_id, workspace_id, expires_at, read_only)
                              VALUES ('\\x00', :u, :w, now() + interval '1 hour', true)"""),
                      {"u": admin["user_id"], "w": admin["workspace_id"]})


def test_customers_cannot_call_staff_functions(admin):
    with pytest.raises(DBAPIError):
        with tenant_session(admin["user_id"], admin["workspace_id"]) as s:
            s.execute(text("SELECT hq_set_frozen(:w, false, '')"), {"w": admin["workspace_id"]})


# ---------- reports and takedowns ----------


def report(c, slug, **overrides):
    body = {"username": "ana", "listing_slug": slug, "category": "copyright",
            "details": "These are my photos, used without permission.", "name": "Pat", "email": "pat@example.com",
            **overrides}
    return c.post("/api/v1/public/reports", json=body)


def test_report_takedown_and_restore(boss, admin, make_client):
    c = admin["client"]
    listing = live_listing(c)
    anon = make_client()
    assert report(anon, listing["slug"]).status_code == 202
    assert report(anon, "no-such-home").status_code == 404
    assert report(anon, listing["slug"], trap="x").status_code == 202  # honeypot: silently dropped

    b = boss["client"]
    reports = b.get(f"{H}/reports").json()
    assert len(reports) == 1 and reports[0]["listing_path"] == f"/ana/{listing['slug']}"
    assert reports[0]["reporter_email"] == "pat@example.com"
    r = hq_post(b, f"/reports/{reports[0]['id']}/resolve", {"action": "takedown", "reason": "Copyright notice"})
    assert r.status_code == 200 and r.json()["status"] == "actioned" and r.json()["listing_taken_down"]
    assert hq_post(b, f"/reports/{reports[0]['id']}/resolve", {"action": "dismiss", "reason": "again"}).status_code == 409

    assert c.get(f"/api/v1/public/sites/ana/listings/{listing['slug']}").status_code == 404
    assert any("taken down" in m.subject for m in mails_to("admin@example.com"))
    r = publish(c, listing["id"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "publish_blocked"
    assert "taken_down" in [x["code"] for x in c.get(f"/api/v1/listings/{listing['id']}").json()["publish_blockers"]]

    assert hq_post(b, f"/listings/{listing['id']}/restore", {"reason": "Counter-notice accepted"}).status_code == 200
    assert publish(c, listing["id"]).status_code == 200
    assert audit_actions()[-2:] == ["listing.taken_down", "listing.restored"]


def test_dismissed_reports_change_nothing(boss, admin, make_client):
    listing = live_listing(admin["client"])
    report(make_client(), listing["slug"])
    b = boss["client"]
    report_id = b.get(f"{H}/reports").json()[0]["id"]
    assert hq_post(b, f"/reports/{report_id}/resolve", {"action": "dismiss", "reason": "Not a real issue"}).status_code == 200
    assert b.get(f"{H}/reports").json() == []
    assert len(b.get(f"{H}/reports?status=dismissed").json()) == 1
    assert admin["client"].get(f"/api/v1/public/sites/ana/listings/{listing['slug']}").status_code == 200


def test_reports_need_moderation_permission(boss, admin, make_client):
    helper, _ = add_staff(boss, make_client, permissions=("customers.view",))
    assert helper.get(f"{H}/reports").status_code == 403


# ---------- trials and free plans ----------


def test_extend_trial(boss, admin, owner_engine):
    ws = admin["workspace_id"]
    b = boss["client"]
    r = hq_post(b, f"/customers/{ws}/extend-trial", {"days": 7, "extra_listings": 2, **REASON})
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_trialing"

    set_workspace(owner_engine, ws, subscription_state="trialing", trial_listing_allowance=3)
    listing = live_listing(admin["client"])
    with owner_engine.connect() as conn:
        before = conn.execute(text("SELECT trial_expires_at FROM listings WHERE id = :l"), {"l": listing["id"]}).scalar()
    assert before is not None
    assert hq_post(b, f"/customers/{ws}/extend-trial", {"days": 7, "extra_listings": 2, **REASON}).status_code == 200
    with owner_engine.connect() as conn:
        after = conn.execute(text("SELECT trial_expires_at FROM listings WHERE id = :l"), {"l": listing["id"]}).scalar()
        allowance = conn.execute(text("SELECT trial_listing_allowance FROM workspaces WHERE id = :w"), {"w": ws}).scalar()
    assert after - before == timedelta(days=7) and allowance == 5


def test_give_and_end_a_free_plan(boss, admin, owner_engine):
    ws = admin["workspace_id"]
    set_workspace(owner_engine, ws, subscription_state="none", plan_key=None)
    b = boss["client"]
    assert hq_post(b, f"/customers/{ws}/give-plan", {"plan_key": "nope", **REASON}).status_code == 422
    r = hq_post(b, f"/customers/{ws}/give-plan", {"plan_key": "team", **REASON})
    assert r.status_code == 200
    data = b.get(f"{H}/customers/{ws}").json()
    assert data["state"] == "active" and data["plan_key"] == "team"

    email.outbox.clear()
    assert hq_post(b, f"/customers/{ws}/end-free-plan").status_code == 200
    assert b.get(f"{H}/customers/{ws}").json()["state"] == "grace"
    assert mails_to("admin@example.com")
    assert hq_post(b, f"/customers/{ws}/end-free-plan").status_code == 409


def test_cannot_give_a_free_plan_over_a_paid_one(boss, admin):
    subscribe(admin["client"])
    r = hq_post(boss["client"], f"/customers/{admin['workspace_id']}/give-plan", {"plan_key": "team", **REASON})
    assert r.status_code == 409 and r.json()["error"]["code"] == "has_subscription"


# ---------- deletion requests ----------


def test_customer_requests_deletion_then_it_is_purged(admin, owner_engine):
    c, ws = admin["client"], admin["workspace_id"]
    live_listing(c)
    r = c.post(f"{W}/delete", json={"password": "wrong password", "confirm": "DELETE"}, headers=csrf(c))
    assert r.status_code == 401
    r = c.post(f"{W}/delete", json={"password": PASSWORD, "confirm": "DELETE"}, headers=csrf(c))
    assert r.status_code == 200 and r.json()["status"] == "scheduled"
    assert c.get("/api/v1/public/sites/ana").status_code == 503  # offline, like a lapsed account
    assert any("deleted" in m.subject for m in mails_to("admin@example.com"))

    backdate(owner_engine, ws, delete_after=timedelta(minutes=-1))
    assert run_lifecycle()["deleted"] == 1
    with owner_engine.connect() as conn:
        assert conn.execute(text("SELECT deleted_at FROM workspaces WHERE id = :w"), {"w": ws}).scalar() is not None


def test_deletion_waits_for_a_running_subscription_to_be_cancelled(admin):
    c = admin["client"]
    subscribe(c)
    r = c.post(f"{W}/delete", json={"password": PASSWORD, "confirm": "DELETE"}, headers=csrf(c))
    assert r.status_code == 409 and r.json()["error"]["code"] == "cancel_subscription_first"


def test_only_the_admin_can_request_deletion(admin, make_client, owner_engine):
    member, _ = _member(make_client, owner_engine, admin, ["listings.create"])
    r = member.post(f"{W}/delete", json={"password": PASSWORD, "confirm": "DELETE"}, headers=csrf(member))
    assert r.status_code == 403


def test_staff_schedule_deletion(boss, admin):
    r = hq_post(boss["client"], f"/customers/{admin['workspace_id']}/delete")
    assert r.status_code == 200 and r.json()["status"] == "scheduled"
    assert boss["client"].get(f"{H}/customers/{admin['workspace_id']}").json()["state"] == "offline"


# ---------- Admin transfer ----------


def test_admin_transfer(admin, make_client, owner_engine):
    c = admin["client"]
    member, membership_id = _member(make_client, owner_engine, admin, ["listings.create"])
    role_id = c.get("/api/v1/team/roles").json()[0]["id"]
    body = {"member_id": membership_id, "my_new_role_id": role_id, "password": "wrong password"}
    assert c.post("/api/v1/team/transfer-admin", json=body, headers=csrf(c)).status_code == 401
    body["password"] = PASSWORD
    r = c.post("/api/v1/team/transfer-admin", json=body, headers=csrf(c))
    assert r.status_code == 200, r.text
    assert any("now the Admin" in m.subject for m in mails_to("agent@example.com"))
    assert any("handed over" in m.subject for m in mails_to("admin@example.com"))

    assert member.get(W).json()["is_admin"] is True
    assert c.post("/api/v1/team/transfer-admin", json=body, headers=csrf(c)).status_code == 403


# ---------- plans and settings ----------


def test_edit_and_create_plans(boss, make_client):
    b = boss["client"]
    plans = b.get(f"{H}/plans").json()
    agent = next(p for p in plans if p["key"] == "agent")
    agent.update(listing_limit=20, price_month="39.00")
    key = agent.pop("key")
    agent.pop("workspaces")
    r = b.put(f"{H}/plans/{key}", json=agent, headers=hq_csrf(b))
    assert r.status_code == 200, r.text
    public = make_client().get("/api/v1/public/plans").json()
    assert next(p for p in public if p["key"] == "agent")["listing_limit"] == 20

    r = b.post(f"{H}/plans", json={**agent, "key": "solo_plus", "name": "Solo Plus", "is_public": False},
               headers=hq_csrf(b))
    assert r.status_code == 201
    assert b.post(f"{H}/plans", json={**agent, "key": "solo_plus"}, headers=hq_csrf(b)).status_code == 409
    assert "solo_plus" not in [p["key"] for p in make_client().get("/api/v1/public/plans").json()]
    assert audit_actions()[-2:] == ["plan.updated", "plan.created"]


def test_plan_editing_needs_permission(boss, make_client):
    helper, _ = add_staff(boss, make_client, permissions=("customers.view",))
    assert helper.get(f"{H}/plans").status_code == 403


def test_trial_video_limit_setting(boss, admin):
    from app.plans import trial_video_max_bytes

    b = boss["client"]
    assert b.get(f"{H}/settings").json() == {"trial_video_max_mb": 500}
    r = b.put(f"{H}/settings", json={"trial_video_max_mb": 800}, headers=hq_csrf(b))
    assert r.status_code == 200
    with tenant_session(admin["user_id"], admin["workspace_id"]) as s:
        assert trial_video_max_bytes(s) == 800 * 1024 * 1024


# ---------- announcements ----------


def test_announcement_banner_reaches_its_audience(boss, admin, make_client, owner_engine):
    b = boss["client"]
    trial = make_client()
    trial_ws = sign_up(trial, "trial@example.com")["current_workspace_id"]
    set_workspace(owner_engine, trial_ws, subscription_state="trialing")

    r = hq_post(b, "/announcements", {"title": "New feature", "body": "Floor plans are here.", "channel": "banner",
                                      "audience": "paying"})
    assert r.status_code == 201
    assert [a["title"] for a in admin["client"].get(f"{W}/announcements").json()] == ["New feature"]
    assert trial.get(f"{W}/announcements").json() == []

    hq_post(b, f"/announcements/{r.json()['id']}/end", {})
    assert admin["client"].get(f"{W}/announcements").json() == []


def test_email_announcement_goes_to_admins(boss, admin):
    email.outbox.clear()
    r = hq_post(boss["client"], "/announcements", {"title": "Maintenance tonight", "body": "Down 2-3am UTC.",
                                                   "channel": "email", "audience": "all"})
    assert r.status_code == 201 and r.json()["emails_sent"] == 1
    assert [m.subject for m in mails_to("admin@example.com")] == ["Maintenance tonight"]
    assert admin["client"].get(f"{W}/announcements").json() == []  # email only, no banner


# ---------- legal versions ----------


def test_material_legal_change_must_be_accepted(boss, admin, make_client):
    b, c = boss["client"], admin["client"]
    assert c.get("/api/v1/auth/me").json()["legal_pending"] == []
    email.outbox.clear()
    r = hq_post(b, "/legal", {"document": "terms", "version": "2026-11", "material": True,
                              "summary": "Clearer refund rules.", "effective_in_days": 0})
    assert r.status_code == 201, r.text
    assert any("Terms of Service" in m.subject for m in mails_to("admin@example.com"))

    pending = c.get("/api/v1/auth/me").json()["legal_pending"]
    assert pending == [{"document": "terms", "version": "2026-11", "summary": "Clearer refund rules."}]
    r = c.post("/api/v1/auth/legal/accept", json={"documents": [{"document": "terms", "version": "2026-10-draft"}]},
               headers=csrf(c))
    assert r.status_code == 409
    r = c.post("/api/v1/auth/legal/accept", json={"documents": [{"document": "terms", "version": "2026-11"}]},
               headers=csrf(c))
    assert r.status_code == 200 and r.json()["legal_pending"] == []

    newcomer = make_client()  # new sign-ups accept the current version straight away
    sign_up(newcomer, "new@example.com")
    assert newcomer.get("/api/v1/auth/me").json()["legal_pending"] == []
    assert hq_post(b, "/legal", {"document": "terms", "version": "2026-11", "material": False}).status_code == 409


def test_legal_versions_are_super_admin_only(boss, make_client):
    helper, _ = add_staff(boss, make_client, permissions=("customers.view", "pricing.edit", "audit.view"))
    assert helper.get(f"{H}/legal").status_code == 403


# ---------- IndexNow ----------


def test_indexnow_pings_on_publish_and_takedown(boss, admin, monkeypatch):
    monkeypatch.setenv("INDEXNOW_KEY", "test-key-1234")
    monkeypatch.setattr(indexnow, "_post", lambda *a, **k: None)
    get_settings.cache_clear()
    indexnow.sent.clear()
    try:
        listing = live_listing(admin["client"])
        url = f"https://scrollwalk.com/ana/{listing['slug']}"
        assert url in indexnow.sent[-1]
        hq_post(boss["client"], f"/listings/{listing['id']}/takedown", {"reason": "Fraudulent listing"})
        assert indexnow.sent[-1] == [url]
    finally:
        monkeypatch.delenv("INDEXNOW_KEY")
        get_settings.cache_clear()


def test_indexnow_is_off_without_a_key(admin):
    indexnow.sent.clear()
    live_listing(admin["client"])
    assert indexnow.sent == []

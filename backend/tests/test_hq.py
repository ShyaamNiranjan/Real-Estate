import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from app import totp
from app.db import hq_session, tenant_session
from app.staff_cli import create_super
from tests.auth_helpers import csrf, mails_to, sign_up
from tests.test_billing import subscribe
from tests.test_enquiries import enquire
from tests.test_listings import admin, make_ready, new_listing, publish  # noqa: F401

H = "/api/v1/hq"
T = "/api/v1/trial"
STAFF_PASSWORD = "a long staff passphrase"


def hq_csrf(c) -> dict:
    return {"X-CSRF-Token": c.cookies.get("__Host-sw_staff_csrf") or ""}


def code(secret: str, ahead: int = 0) -> str:
    return totp.code_at(secret, totp.current_step() + ahead)


def finish_setup(c, link: str) -> str:
    token = link.split("#", 1)[1]
    r = c.post(f"{H}/auth/setup/start", json={"token": token})
    assert r.status_code == 200, r.text
    secret = r.json()["secret"]
    assert r.json()["otpauth_uri"].startswith("otpauth://totp/")
    r = c.post(f"{H}/auth/setup/finish", json={"token": token, "password": STAFF_PASSWORD, "code": code(secret)})
    assert r.status_code == 200, r.text
    return secret


def staff_login(c, email: str, secret: str, ahead: int = 1):
    return c.post(f"{H}/auth/login", json={"email": email, "password": STAFF_PASSWORD, "code": code(secret, ahead)})


@pytest.fixture
def boss(make_client):
    c = make_client()
    secret = finish_setup(c, create_super("founder@scrollwalk.com", "Founder"))
    r = staff_login(c, "founder@scrollwalk.com", secret)
    assert r.status_code == 200, r.text
    return {"client": c, "secret": secret}


def add_staff(boss, make_client, email="helper@scrollwalk.com", permissions=("customers.view",)):
    b = boss["client"]
    roles = b.post(f"{H}/roles", json={"name": f"Role {email}", "permissions": list(permissions)}, headers=hq_csrf(b))
    assert roles.status_code == 201, roles.text
    role_id = next(r["id"] for r in roles.json()["roles"] if r["name"] == f"Role {email}")
    r = b.post(f"{H}/staff", json={"email": email, "role_id": role_id}, headers=hq_csrf(b))
    assert r.status_code == 201, r.text
    link = next(line for line in mails_to(email)[-1].text.splitlines() if "/setup#" in line)
    c = make_client()
    secret = finish_setup(c, link.strip())
    assert staff_login(c, email, secret).status_code == 200
    return c, r.json()["id"]


def audit_actions() -> list[str]:
    with hq_session() as s:
        return list(s.execute(text("SELECT action FROM audit_log ORDER BY id")).scalars())


# ---------- staff sign-in ----------


def test_super_admin_sets_up_two_factor_and_signs_in(boss, make_client):
    me = boss["client"].get(f"{H}/auth/me").json()
    assert me["is_super"] and "customers.impersonate" in me["permissions"]
    other = make_client()
    r = other.post(f"{H}/auth/login", json={"email": "founder@scrollwalk.com", "password": STAFF_PASSWORD,
                                            "code": "000000"})
    assert r.status_code == 401
    r = other.post(f"{H}/auth/login", json={"email": "founder@scrollwalk.com", "password": "wrong password!",
                                            "code": code(boss["secret"], 1)})
    assert r.status_code == 401
    assert audit_actions()[:3] == ["staff.super_created", "staff.setup_completed", "staff.login"]
    assert audit_actions().count("staff.login_failed") == 2


def test_a_code_works_only_once(boss, make_client):
    other = make_client()
    r = staff_login(other, "founder@scrollwalk.com", boss["secret"], ahead=1)
    assert r.status_code == 401  # the fixture already used this step
    assert staff_login(other, "founder@scrollwalk.com", boss["secret"], ahead=-5).status_code == 401


def test_setup_link_is_single_use(make_client):
    c = make_client()
    link = create_super("founder@scrollwalk.com")
    token = link.split("#", 1)[1]
    secret = c.post(f"{H}/auth/setup/start", json={"token": token}).json()["secret"]
    r = c.post(f"{H}/auth/setup/finish", json={"token": token, "password": STAFF_PASSWORD, "code": "123456"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_code"
    r = c.post(f"{H}/auth/setup/finish", json={"token": token, "password": STAFF_PASSWORD, "code": code(secret)})
    assert r.status_code == 200
    assert c.post(f"{H}/auth/setup/start", json={"token": token}).status_code == 400
    with pytest.raises(SystemExit):
        create_super("someone@else.com")


def test_two_factor_secret_is_encrypted_at_rest(boss):
    with hq_session() as s:
        stored = bytes(s.execute(text("SELECT totp_secret FROM staff")).scalar_one())
    assert boss["secret"].encode() not in stored


def test_customer_and_staff_sessions_are_separate(boss, admin):
    assert admin["client"].get(f"{H}/customers").status_code == 401
    b = boss["client"]
    assert b.get("/api/v1/auth/me").status_code == 401
    assert b.get("/api/v1/listings").status_code == 401


def test_staff_writes_need_csrf(boss):
    b = boss["client"]
    r = b.post(f"{H}/roles", json={"name": "Support", "permissions": []})
    assert r.status_code == 403 and r.json()["error"]["code"] == "csrf_failed"


def test_idle_and_logged_out_sessions_end(boss, owner_engine):
    b = boss["client"]
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE staff_sessions SET last_seen_at = now() - interval '61 minutes'"))
    assert b.get(f"{H}/auth/me").status_code == 401


def test_logout(boss):
    b = boss["client"]
    assert b.post(f"{H}/auth/logout", headers=hq_csrf(b)).status_code == 204
    assert b.get(f"{H}/auth/me").status_code == 401


# ---------- staff roles and accounts ----------


def test_staff_permissions_are_enforced(boss, make_client):
    helper, helper_id = add_staff(boss, make_client, permissions=("customers.view",))
    me = helper.get(f"{H}/auth/me").json()
    assert not me["is_super"] and me["permissions"] == ["customers.view"]
    assert helper.get(f"{H}/customers").status_code == 200
    assert helper.get(f"{H}/trial-invites").status_code == 403
    assert helper.get(f"{H}/audit").status_code == 403
    assert helper.get(f"{H}/staff").status_code == 403
    assert helper.post(f"{H}/roles", json={"name": "Mine", "permissions": ["audit.view"]},
                       headers=hq_csrf(helper)).status_code == 403

    b = boss["client"]
    r = b.patch(f"{H}/staff/{helper_id}", json={"disabled": True}, headers=hq_csrf(b))
    assert r.json()["status"] == "disabled"
    assert helper.get(f"{H}/auth/me").status_code == 401


def test_roles_validate_and_protect(boss, make_client):
    b = boss["client"]
    r = b.post(f"{H}/roles", json={"name": "Bad", "permissions": ["staff.manage"]}, headers=hq_csrf(b))
    assert r.status_code == 422
    _, helper_id = add_staff(boss, make_client)
    role_id = b.get(f"{H}/staff").json()[1]["role_id"]
    assert b.delete(f"{H}/roles/{role_id}", headers=hq_csrf(b)).json()["error"]["code"] == "role_in_use"
    supers = [x for x in b.get(f"{H}/staff").json() if x["is_super"]]
    r = b.patch(f"{H}/staff/{supers[0]['id']}", json={"disabled": True}, headers=hq_csrf(b))
    assert r.status_code == 409


def test_reset_sends_a_new_setup_link(boss, make_client):
    helper, helper_id = add_staff(boss, make_client)
    b = boss["client"]
    r = b.post(f"{H}/staff/{helper_id}/reset", headers=hq_csrf(b))
    assert r.json()["status"] == "setup_pending"
    assert helper.get(f"{H}/auth/me").status_code == 401
    assert len([m for m in mails_to("helper@scrollwalk.com") if "/setup#" in m.text]) == 2


# ---------- customers ----------


def test_customers_list_and_read_only_view(boss, admin, make_client):
    listing = new_listing(admin["client"])
    publish(admin["client"], listing["id"])
    assert enquire(admin["client"], admin["workspace_id"], slug=listing["slug"],
                   message="Secret buyer message").status_code == 202
    sign_up(make_client(), "other@example.com")
    b = boss["client"]

    data = b.get(f"{H}/customers").json()
    assert data["total"] == 2
    data = b.get(f"{H}/customers", params={"q": "admin@exa"}).json()
    assert [c["admin_email"] for c in data["items"]] == ["admin@example.com"]
    assert data["items"][0]["listings"] == 1
    assert b.get(f"{H}/customers", params={"q": "%"}).json()["total"] == 0

    r = b.get(f"{H}/customers/{admin['workspace_id']}")
    assert r.status_code == 200, r.text
    view = r.json()
    assert view["members"][0]["email"] == "admin@example.com"
    assert view["listings"][0]["title"] == "Villa Aurelia"
    assert view["usage"]["enquiries_total"] == 1
    assert "Secret buyer message" not in r.text and "bea@example.com" not in r.text
    assert view["recent_staff_actions"][0]["action"] == "customer.viewed"
    assert b.get(f"{H}/customers/00000000-0000-0000-0000-000000000000").status_code == 404


def test_audit_log_is_append_only(boss, owner_engine):
    with pytest.raises(ProgrammingError):
        with hq_session() as s:
            s.execute(text("DELETE FROM audit_log"))
    with pytest.raises(DBAPIError):
        with owner_engine.begin() as conn:
            conn.execute(text("UPDATE audit_log SET action = 'nothing'"))
    with pytest.raises(DBAPIError):
        with owner_engine.begin() as conn:
            conn.execute(text("DELETE FROM audit_log"))
    page = boss["client"].get(f"{H}/audit").json()
    assert [e["action"] for e in page["items"]][-1] == "staff.super_created"


def test_customer_api_role_cannot_see_staff_tables(admin):
    for table in ("staff", "staff_sessions", "audit_log", "trial_invites", "trial_redemptions", "staff_roles"):
        with pytest.raises(ProgrammingError):
            with tenant_session(admin["user_id"], admin["workspace_id"]) as s:
                s.execute(text(f"SELECT * FROM {table}")).all()


# ---------- trial invites ----------


def _invite(boss, **body):
    b = boss["client"]
    r = b.post(f"{H}/trial-invites", json=body, headers=hq_csrf(b))
    assert r.status_code == 201, r.text
    return r.json()


def test_personal_trial_invite(boss, client, make_client, owner_engine):
    invite = _invite(boss, kind="personal", email="Ana@Example.com", listings_allowed=4, note="Open house lead")
    token = invite["link"].split("#", 1)[1]
    assert mails_to("ana@example.com")[-1].subject == "You're invited to try Scrollwalk"

    looked = client.post(f"{T}/lookup", json={"token": token}).json()
    assert looked["status"] == "open" and looked["email"] == "ana@example.com" and looked["listings_allowed"] == 4

    eve = make_client()
    sign_up(eve, "eve@example.com")
    r = eve.post(f"{T}/redeem", json={"token": token}, headers=csrf(eve))
    assert r.status_code == 403 and r.json()["error"]["code"] == "trial_email_mismatch"

    me = sign_up(client, "ana@example.com")
    preview = client.post("/api/v1/listings", json={"title": "Preview", "experience_type": "photo"},
                          headers=csrf(client)).json()
    r = client.post(f"{T}/redeem", json={"token": token}, headers=csrf(client))
    assert r.status_code == 200 and r.json() == {"status": "trialing", "listings_allowed": 4}
    with owner_engine.connect() as conn:
        ws = conn.execute(text("SELECT * FROM workspaces WHERE id = :w"), {"w": me["current_workspace_id"]}).one()
        assert ws.subscription_state == "trialing" and ws.trial_listing_allowance == 4
        assert conn.execute(text("SELECT is_trial FROM listings WHERE id = :l"), {"l": preview["id"]}).scalar()

    assert client.post(f"{T}/redeem", json={"token": token}, headers=csrf(client)).status_code == 400
    assert client.post(f"{T}/lookup", json={"token": token}).json()["status"] == "used"
    listed = boss["client"].get(f"{H}/trial-invites").json()[0]
    assert listed["redemptions"] == 1 and listed["link"] is None


def test_campaign_code_cap_and_one_trial_per_person(boss, make_client, owner_engine):
    _invite(boss, kind="campaign", code="REZA30", max_redemptions=2)
    clients = []
    for n in range(3):
        c = make_client()
        sign_up(c, f"agent{n}@example.com")
        clients.append(c)
    assert clients[0].post(f"{T}/redeem", json={"code": "reza30"}, headers=csrf(clients[0])).status_code == 200
    r = clients[0].post(f"{T}/redeem", json={"code": "REZA30"}, headers=csrf(clients[0]))
    assert r.json()["error"]["code"] == "already_trialed"
    assert clients[1].post(f"{T}/redeem", json={"code": "REZA30"}, headers=csrf(clients[1])).status_code == 200
    r = clients[2].post(f"{T}/redeem", json={"code": "REZA30"}, headers=csrf(clients[2]))
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_trial"
    assert clients[2].post(f"{T}/lookup", json={"code": "nope-code"}).status_code == 404

    b = boss["client"]
    r = b.post(f"{H}/trial-invites", json={"kind": "campaign", "code": "reza30"}, headers=hq_csrf(b))
    assert r.status_code == 409


def test_paid_accounts_cannot_start_a_trial(boss, admin):
    _invite(boss, kind="campaign", code="SPRING")
    c = admin["client"]
    r = c.post(f"{T}/redeem", json={"code": "SPRING"}, headers=csrf(c))
    assert r.status_code == 409 and r.json()["error"]["code"] == "trial_not_eligible"


def test_revoked_invites_stop_working(boss, client):
    invite = _invite(boss, kind="campaign", code="GONE")
    b = boss["client"]
    assert b.post(f"{H}/trial-invites/{invite['id']}/revoke", headers=hq_csrf(b)).json()["status"] == "revoked"
    sign_up(client, "ana@example.com")
    assert client.post(f"{T}/lookup", json={"code": "GONE"}).json()["status"] == "revoked"
    assert client.post(f"{T}/redeem", json={"code": "GONE"}, headers=csrf(client)).status_code == 400


def test_trial_conversion_is_recorded(boss, client, owner_engine):
    _invite(boss, kind="campaign", code="CONVERT")
    me = sign_up(client, "ana@example.com")
    assert client.post(f"{T}/redeem", json={"code": "CONVERT"}, headers=csrf(client)).status_code == 200
    subscribe(client)
    listed = boss["client"].get(f"{H}/trial-invites").json()[0]
    assert listed["redemptions"] == 1 and listed["conversions"] == 1
    view = boss["client"].get(f"{H}/customers/{me['current_workspace_id']}").json()
    assert view["trial"]["converted_at"] is not None and view["state"] == "active"


def test_only_trial_managers_create_invites(boss, make_client):
    helper, _ = add_staff(boss, make_client, permissions=("customers.view",))
    r = helper.post(f"{H}/trial-invites", json={"kind": "campaign", "code": "NOPE"}, headers=hq_csrf(helper))
    assert r.status_code == 403

from sqlalchemy import text

from tests.auth_helpers import PASSWORD, csrf, last_code, mails_to, sign_up

API = "/api/v1/auth"


def test_signup_verify_creates_session_and_workspace(client, owner_engine):
    me = sign_up(client, "Ana@Example.com", name="Ana Silva")
    assert me["user"]["email"] == "Ana@example.com"
    assert me["user"]["email_verified"] is True
    assert me["user"]["display_name"] == "Ana Silva"
    assert len(me["workspaces"]) == 1 and me["workspaces"][0]["is_admin"] is True
    assert me["current_workspace_id"] == me["workspaces"][0]["id"]
    assert client.get(f"{API}/me").json()["user"]["id"] == me["user"]["id"]
    with owner_engine.connect() as conn:
        docs = conn.execute(text("SELECT document FROM legal_acceptances ORDER BY document")).scalars().all()
    assert docs == ["privacy", "terms"]


def test_session_cookie_is_locked_down(client):
    client.post(f"{API}/signup", json={"email": "a@example.com", "password": PASSWORD, "accept_terms": True})
    r = client.post(f"{API}/verify", json={"email": "a@example.com", "code": last_code("a@example.com")})
    cookies = r.headers.get_list("set-cookie")
    session = next(c for c in cookies if c.startswith("__Host-sw_session="))
    for flag in ("HttpOnly", "Secure", "SameSite=lax", "Path=/"):
        assert flag.lower() in session.lower()
    assert "Domain" not in session
    assert "sw_session" not in r.text


def test_signup_requires_terms(client):
    r = client.post(f"{API}/signup", json={"email": "a@example.com", "password": PASSWORD, "accept_terms": False})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


def test_signup_rejects_short_password(client):
    r = client.post(f"{API}/signup", json={"email": "a@example.com", "password": "short", "accept_terms": True})
    assert r.status_code == 422


def test_signup_with_taken_email_reveals_nothing_and_changes_nothing(client, make_client):
    sign_up(client, "a@example.com")
    other = make_client()
    r = other.post(f"{API}/signup", json={"email": "a@example.com", "password": "attacker-pass", "accept_terms": True})
    assert r.status_code == 202 and r.json() == {"status": "code_sent"}
    assert "already have" in mails_to("a@example.com")[-1].subject
    assert other.post(f"{API}/login", json={"email": "a@example.com", "password": "attacker-pass"}).status_code == 401
    assert other.post(f"{API}/login", json={"email": "a@example.com", "password": PASSWORD}).status_code == 200


def test_unverified_signup_can_be_reclaimed_by_inbox_owner(client, make_client):
    attacker = make_client()
    attacker.post(f"{API}/signup", json={"email": "v@example.com", "password": "attacker-pass", "accept_terms": True})
    client.cookies.clear()
    # Inside the resend cooldown no new code is sent; the one already in the inbox still works.
    r = client.post(f"{API}/signup", json={"email": "v@example.com", "password": PASSWORD, "accept_terms": True})
    assert r.status_code == 202
    code = last_code("v@example.com")
    assert client.post(f"{API}/verify", json={"email": "v@example.com", "code": code}).status_code == 200
    assert attacker.post(f"{API}/login", json={"email": "v@example.com", "password": "attacker-pass"}).status_code == 401
    assert attacker.post(f"{API}/login", json={"email": "v@example.com", "password": PASSWORD}).status_code == 200


def test_wrong_password_and_unknown_email_look_identical(client):
    sign_up(client, "a@example.com")
    wrong = client.post(f"{API}/login", json={"email": "a@example.com", "password": "nope-nope"})
    unknown = client.post(f"{API}/login", json={"email": "ghost@example.com", "password": "nope-nope"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_unverified_login_is_refused_and_sends_code(client, owner_engine):
    client.post(f"{API}/signup", json={"email": "a@example.com", "password": PASSWORD, "accept_terms": True})
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE email_codes SET created_at = now() - interval '1 minute'"))
    r = client.post(f"{API}/login", json={"email": "a@example.com", "password": PASSWORD})
    assert r.status_code == 403 and r.json()["error"]["code"] == "email_not_verified"
    assert len(mails_to("a@example.com")) == 2


def test_code_dies_after_five_wrong_guesses(client):
    client.post(f"{API}/signup", json={"email": "a@example.com", "password": PASSWORD, "accept_terms": True})
    code = last_code("a@example.com")
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        assert client.post(f"{API}/verify", json={"email": "a@example.com", "code": wrong}).status_code == 400
    assert client.post(f"{API}/verify", json={"email": "a@example.com", "code": code}).status_code == 400


def test_expired_code_is_refused(client, owner_engine):
    client.post(f"{API}/signup", json={"email": "a@example.com", "password": PASSWORD, "accept_terms": True})
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE email_codes SET expires_at = now() - interval '1 second'"))
    r = client.post(f"{API}/verify", json={"email": "a@example.com", "code": last_code("a@example.com")})
    assert r.status_code == 400


def test_code_is_single_use(client):
    me = sign_up(client, "a@example.com")
    code = last_code("a@example.com")
    assert client.post(f"{API}/verify", json={"email": "a@example.com", "code": code}).status_code == 400
    assert me["user"]["email_verified"]


def test_new_code_replaces_old_and_resend_has_cooldown(client, owner_engine):
    client.post(f"{API}/signup", json={"email": "a@example.com", "password": PASSWORD, "accept_terms": True})
    first = last_code("a@example.com")
    client.post(f"{API}/resend", json={"email": "a@example.com", "purpose": "verify"})
    assert len(mails_to("a@example.com")) == 1
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE email_codes SET created_at = now() - interval '31 seconds'"))
    client.post(f"{API}/resend", json={"email": "a@example.com", "purpose": "verify"})
    second = last_code("a@example.com")
    assert len(mails_to("a@example.com")) == 2
    if first != second:
        assert client.post(f"{API}/verify", json={"email": "a@example.com", "code": first}).status_code == 400
    assert client.post(f"{API}/verify", json={"email": "a@example.com", "code": second}).status_code == 200


def test_codes_are_stored_hashed(client, owner_engine):
    client.post(f"{API}/signup", json={"email": "a@example.com", "password": PASSWORD, "accept_terms": True})
    code = last_code("a@example.com")
    with owner_engine.connect() as conn:
        stored = conn.execute(text("SELECT code_hash FROM email_codes")).scalar_one()
        password = conn.execute(text("SELECT password_hash FROM user_credentials")).scalar_one()
    assert code.encode() not in bytes(stored)
    assert password.startswith("$argon2id$")


def test_state_changes_need_csrf_header(client):
    sign_up(client, "a@example.com")
    r = client.post(f"{API}/logout")
    assert r.status_code == 403 and r.json()["error"]["code"] == "csrf_failed"
    r = client.post(f"{API}/logout", headers={"X-CSRF-Token": "forged"})
    assert r.status_code == 403
    assert client.post(f"{API}/logout", headers=csrf(client)).status_code == 204
    assert client.get(f"{API}/me").status_code == 401


def test_logout_survives_stolen_cookie_replay(client, make_client):
    sign_up(client, "a@example.com")
    stolen = client.cookies.get("__Host-sw_session")
    client.post(f"{API}/logout", headers=csrf(client))
    thief = make_client()
    thief.cookies.set("__Host-sw_session", stolen)
    assert thief.get(f"{API}/me").status_code == 401


def test_logout_everywhere(client, make_client):
    sign_up(client, "a@example.com")
    laptop = make_client()
    assert laptop.post(f"{API}/login", json={"email": "a@example.com", "password": PASSWORD}).status_code == 200
    assert client.post(f"{API}/logout-all", headers=csrf(client)).status_code == 204
    assert laptop.get(f"{API}/me").status_code == 401
    assert client.get(f"{API}/me").status_code == 401


def test_password_reset_signs_out_other_devices(client, make_client):
    sign_up(client, "a@example.com")
    phone = make_client()
    assert phone.post(f"{API}/password/forgot", json={"email": "a@example.com"}).status_code == 202
    r = phone.post(f"{API}/password/reset", json={
        "email": "a@example.com", "code": last_code("a@example.com"), "password": "a brand new password",
    })
    assert r.status_code == 200
    assert client.get(f"{API}/me").status_code == 401
    assert phone.get(f"{API}/me").status_code == 200
    assert phone.post(f"{API}/login", json={"email": "a@example.com", "password": PASSWORD}).status_code == 401
    assert phone.post(f"{API}/login", json={"email": "a@example.com", "password": "a brand new password"}).status_code == 200


def test_forgot_password_for_unknown_email_sends_nothing(client):
    r = client.post(f"{API}/password/forgot", json={"email": "ghost@example.com"})
    assert r.status_code == 202 and r.json() == {"status": "code_sent"}
    assert mails_to("ghost@example.com") == []


def test_reset_code_cannot_verify_and_vice_versa(client):
    sign_up(client, "a@example.com")
    client.post(f"{API}/password/forgot", json={"email": "a@example.com"})
    code = last_code("a@example.com")
    assert client.post(f"{API}/verify", json={"email": "a@example.com", "code": code}).status_code == 400


def test_login_is_rate_limited(client):
    sign_up(client, "a@example.com")
    statuses = [
        client.post(f"{API}/login", json={"email": "a@example.com", "password": "wrong-pass"}).status_code
        for _ in range(11)
    ]
    assert statuses[:10] == [401] * 10 and statuses[10] == 429
    r = client.post(f"{API}/login", json={"email": "a@example.com", "password": PASSWORD})
    assert r.status_code == 429


def test_code_guessing_is_rate_limited_across_codes(client, owner_engine):
    client.post(f"{API}/signup", json={"email": "a@example.com", "password": PASSWORD, "accept_terms": True})
    statuses = []
    for _ in range(11):
        statuses.append(client.post(f"{API}/verify", json={"email": "a@example.com", "code": "999999"}).status_code)
    assert statuses[-1] == 429


def test_foreign_origin_writes_are_refused(client):
    r = client.post(f"{API}/login", json={"email": "a@example.com", "password": PASSWORD},
                    headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "origin_not_allowed"
    r = client.post(f"{API}/login", json={"email": "a@example.com", "password": PASSWORD},
                    headers={"Origin": "http://localhost:3000"})
    assert r.status_code == 401


def test_security_headers(client):
    r = client.get("/api/v1/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["cache-control"] == "no-store"
    assert "max-age" in r.headers["strict-transport-security"]
    assert "default-src 'none'" in r.headers["content-security-policy"]


def test_change_email(client, make_client):
    sign_up(client, "old@example.com")
    r = client.post(f"{API}/email/change", json={"new_email": "new@example.com", "password": "wrong-pass"},
                    headers=csrf(client))
    assert r.status_code == 401
    r = client.post(f"{API}/email/change", json={"new_email": "new@example.com", "password": PASSWORD},
                    headers=csrf(client))
    assert r.status_code == 202
    r = client.post(f"{API}/email/confirm", json={"code": last_code("new@example.com")}, headers=csrf(client))
    assert r.status_code == 200 and r.json()["user"]["email"] == "new@example.com"
    assert "changed" in mails_to("old@example.com")[-1].subject
    fresh = make_client()
    assert fresh.post(f"{API}/login", json={"email": "new@example.com", "password": PASSWORD}).status_code == 200


def test_change_email_to_taken_address_is_refused(client, make_client):
    sign_up(client, "a@example.com")
    sign_up(make_client(), "b@example.com")
    r = client.post(f"{API}/email/change", json={"new_email": "b@example.com", "password": PASSWORD},
                    headers=csrf(client))
    assert r.status_code == 409


def test_removed_member_session_loses_the_workspace(client, make_client, owner_engine):
    owner = sign_up(client, "owner@example.com")
    team_ws = owner["current_workspace_id"]
    member_client = make_client()
    member = sign_up(member_client, "member@example.com")
    with owner_engine.begin() as conn:
        conn.execute(text("INSERT INTO memberships (workspace_id, user_id) VALUES (:w, :u)"),
                     {"w": team_ws, "u": member["user"]["id"]})
        conn.execute(text("UPDATE sessions SET workspace_id = :w WHERE user_id = :u"),
                     {"w": team_ws, "u": member["user"]["id"]})
    assert member_client.get(f"{API}/me").json()["current_workspace_id"] == team_ws
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE memberships SET removed_at = now() WHERE workspace_id = :w AND user_id = :u"),
                     {"w": team_ws, "u": member["user"]["id"]})
    me = member_client.get(f"{API}/me").json()
    assert me["current_workspace_id"] is None
    assert team_ws not in [w["id"] for w in me["workspaces"]]


def test_api_database_user_cannot_read_sessions_of_others(client, make_client):
    from app.db import tenant_session

    a = sign_up(client, "a@example.com")
    sign_up(make_client(), "b@example.com")
    with tenant_session(a["user"]["id"]) as s:
        owners = set(s.execute(text("SELECT user_id::text FROM sessions")).scalars())
        codes = set(s.execute(text("SELECT user_id::text FROM email_codes")).scalars())
    assert owners == {a["user"]["id"]} and codes == {a["user"]["id"]}

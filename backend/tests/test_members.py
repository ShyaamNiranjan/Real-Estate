import re
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.db import tenant_session
from tests.auth_helpers import PASSWORD, csrf, mails_to, set_workspace, sign_up

T = "/api/v1/team"
I = "/api/v1/invitations"


@pytest.fixture
def admin(client, owner_engine):
    me = sign_up(client, "admin@example.com", name="Ana Admin")
    set_workspace(owner_engine, me["current_workspace_id"], plan_key="team", display_name="Silva Realty")
    return {"client": client, "workspace_id": me["current_workspace_id"], "user_id": me["user"]["id"]}


def role(c, name="Agent", permissions=("listings.create", "listings.edit_own")):
    r = c.post(f"{T}/roles", json={"name": name, "permissions": list(permissions)}, headers=csrf(c))
    assert r.status_code == 201, r.text
    return r.json()


def invite(c, address, role_id):
    return c.post(f"{T}/invitations", json={"email": address, "role_id": role_id}, headers=csrf(c))


def token_for(address):
    message = mails_to(address)[-1]
    return re.search(r"/join#(\S+)", message.text).group(1)


def join(make_client, c, address, permissions=("listings.create", "listings.edit_own"), role_name=None):
    """Invites `address` into a role and signs them up through the link. Returns (client, me)."""
    r = role(c, role_name or address, permissions)
    assert invite(c, address, r["id"]).status_code == 201
    member = make_client()
    res = member.post(f"{I}/signup", json={"token": token_for(address), "password": PASSWORD, "accept_terms": True})
    assert res.status_code == 200, res.text
    return member, res.json()


def members(c):
    return {m["name"]: m for m in c.get(f"{T}/members").json()}


def test_invited_person_joins_without_an_email_code(admin, make_client):
    c = admin["client"]
    agent_role = role(c)
    r = invite(c, "Bea@Example.com", agent_role["id"])
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "open" and r.json()["role"]["name"] == "Agent"
    message = mails_to("bea@example.com")[-1]
    assert message.subject == "Ana Admin invited you to join Silva Realty on Scrollwalk"
    assert "https://testserver/join#" in message.text

    token = token_for("bea@example.com")
    guest = make_client()
    preview = guest.post(f"{I}/lookup", json={"token": token}).json()
    assert preview["status"] == "open" and preview["has_account"] is False
    assert preview["team_name"] == "Silva Realty" and preview["role_name"] == "Agent"

    r = guest.post(f"{I}/signup", json={"token": token, "password": PASSWORD, "display_name": "Bea", "accept_terms": True})
    assert r.status_code == 200, r.text
    me = r.json()
    assert me["user"]["email_verified"] is True
    assert me["current_workspace_id"] == admin["workspace_id"] and len(me["workspaces"]) == 1
    assert mails_to("admin@example.com")[-1].subject == "Bea joined Silva Realty on Scrollwalk"

    bea = members(c)["Bea"]
    assert bea["role"]["name"] == "Agent" and bea["email"] == "bea@example.com" and not bea["is_admin"]
    assert c.get(f"{T}/invitations").json()["items"] == []
    again = make_client().post(f"{I}/signup", json={"token": token, "password": PASSWORD, "accept_terms": True})
    assert again.status_code == 410
    assert guest.post(f"{I}/lookup", json={"token": token}).json()["status"] == "accepted"


def test_existing_user_accepts_and_can_switch_workspaces(admin, make_client):
    c = admin["client"]
    bea = make_client()
    own = sign_up(bea, "bea@example.com")["current_workspace_id"]
    assert invite(c, "bea@example.com", role(c)["id"]).status_code == 201
    token = token_for("bea@example.com")
    assert bea.post(f"{I}/lookup", json={"token": token}).json()["has_account"] is True
    r = bea.post(f"{I}/signup", json={"token": token, "password": PASSWORD, "accept_terms": True})
    assert r.status_code == 409 and r.json()["error"]["code"] == "account_exists"

    me = bea.post(f"{I}/accept", json={"token": token}, headers=csrf(bea)).json()
    assert me["current_workspace_id"] == admin["workspace_id"] and len(me["workspaces"]) == 2

    again = make_client()
    r = again.post("/api/v1/auth/login", json={"email": "bea@example.com", "password": PASSWORD})
    assert r.json()["current_workspace_id"] == admin["workspace_id"], "sign-in returns to the last workspace used"

    r = bea.post("/api/v1/auth/workspace", json={"workspace_id": own}, headers=csrf(bea))
    assert r.status_code == 200 and r.json()["current_workspace_id"] == own
    r = bea.post("/api/v1/auth/workspace", json={"workspace_id": str(uuid4())}, headers=csrf(bea))
    assert r.status_code == 403


def test_invitation_only_works_for_the_invited_email(admin, make_client):
    c = admin["client"]
    assert invite(c, "bea@example.com", role(c)["id"]).status_code == 201
    eve = make_client()
    sign_up(eve, "eve@example.com")
    r = eve.post(f"{I}/accept", json={"token": token_for("bea@example.com")}, headers=csrf(eve))
    assert r.status_code == 403 and r.json()["error"]["code"] == "invitation_email_mismatch"
    assert eve.post(f"{I}/lookup", json={"token": "x" * 43}).status_code == 410


def test_revoked_and_resent_invitations(admin, make_client):
    c = admin["client"]
    inv = invite(c, "bea@example.com", role(c)["id"]).json()
    first = token_for("bea@example.com")
    r = c.post(f"{T}/invitations/{inv['id']}/resend", headers=csrf(c))
    assert r.status_code == 200
    second = token_for("bea@example.com")
    assert first != second
    guest = make_client()
    assert guest.post(f"{I}/lookup", json={"token": first}).status_code == 410

    assert c.delete(f"{T}/invitations/{inv['id']}", headers=csrf(c)).status_code == 204
    assert guest.post(f"{I}/lookup", json={"token": second}).json()["status"] == "revoked"
    r = guest.post(f"{I}/signup", json={"token": second, "password": PASSWORD, "accept_terms": True})
    assert r.status_code == 410


def test_reinviting_replaces_the_open_invitation(admin):
    c = admin["client"]
    agent = role(c)
    invite(c, "bea@example.com", agent["id"])
    invite(c, "bea@example.com", agent["id"])
    data = c.get(f"{T}/invitations").json()
    assert len(data["items"]) == 1 and data["seats"] == {"used": 2, "total": 10}


def test_seats_are_counted_with_open_invitations(admin, owner_engine):
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE plans SET seats = 2 WHERE key = 'team'"))
    c = admin["client"]
    agent = role(c)
    assert invite(c, "bea@example.com", agent["id"]).status_code == 201
    r = invite(c, "cal@example.com", agent["id"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "seats_full"


def test_cannot_invite_existing_members(admin, make_client):
    c = admin["client"]
    join(make_client, c, "bea@example.com")
    r = invite(c, "bea@example.com", role(c, "Other")["id"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "already_member"
    r = invite(c, "admin@example.com", role(c, "Third")["id"])
    assert r.status_code == 409


def test_invitations_need_a_team_plan_and_permission(admin, make_client, owner_engine):
    c = admin["client"]
    agent, _ = join(make_client, c, "bea@example.com")
    spare = role(c, "Spare")
    assert agent.get(f"{T}/invitations").status_code == 403
    assert invite(agent, "cal@example.com", spare["id"]).status_code == 403

    set_workspace(owner_engine, admin["workspace_id"], plan_key="agent")
    r = invite(c, "cal@example.com", spare["id"])
    assert r.status_code == 403 and r.json()["error"]["code"] == "plan_required"


def test_managers_cannot_invite_into_roles_stronger_than_their_own(admin, make_client):
    c = admin["client"]
    manager, _ = join(make_client, c, "mo@example.com", ["team.manage_members", "listings.create"])
    strong = role(c, "Strong", ["enquiries.view_all"])
    r = invite(manager, "cal@example.com", strong["id"])
    assert r.status_code == 403 and r.json()["error"]["code"] == "cannot_grant"
    weak = role(c, "Weak", ["listings.create"])
    assert invite(manager, "cal@example.com", weak["id"]).status_code == 201


def test_invitations_are_invisible_across_workspaces_and_to_non_managers(admin, make_client):
    c = admin["client"]
    inv = invite(c, "bea@example.com", role(c)["id"]).json()
    agent, agent_me = join(make_client, c, "dee@example.com")

    other = make_client()
    other_me = sign_up(other, "other@example.com")
    assert other.delete(f"{T}/invitations/{inv['id']}", headers=csrf(other)).status_code == 404

    with tenant_session(other_me["user"]["id"], other_me["current_workspace_id"]) as s:
        assert s.execute(text("SELECT count(*) FROM invitations")).scalar() == 0
    with tenant_session(agent_me["user"]["id"], admin["workspace_id"]) as s:
        assert s.execute(text("SELECT count(*) FROM invitations")).scalar() == 0, "agent can't manage members"
    with tenant_session(admin["user_id"], admin["workspace_id"]) as s:
        assert s.execute(text("SELECT count(*) FROM invitations")).scalar() == 2


def test_role_with_pending_invitations_cannot_be_deleted(admin):
    c = admin["client"]
    agent = role(c)
    inv = invite(c, "bea@example.com", agent["id"]).json()
    r = c.delete(f"{T}/roles/{agent['id']}", headers=csrf(c))
    assert r.status_code == 409 and r.json()["error"]["code"] == "role_in_use"
    c.delete(f"{T}/invitations/{inv['id']}", headers=csrf(c))
    assert c.delete(f"{T}/roles/{agent['id']}", headers=csrf(c)).status_code == 204


# ---------- members ----------


def _listing(c, title="Agent's home"):
    r = c.post("/api/v1/listings", json={"title": title, "experience_type": "photo"}, headers=csrf(c))
    assert r.status_code == 201, r.text
    return r.json()


def _enquiry(owner_engine, workspace_id, listing_id, member_id):
    with owner_engine.begin() as conn:
        conn.execute(text("""INSERT INTO enquiries (id, workspace_id, listing_id, agent_member_id, name, email,
                                                    consent_text, consent_version)
                             VALUES (:id, :w, :l, :m, 'Buyer', 'buyer@example.com', 'ok', 'v1')"""),
                     {"id": uuid4(), "w": workspace_id, "l": listing_id, "m": member_id})


def _owners(owner_engine, workspace_id):
    with owner_engine.begin() as conn:
        return (conn.execute(text("SELECT agent_member_id::text FROM listings WHERE workspace_id = :w"),
                             {"w": workspace_id}).scalars().all(),
                conn.execute(text("SELECT agent_member_id::text FROM enquiries WHERE workspace_id = :w"),
                             {"w": workspace_id}).scalars().all())


def test_removing_a_member_hands_their_work_to_the_admin(admin, make_client, owner_engine):
    c = admin["client"]
    agent, _ = join(make_client, c, "bea@example.com", ["listings.create", "listings.edit_own", "listings.listing_agent"])
    listing = _listing(agent)
    team = members(c)
    bea_id, admin_id = team["bea@example.com"]["id"], team["Ana Admin"]["id"]
    _enquiry(owner_engine, admin["workspace_id"], listing["id"], bea_id)

    r = c.post(f"{T}/members/{bea_id}/remove", json={}, headers=csrf(c))
    assert r.status_code == 204, r.text
    assert _owners(owner_engine, admin["workspace_id"]) == ([admin_id], [admin_id])
    assert "bea@example.com" not in members(c)

    r = agent.get("/api/v1/workspace")
    assert r.status_code == 409 and r.json()["error"]["code"] == "no_workspace"
    me = agent.post("/api/v1/auth/workspace", json={}, headers=csrf(agent)).json()
    assert me["current_workspace_id"] not in (None, admin["workspace_id"])
    assert c.post(f"{T}/members/{bea_id}/remove", json={}, headers=csrf(c)).status_code == 404


def test_manager_without_enquiry_access_still_hands_over_enquiries(admin, make_client, owner_engine):
    c = admin["client"]
    agent, _ = join(make_client, c, "bea@example.com")
    manager, _ = join(make_client, c, "mo@example.com", ["team.manage_members", "listings.create", "listings.edit_own"])
    listing = _listing(agent)
    team = members(c)
    bea_id, mo_id = team["bea@example.com"]["id"], team["mo@example.com"]["id"]
    _enquiry(owner_engine, admin["workspace_id"], listing["id"], bea_id)

    r = manager.post(f"{T}/members/{bea_id}/remove", json={"successor_id": mo_id}, headers=csrf(manager))
    assert r.status_code == 204, r.text
    assert _owners(owner_engine, admin["workspace_id"]) == ([mo_id], [mo_id])


def test_successor_must_be_on_the_team(admin, make_client):
    c = admin["client"]
    join(make_client, c, "bea@example.com")
    bea_id = members(c)["bea@example.com"]["id"]
    for successor in (bea_id, str(uuid4())):
        r = c.post(f"{T}/members/{bea_id}/remove", json={"successor_id": successor}, headers=csrf(c))
        assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_successor"


def test_admin_is_protected_and_managers_cannot_touch_stronger_members(admin, make_client):
    c = admin["client"]
    manager, _ = join(make_client, c, "mo@example.com", ["team.manage_members", "listings.create"])
    join(make_client, c, "eli@example.com", ["enquiries.view_all"])
    team = members(c)
    admin_id, eli_id, mo_id = team["Ana Admin"]["id"], team["eli@example.com"]["id"], team["mo@example.com"]["id"]

    r = manager.post(f"{T}/members/{admin_id}/remove", json={}, headers=csrf(manager))
    assert r.status_code == 403 and r.json()["error"]["code"] == "admin_protected"
    r = manager.post(f"{T}/members/{eli_id}/remove", json={}, headers=csrf(manager))
    assert r.status_code == 403 and r.json()["error"]["code"] == "cannot_manage"
    r = manager.patch(f"{T}/members/{mo_id}", json={"role_id": team["eli@example.com"]["role"]["id"]}, headers=csrf(manager))
    assert r.status_code == 403 and r.json()["error"]["code"] == "cannot_change_own_role"
    r = c.patch(f"{T}/members/{admin_id}", json={"role_id": team["eli@example.com"]["role"]["id"]}, headers=csrf(c))
    assert r.status_code == 403
    r = c.post(f"{T}/members/{admin_id}/remove", json={}, headers=csrf(c))
    assert r.status_code == 409 and r.json()["error"]["code"] == "use_leave"


def test_role_change_applies_immediately(admin, make_client):
    c = admin["client"]
    agent, _ = join(make_client, c, "bea@example.com", ["listings.create"])
    assert agent.get(f"{T}/invitations").status_code == 403
    managers = role(c, "Managers", ["team.manage_members"])
    bea_id = members(c)["bea@example.com"]["id"]
    r = c.patch(f"{T}/members/{bea_id}", json={"role_id": managers["id"]}, headers=csrf(c))
    assert r.status_code == 200 and r.json()["role"]["name"] == "Managers"
    assert agent.get(f"{T}/invitations").status_code == 200


def test_members_see_names_but_only_managers_see_contact_details(admin, make_client):
    c = admin["client"]
    agent, _ = join(make_client, c, "bea@example.com")
    seen = members(agent)
    assert seen["Ana Admin"]["email"] is None and seen["Ana Admin"]["licence_number"] is None
    assert seen["bea@example.com"]["email"] == "bea@example.com" and seen["bea@example.com"]["is_you"]

    bea_id = seen["bea@example.com"]["id"]
    r = agent.patch(f"{T}/members/{bea_id}", json={"licence_number": " 01234567 "}, headers=csrf(agent))
    assert r.status_code == 200 and r.json()["licence_number"] == "01234567"
    r = agent.patch(f"{T}/members/{seen['Ana Admin']['id']}", json={"licence_number": "x"}, headers=csrf(agent))
    assert r.status_code == 403


def test_member_can_leave(admin, make_client, owner_engine):
    c = admin["client"]
    agent, _ = join(make_client, c, "bea@example.com")
    listing = _listing(agent)
    admin_id = members(c)["Ana Admin"]["id"]
    me = agent.post(f"{T}/leave", json={}, headers=csrf(agent)).json()
    assert me["current_workspace_id"] != admin["workspace_id"]
    assert all(w["id"] != admin["workspace_id"] for w in me["workspaces"])
    assert _owners(owner_engine, admin["workspace_id"])[0] == [admin_id]
    assert listing["status"] == "draft"
    r = c.post(f"{T}/leave", json={}, headers=csrf(c))
    assert r.status_code == 403 and r.json()["error"]["code"] == "admin_protected"

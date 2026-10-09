import pytest

from app.permissions import ALL_PERMISSIONS
from tests.auth_helpers import add_member, csrf, set_workspace, sign_up

T = "/api/v1/team"


@pytest.fixture
def admin(client, owner_engine):
    me = sign_up(client, "admin@example.com")
    set_workspace(owner_engine, me["current_workspace_id"], plan_key="team")
    return {"client": client, "workspace_id": me["current_workspace_id"]}


def create(c, name, permissions, description=""):
    return c.post(f"{T}/roles", json={"name": name, "description": description, "permissions": permissions},
                  headers=csrf(c))


def test_catalogue_never_offers_admin_only_powers(admin):
    data = admin["client"].get(f"{T}/permissions").json()
    keys = {p["key"] for p in data["permissions"]}
    assert keys == ALL_PERMISSIONS and len(keys) == 20
    assert not any(word in k for k in keys for word in ("billing", "plan", "delete_workspace", "transfer"))
    assert [s["name"] for s in data["suggestions"]] == ["Agent", "Marketing", "Coordinator"]
    assert all(set(s["permissions"]) <= keys for s in data["suggestions"])


def test_no_roles_exist_until_the_admin_creates_one(admin):
    assert admin["client"].get(f"{T}/roles").json() == []


def test_roles_need_a_team_plan(client, owner_engine):
    sign_up(client, "solo@example.com")
    r = create(client, "Agent", ["listings.create"])
    assert r.status_code == 403 and r.json()["error"]["code"] == "plan_required"


def test_create_update_delete_role(admin):
    c = admin["client"]
    r = create(c, "Agent", ["listings.create", "listings.edit_own"], "Lists homes")
    assert r.status_code == 201
    role = r.json()
    assert role["permissions"] == ["listings.create", "listings.edit_own"] and role["member_count"] == 0

    r = c.put(f"{T}/roles/{role['id']}", json={"name": "Senior agent", "permissions": ["listings.edit_all"]},
              headers=csrf(c))
    assert r.status_code == 200 and r.json()["permissions"] == ["listings.edit_all"]
    assert c.delete(f"{T}/roles/{role['id']}", headers=csrf(c)).status_code == 204
    assert c.get(f"{T}/roles").json() == []


def test_role_names_are_unique_ignoring_case(admin):
    c = admin["client"]
    assert create(c, "Agent", []).status_code == 201
    r = create(c, "agent", [])
    assert r.status_code == 409 and r.json()["error"]["code"] == "role_name_taken"


def test_unknown_permissions_are_refused(admin):
    r = create(admin["client"], "Hacker", ["billing.manage"])
    assert r.status_code == 422 and r.json()["error"]["code"] == "unknown_permission"


def test_nobody_grants_more_than_they_have(admin, make_client, owner_engine):
    c = admin["client"]
    manager_role = create(c, "Team lead", ["team.manage_roles", "listings.create", "listings.edit_own"]).json()
    lead_client = make_client()
    lead = sign_up(lead_client, "lead@example.com")
    add_member(owner_engine, admin["workspace_id"], lead["user"]["id"], manager_role["id"])

    assert create(lead_client, "Junior", ["listings.create"]).status_code == 201
    r = create(lead_client, "Power", ["listings.publish_all"])
    assert r.status_code == 403 and r.json()["error"]["code"] == "cannot_grant"

    # Nor by editing their own role upwards.
    r = lead_client.put(f"{T}/roles/{manager_role['id']}",
                        json={"name": "Team lead", "permissions": ["team.manage_roles", "listings.delete_all"]},
                        headers=csrf(lead_client))
    assert r.status_code == 403
    # Keeping permissions they don't hold on a role someone else set up is fine.
    admin_role = create(c, "Publisher", ["listings.publish_all"]).json()
    r = lead_client.put(f"{T}/roles/{admin_role['id']}",
                        json={"name": "Publisher", "description": "renamed", "permissions": ["listings.publish_all"]},
                        headers=csrf(lead_client))
    assert r.status_code == 200


def test_members_without_role_permissions_are_refused(admin, make_client, owner_engine):
    member_client = make_client()
    member = sign_up(member_client, "member@example.com")
    add_member(owner_engine, admin["workspace_id"], member["user"]["id"])
    assert member_client.get(f"{T}/roles").status_code == 403
    assert create(member_client, "Mine", []).status_code == 403


def test_role_with_members_cannot_be_deleted(admin, make_client, owner_engine):
    c = admin["client"]
    role = create(c, "Agent", ["listings.create"]).json()
    member = sign_up(make_client(), "member@example.com")
    add_member(owner_engine, admin["workspace_id"], member["user"]["id"], role["id"])
    assert c.get(f"{T}/roles").json()[0]["member_count"] == 1
    r = c.delete(f"{T}/roles/{role['id']}", headers=csrf(c))
    assert r.status_code == 409 and r.json()["error"]["code"] == "role_in_use"


def test_other_workspaces_roles_are_invisible(admin, make_client, owner_engine):
    role = create(admin["client"], "Agent", ["listings.create"]).json()
    rival_client = make_client()
    rival = sign_up(rival_client, "rival@example.com")
    set_workspace(owner_engine, rival["current_workspace_id"], plan_key="team")

    assert rival_client.get(f"{T}/roles").json() == []
    r = rival_client.put(f"{T}/roles/{role['id']}", json={"name": "Owned", "permissions": []}, headers=csrf(rival_client))
    assert r.status_code == 404
    assert rival_client.delete(f"{T}/roles/{role['id']}", headers=csrf(rival_client)).status_code == 404
    assert admin["client"].get(f"{T}/roles").json()[0]["name"] == "Agent"


def test_role_from_another_workspace_cannot_be_assigned(admin, make_client, owner_engine):
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    role = create(admin["client"], "Agent", []).json()
    rival = sign_up(make_client(), "rival@example.com")
    with pytest.raises(IntegrityError):
        with owner_engine.begin() as conn:
            conn.execute(text("UPDATE memberships SET role_id = :r WHERE workspace_id = :w"),
                         {"r": role["id"], "w": rival["current_workspace_id"]})

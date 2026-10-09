import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from tests.auth_helpers import add_member, csrf, set_workspace, sign_up

W = "/api/v1/workspace"


@pytest.fixture
def admin(client):
    me = sign_up(client, "admin@example.com")
    return {"client": client, "workspace_id": me["current_workspace_id"], "user_id": me["user"]["id"]}


def patch(c, body):
    return c.patch(f"{W}/profile", json=body, headers=csrf(c))


def blocker_codes(ws):
    return {b["code"] for b in ws["publish_blockers"]}


def test_new_workspace_lists_what_blocks_publishing(admin):
    ws = admin["client"].get(W).json()
    assert ws["is_admin"] is True and len(ws["my_permissions"]) == 20
    assert ws["username"] is None and ws["can_claim_username"] is False
    assert blocker_codes(ws) == {"username", "display_name", "contact", "country"}


def test_country_picks_profile_currency_and_units(admin):
    c = admin["client"]
    ws = patch(c, {"country_code": "us"}).json()
    assert (ws["country_code"], ws["compliance_profile"], ws["currency_default"], ws["area_unit"]) == ("US", "US", "USD", "sqft")
    assert {"compliance.licence_number", "compliance.licence_state", "compliance.brokerage_name"} <= blocker_codes(ws)

    ws = patch(c, {"brokerage_name": "Compass", "compliance": {"licence_number": "01234567", "licence_state": "CA"}}).json()
    assert not any(code.startswith("compliance.") for code in blocker_codes(ws))

    ws = patch(c, {"country_code": "DE"}).json()
    assert (ws["compliance_profile"], ws["currency_default"], ws["area_unit"]) == ("EU", "EUR", "sqm")
    assert ws["profile"]["compliance"] == {}

    ws = patch(c, {"country_code": "BR"}).json()
    assert ws["compliance_profile"] == "OTHER"


def test_explicit_currency_wins_over_country_default(admin):
    ws = patch(admin["client"], {"country_code": "AE", "currency_default": "usd", "area_unit": "sqm"}).json()
    assert ws["currency_default"] == "USD" and ws["area_unit"] == "sqm"


def test_unknown_compliance_field_is_refused(admin):
    c = admin["client"]
    patch(c, {"country_code": "IN"})
    r = patch(c, {"compliance": {"licence_number": "x"}})
    assert r.status_code == 422 and r.json()["error"]["code"] == "unknown_compliance_field"
    assert patch(c, {"compliance": {"rera_agent_number": "A51800001234"}}).status_code == 200


def test_contact_methods_are_validated_and_normalised(admin):
    c = admin["client"]
    ws = patch(c, {"contact_phone": "+1 (415) 555-0100", "whatsapp": "+971 50 123 4567",
                   "booking_url": "https://cal.com/ana", "contact_email": "ana@example.com"}).json()
    assert ws["profile"]["contact_phone"] == "+14155550100"
    assert ws["profile"]["whatsapp"] == "+971501234567"
    assert "contact" not in blocker_codes(ws)
    assert patch(c, {"contact_phone": "415 555 0100"}).status_code == 422
    assert patch(c, {"booking_url": "http://cal.com/ana"}).status_code == 422
    assert patch(c, {"timezone": "Mars/Olympus"}).status_code == 422
    ws = patch(c, {"contact_phone": "", "whatsapp": "", "booking_url": "", "contact_email": ""}).json()
    assert "contact" in blocker_codes(ws)


def test_username_check_rules(admin):
    c = admin["client"]
    check = lambda name: c.get(f"{W}/username/check", params={"username": name}).json()
    assert check("Ana-Silva") == {"username": "ana-silva", "available": True, "reason": None, "suggestions": []}
    assert check("ab")["reason"] == "too_short"
    assert check("a" * 31)["reason"] == "too_long"
    assert check("ana--silva")["reason"] == "invalid_characters"
    assert check("-ana")["reason"] == "invalid_characters"
    assert check("ana.silva")["reason"] == "invalid_characters"
    reserved = check("zillow")
    assert reserved["reason"] == "reserved" and len(reserved["suggestions"]) == 3


def test_taken_username_gets_three_available_suggestions(admin, owner_engine):
    set_workspace(owner_engine, admin["workspace_id"], username="shyaam")
    result = admin["client"].get(f"{W}/username/check", params={"username": "Shyaam"}).json()
    assert result["reason"] == "taken" and len(result["suggestions"]) == 3
    assert "shyaam" not in result["suggestions"]
    assert any(s[-1].isdigit() for s in result["suggestions"])


def test_claiming_a_username_needs_a_plan_and_is_permanent(admin, owner_engine):
    c = admin["client"]
    body = {"username": "ana-silva", "confirm_permanent": True}
    r = c.post(f"{W}/username", json=body, headers=csrf(c))
    assert r.status_code == 403 and r.json()["error"]["code"] == "plan_required"

    set_workspace(owner_engine, admin["workspace_id"], subscription_state="trialing")
    assert c.get(W).json()["can_claim_username"] is True
    r = c.post(f"{W}/username", json=body, headers=csrf(c))
    assert r.status_code == 200 and r.json()["username"] == "ana-silva"
    assert "username" not in blocker_codes(r.json())

    r = c.post(f"{W}/username", json={"username": "another", "confirm_permanent": True}, headers=csrf(c))
    assert r.status_code == 409 and r.json()["error"]["code"] == "username_permanent"


def test_database_refuses_username_changes_even_if_the_api_tried(admin, owner_engine):
    from app.db import tenant_session

    set_workspace(owner_engine, admin["workspace_id"], username="ana-silva")
    with pytest.raises(IntegrityError, match="permanent"):
        with tenant_session(admin["user_id"], admin["workspace_id"]) as s:
            s.execute(text("UPDATE workspaces SET username = 'stolen' WHERE id = :w"), {"w": admin["workspace_id"]})


def test_claim_requires_confirmation_and_valid_name(admin, owner_engine):
    c = admin["client"]
    set_workspace(owner_engine, admin["workspace_id"], subscription_state="active")
    assert c.post(f"{W}/username", json={"username": "ana", "confirm_permanent": False}, headers=csrf(c)).status_code == 422
    r = c.post(f"{W}/username", json={"username": "studio", "confirm_permanent": True}, headers=csrf(c))
    assert r.status_code == 422 and r.json()["error"]["code"] == "username_reserved"


def test_taken_and_held_usernames_cannot_be_claimed(admin, make_client, owner_engine):
    other = sign_up(make_client(), "other@example.com")
    set_workspace(owner_engine, other["current_workspace_id"], username="taken-name")
    with owner_engine.begin() as conn:
        conn.execute(text("INSERT INTO username_holds (username, available_at) VALUES ('held-name', now() + interval '60 days')"))
        conn.execute(text("INSERT INTO username_holds (username, available_at) VALUES ('free-again', now() - interval '1 day')"))
    set_workspace(owner_engine, admin["workspace_id"], subscription_state="active")
    c = admin["client"]
    for name in ("Taken-Name", "held-name"):
        r = c.post(f"{W}/username", json={"username": name, "confirm_permanent": True}, headers=csrf(c))
        assert r.status_code == 409, name
    r = c.post(f"{W}/username", json={"username": "free-again", "confirm_permanent": True}, headers=csrf(c))
    assert r.status_code == 200


def test_only_the_admin_claims_usernames_and_records_setup(admin, make_client, owner_engine):
    member_client = make_client()
    member = sign_up(member_client, "member@example.com")
    add_member(owner_engine, admin["workspace_id"], member["user"]["id"])
    set_workspace(owner_engine, admin["workspace_id"], subscription_state="active")
    r = member_client.post(f"{W}/username", json={"username": "member-grab", "confirm_permanent": True},
                           headers=csrf(member_client))
    assert r.status_code == 403 and r.json()["error"]["code"] == "admin_only"
    r = member_client.post(f"{W}/setup", json={"step": "style", "status": "done"}, headers=csrf(member_client))
    assert r.status_code == 403


def test_member_edits_follow_their_role(admin, make_client, owner_engine):
    c = admin["client"]
    set_workspace(owner_engine, admin["workspace_id"], plan_key="team")
    role = c.post("/api/v1/team/roles", json={"name": "Front desk", "permissions": ["site.edit_contact"]},
                  headers=csrf(c)).json()
    member_client = make_client()
    member = sign_up(member_client, "member@example.com")
    add_member(owner_engine, admin["workspace_id"], member["user"]["id"], role["id"])

    ws = member_client.get(W).json()
    assert ws["is_admin"] is False and ws["my_permissions"] == ["site.edit_contact"]
    assert patch(member_client, {"contact_email": "desk@example.com"}).status_code == 200
    r = patch(member_client, {"display_name": "Renamed"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "permission_denied"
    assert patch(member_client, {"contact_email": "x@example.com", "style_preset": "coastal"}).status_code == 403


def test_setup_guide_progress(admin):
    c = admin["client"]
    c.post(f"{W}/setup", json={"step": "about_you", "status": "skipped"}, headers=csrf(c))
    ws = c.post(f"{W}/setup", json={"step": "style", "status": "done"}, headers=csrf(c)).json()
    assert ws["setup"] == {"about_you": "skipped", "style": "done"}
    ws = c.post(f"{W}/setup", json={"step": "about_you", "status": "done"}, headers=csrf(c)).json()
    assert ws["setup"]["about_you"] == "done"


def test_compliance_catalogue(admin):
    data = admin["client"].get(f"{W}/compliance-profiles").json()
    keys = [p["key"] for p in data["profiles"]]
    assert keys == ["US", "GB", "AE", "IN", "CA", "AU", "EU", "OTHER"]
    eu = next(p for p in data["profiles"] if p["key"] == "EU")
    assert any(f["key"] == "energy_rating" and f["required"] and f["scope"] == "listing" for f in eu["fields"])
    assert "DE" in data["eu_countries"] and "GB" not in data["eu_countries"]


def test_public_role_sees_contact_details_only_for_claimed_workspaces(admin, owner_engine):
    from app.db import public_session

    patch(admin["client"], {"contact_email": "ana@example.com"})
    with public_session() as s:
        assert s.execute(text("SELECT contact_email FROM workspace_profiles")).all() == []
    set_workspace(owner_engine, admin["workspace_id"], username="ana")
    with public_session() as s:
        assert s.execute(text("SELECT contact_email FROM workspace_profiles")).scalars().all() == ["ana@example.com"]
        with pytest.raises(Exception, match="permission denied"):
            s.execute(text("SELECT setup FROM workspace_profiles")).all()

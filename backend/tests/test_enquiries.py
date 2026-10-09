import time

import pytest
from sqlalchemy import text

from app import email
from app.config import get_settings
from app.db import tenant_session
from app.security import keyed
from tests.auth_helpers import csrf, mails_to, set_workspace
from tests.test_listings import _member, admin, edit, make_ready, new_listing, publish  # noqa: F401

P = "/api/v1/public"
E = "/api/v1/enquiries"


def aged_token(workspace_id: str, seconds: int = 10) -> str:
    issued = str(int(time.time()) - seconds)
    return f"{issued}.{keyed('enquiry-form', f'{workspace_id}:{issued}')[:32]}"


_visitors: dict[str, object] = {}


def visitor(ip: str):
    """A browser at a given IP (the API rate-limits by the connecting address)."""
    from fastapi.testclient import TestClient

    from app.main import app

    if ip not in _visitors:
        _visitors[ip] = TestClient(app, base_url="https://testserver", client=(ip, 50000))
    return _visitors[ip]


def enquire(c, workspace_id, slug="villa-aurelia", ip=None, **overrides):
    body = {"username": "ana", "listing_slug": slug, "name": "Bea Buyer", "email": "bea@example.com",
            "phone": "+1 555 0100", "message": "Can I see it Saturday?", "consent": True,
            "form_token": aged_token(workspace_id), **overrides}
    ip = ip or f"203.0.113.{len(_visitors) + 1}"
    return visitor(ip).post(f"{P}/enquiries", json=body)


def stored(owner_engine) -> list:
    with owner_engine.connect() as conn:
        return conn.execute(text("SELECT * FROM enquiries ORDER BY created_at")).all()


@pytest.fixture
def live(admin):
    listing = new_listing(admin["client"])
    publish(admin["client"], listing["id"])
    return listing


def test_enquiry_is_stored_and_emailed_to_the_agent(admin, live, owner_engine):
    c = admin["client"]
    email.outbox.clear()
    r = enquire(c, admin["workspace_id"])
    assert r.status_code == 202 and r.json() == {"status": "sent"}
    [row] = stored(owner_engine)
    assert row.listing_id is not None and row.name == "Bea Buyer" and row.status == "new"
    assert row.consent_text == "By sending this, you agree to be contacted by admin@example.com about this property."
    assert row.page_path == "/ana/villa-aurelia" and row.consent_version
    [alert] = mails_to("admin@example.com")
    assert alert.subject == "New enquiry: Villa Aurelia" and alert.reply_to == "bea@example.com"
    assert "Can I see it Saturday?" in alert.text


def test_site_contact_form(admin, owner_engine):
    c = admin["client"]
    r = enquire(c, admin["workspace_id"], slug=None)
    assert r.status_code == 404
    c.post("/api/v1/workspace/site/publish", json={"acknowledge_compliance": True}, headers=csrf(c))
    assert c.get(f"{P}/sites/ana").json()["form_token"]
    assert enquire(c, admin["workspace_id"], slug=None).status_code == 202
    [row] = stored(owner_engine)
    assert row.listing_id is None and row.page_path == "/ana/contact"


def test_bots_are_dropped_silently(admin, live, owner_engine):
    c = admin["client"]
    fresh = c.get(f"{P}/sites/ana/listings/villa-aurelia").json()["page"]["form_token"]
    for overrides in ({"website": "http://spam.example"}, {"form_token": fresh}, {"form_token": "123.forged"},
                      {"form_token": aged_token(admin["workspace_id"], seconds=2 * 86400)}):
        assert enquire(c, admin["workspace_id"], ip="198.51.100.9", **overrides).status_code == 202
    assert stored(owner_engine) == []
    assert enquire(c, admin["workspace_id"], slug="not-a-listing").status_code == 404
    r = enquire(c, admin["workspace_id"], consent=False)
    assert r.status_code == 422 and r.json()["error"]["fields"]["consent"] == "Please tick this box."


def test_draft_listings_take_no_enquiries(admin, owner_engine):
    new_listing(admin["client"], "Draft Home")
    assert enquire(admin["client"], admin["workspace_id"], slug="draft-home").status_code == 404


def test_enquiries_are_rate_limited_per_ip(admin, live):
    c = admin["client"]
    codes = [enquire(c, admin["workspace_id"], ip="192.0.2.50").status_code for _ in range(6)]
    assert codes == [202] * 5 + [429]
    assert enquire(c, admin["workspace_id"], ip="192.0.2.51").status_code == 202


def test_turnstile_is_required_when_configured(admin, live, monkeypatch, owner_engine):
    monkeypatch.setattr(get_settings(), "turnstile_secret", "test-secret")
    r = enquire(admin["client"], admin["workspace_id"])
    assert r.status_code == 422 and r.json()["error"]["code"] == "verification_failed"
    assert stored(owner_engine) == []


# ---------- Studio ----------


def test_inbox_status_and_search(admin, live):
    c = admin["client"]
    enquire(c, admin["workspace_id"], name="First Person", email="first@example.com")
    enquire(c, admin["workspace_id"], name="Second Person", email="second@example.com", message="Price?")
    page = c.get(E).json()
    assert [i["name"] for i in page["items"]] == ["Second Person", "First Person"]
    assert page["counts"] == {"new": 2, "contacted": 0, "closed": 0} and page["next_before"] is None
    assert page["items"][0]["listing_title"] == "Villa Aurelia"
    first = page["items"][1]["id"]
    r = c.patch(f"{E}/{first}", json={"status": "contacted"}, headers=csrf(c))
    assert r.status_code == 200 and r.json()["status"] == "contacted"
    assert [i["name"] for i in c.get(E, params={"status": "new"}).json()["items"]] == ["Second Person"]
    assert [i["name"] for i in c.get(E, params={"q": "price"}).json()["items"]] == ["Second Person"]
    assert [i["name"] for i in c.get(E, params={"q": "%"}).json()["items"]] == []
    assert c.get(f"{E}/{first}").json()["email"] == "first@example.com"


def test_export_is_spreadsheet_safe(admin, live):
    c = admin["client"]
    enquire(c, admin["workspace_id"], name="=HYPERLINK(\"http://evil\")", message="+1 call me")
    r = c.get(f"{E}/export")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    assert "'=HYPERLINK" in r.text and "'+1 call me" in r.text


def test_agents_see_only_their_own_listings_enquiries(admin, make_client, owner_engine):
    c = admin["client"]
    agent_client, agent_member = _member(make_client, owner_engine, admin,
                                         ["enquiries.view_own", "listings.listing_agent"], licence="LIC-1")
    mine, other = new_listing(c, "Agent Home"), new_listing(c, "Office Home")
    edit(c, mine["id"], agent_member_id=agent_member)
    publish(c, mine["id"]), publish(c, other["id"])
    email.outbox.clear()
    enquire(c, admin["workspace_id"], slug="agent-home", email="one@example.com")
    enquire(c, admin["workspace_id"], slug="office-home", email="two@example.com")

    assert [m.subject for m in mails_to("agent@example.com")] == ["New enquiry: Agent Home"]
    assert len(mails_to("admin@example.com")) == 2
    items = agent_client.get(E).json()["items"]
    assert [i["email"] for i in items] == ["one@example.com"]
    other_id = next(i["id"] for i in c.get(E).json()["items"] if i["email"] == "two@example.com")
    assert agent_client.get(f"{E}/{other_id}").status_code == 404
    assert agent_client.patch(f"{E}/{other_id}", json={"status": "closed"}, headers=csrf(agent_client)).status_code == 404
    assert agent_client.get(f"{E}/export").status_code == 403

    nobody_client, _ = _member(make_client, owner_engine, admin, ["listings.create"], email="desk@example.com")
    assert nobody_client.get(E).status_code == 403


def test_database_hides_enquiries_without_permission(admin, live, make_client, owner_engine):
    c = admin["client"]
    enquire(c, admin["workspace_id"])
    _, _ = _member(make_client, owner_engine, admin, ["listings.create"], email="desk@example.com")
    with owner_engine.connect() as conn:
        desk = conn.execute(text("SELECT id FROM users WHERE email = 'desk@example.com'")).scalar_one()
    with tenant_session(desk, admin["workspace_id"]) as s:
        assert s.execute(text("SELECT count(*) FROM enquiries")).scalar_one() == 0
        assert s.execute(text("UPDATE enquiries SET status = 'closed' RETURNING id")).first() is None
    with tenant_session(None, admin["workspace_id"]) as s:
        assert s.execute(text("SELECT count(*) FROM enquiries")).scalar_one() == 0


def test_offline_studio_is_read_only_for_enquiries(admin, live, owner_engine):
    c = admin["client"]
    enquire(c, admin["workspace_id"])
    enquiry_id = c.get(E).json()["items"][0]["id"]
    set_workspace(owner_engine, admin["workspace_id"], subscription_state="offline")
    assert c.get(E).status_code == 200
    assert c.patch(f"{E}/{enquiry_id}", json={"status": "closed"}, headers=csrf(c)).status_code == 403


def test_trial_workspaces_cannot_publish_a_site(admin, owner_engine):
    set_workspace(owner_engine, admin["workspace_id"], subscription_state="trialing")
    c = admin["client"]
    r = c.post("/api/v1/workspace/site/publish", json={"acknowledge_compliance": True}, headers=csrf(c))
    assert r.status_code == 409 and "trial" in r.json()["error"]["message"]

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from app.db import public_session, tenant_session
from tests.auth_helpers import add_member, csrf, set_workspace, sign_up

L = "/api/v1/listings"


def make_ready(client, owner_engine, workspace_id, username="ana", state="active", plan="agent"):
    set_workspace(owner_engine, workspace_id, username=username, subscription_state=state, plan_key=plan)
    r = client.patch("/api/v1/workspace/profile", headers=csrf(client), json={
        "display_name": "Ana Silva", "contact_email": "ana@example.com", "country_code": "US",
        "brokerage_name": "Silva Realty", "compliance": {"licence_number": "0123", "licence_state": "CA"},
    })
    assert r.status_code == 200 and r.json()["publish_blockers"] == [], r.text


@pytest.fixture
def admin(client, owner_engine):
    me = sign_up(client, "admin@example.com")
    make_ready(client, owner_engine, me["current_workspace_id"])
    return {"client": client, "workspace_id": me["current_workspace_id"], "user_id": me["user"]["id"]}


def new_listing(c, title="Villa Aurelia", **kw):
    kw.setdefault("experience_type", "photo")
    r = c.post(L, json={"title": title, **kw}, headers=csrf(c))
    assert r.status_code == 201, r.text
    return r.json()


def publish(c, listing_id, ack=True):
    return c.post(f"{L}/{listing_id}/publish", json={"acknowledge_compliance": ack}, headers=csrf(c))


def edit(c, listing_id, **fields):
    return c.patch(f"{L}/{listing_id}", json=fields, headers=csrf(c))


def public_rows():
    with public_session() as s:
        return s.execute(text("SELECT id, status, live_slug, live FROM listings")).all()


def test_new_listing_starts_with_designed_sections(admin):
    listing = new_listing(admin["client"])
    assert listing["slug"] == "villa-aurelia" and listing["status"] == "draft"
    assert [s["type"] for s in listing["sections"]] == [
        "story", "at_a_glance", "spaces", "gallery", "floor_plans", "location", "faq", "cta"]
    assert listing["hero"] == {"enabled": True, "image_media_id": None, "show_facts": True, "show_price": True}
    assert listing["agent"]["name"] == "admin@example.com"
    assert listing["price_currency"] == "USD" and listing["area_unit"] == "sqft"
    assert listing["permissions"] == {"can_edit": True, "can_publish": True, "can_submit": False,
                                      "can_approve": True, "can_delete": True}
    assert listing["preview_path"] == f"/preview/{listing['id']}"
    assert listing["public_path"] == "/ana/villa-aurelia"


def test_slugs_are_unique_and_avoid_section_words(admin):
    c = admin["client"]
    assert new_listing(c, "Villa Aurelia")["slug"] == "villa-aurelia"
    assert new_listing(c, "Villa Aurelia")["slug"] == "villa-aurelia-2"
    assert new_listing(c, "About")["slug"] == "about-home"
    assert new_listing(c, "Château Élysée")["slug"] == "chateau-elysee"


def test_at_a_glance_follows_the_details(admin):
    c = admin["client"]
    listing = new_listing(c, experience_type="immersive")
    listing = edit(c, listing["id"], bedrooms=4, bathrooms=3.5, area=2400, price_amount=2450000).json()
    glance = next(s for s in listing["sections"] if s["type"] == "at_a_glance")
    assert glance["content"]["items"] == [
        {"label": "Bedrooms", "value": "4"}, {"label": "Bathrooms", "value": "3.5"},
        {"label": "Area", "value": "2,400 sq ft"}, {"label": "Experience", "value": "Walkthrough"}]
    assert listing["price_amount"] == 2450000.0


def test_publishing_needs_one_time_compliance_acknowledgement(admin):
    c = admin["client"]
    listing = new_listing(c)
    r = publish(c, listing["id"], ack=False)
    assert r.status_code == 409 and r.json()["error"]["code"] == "compliance_ack_required"
    r = publish(c, listing["id"])
    assert r.status_code == 200 and r.json()["live_state"] == "live"
    second = new_listing(c, "Second home")
    assert publish(c, second["id"], ack=False).status_code == 200


def test_public_sees_only_the_published_snapshot(admin):
    c = admin["client"]
    listing = new_listing(c)
    edit(c, listing["id"], summary="Private notes for the AI", subtitle="Sea views")
    assert public_rows() == []
    publish(c, listing["id"])
    rows = public_rows()
    assert len(rows) == 1 and rows[0].live["title"] == "Villa Aurelia" and rows[0].live_slug == "villa-aurelia"
    assert "summary" not in rows[0].live

    after = edit(c, listing["id"], title="Villa Aurelia Renamed").json()
    assert after["has_unpublished_changes"] is True and after["live_state"] == "live"
    assert public_rows()[0].live["title"] == "Villa Aurelia"
    assert publish(c, listing["id"]).json()["has_unpublished_changes"] is False
    assert public_rows()[0].live["title"] == "Villa Aurelia Renamed"


def test_public_cannot_read_private_columns(admin):
    publish(admin["client"], new_listing(admin["client"])["id"])
    with pytest.raises(ProgrammingError, match="permission denied"):
        with public_session() as s:
            s.execute(text("SELECT summary FROM listings")).all()
    with pytest.raises(ProgrammingError, match="permission denied"):
        with public_session() as s:
            s.execute(text("SELECT content FROM listing_sections")).all()


def test_renamed_slug_redirects_from_the_old_address(admin):
    c = admin["client"]
    listing = new_listing(c)
    publish(c, listing["id"])
    edit(c, listing["id"], slug="villa-aurelia-marbella")
    assert public_rows()[0].live_slug == "villa-aurelia"
    publish(c, listing["id"])
    assert public_rows()[0].live_slug == "villa-aurelia-marbella"
    with public_session() as s:
        history = s.execute(text("SELECT slug, listing_id::text FROM listing_slug_history")).all()
    assert [tuple(h) for h in history] == [("villa-aurelia", listing["id"])]
    other = new_listing(c, "Villa Aurelia")
    assert other["slug"] == "villa-aurelia-2"


def test_slug_rules(admin):
    c = admin["client"]
    a, b = new_listing(c, "First"), new_listing(c, "Second")
    assert edit(c, a["id"], slug="Bad Slug").status_code == 422
    assert edit(c, a["id"], slug="contact").status_code == 422
    r = edit(c, a["id"], slug=b["slug"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "slug_taken"


def test_sections_add_edit_reorder_hide(admin):
    c = admin["client"]
    listing = new_listing(c)
    story = listing["sections"][0]
    r = c.post(f"{L}/{listing['id']}/sections", json={"type": "quote", "after_id": story["id"]}, headers=csrf(c))
    assert r.status_code == 201 and r.json()["sections"][1]["type"] == "quote"
    sections = r.json()["sections"]
    quote = sections[1]

    path = f"{L}/{listing['id']}/sections/{quote['id']}"
    assert c.patch(path, json={"layout_variant": "nope"}, headers=csrf(c)).status_code == 422
    assert c.patch(path, json={"content": {"text": "x", "script": "<b>"}}, headers=csrf(c)).status_code == 422
    r = c.patch(path, json={"content": {"text": "Best view on the coast.", "attribution": "Seller"},
                            "layout_variant": "minimal"}, headers=csrf(c))
    assert r.json()["sections"][1]["content"]["text"] == "Best view on the coast."

    ids = [s["id"] for s in sections]
    assert c.put(f"{L}/{listing['id']}/sections/order", json={"ids": ids[:-1]}, headers=csrf(c)).status_code == 422
    r = c.put(f"{L}/{listing['id']}/sections/order", json={"ids": ids[::-1]}, headers=csrf(c))
    assert [s["id"] for s in r.json()["sections"]] == ids[::-1]

    c.patch(path, json={"is_visible": False}, headers=csrf(c))
    publish(c, listing["id"])
    assert "quote" not in [s["type"] for s in public_rows()[0].live["sections"]]
    r = c.delete(path, headers=csrf(c))
    assert quote["id"] not in [s["id"] for s in r.json()["sections"]]


def test_hero_and_captions(admin):
    c = admin["client"]
    listing = new_listing(c)
    r = c.put(f"{L}/{listing['id']}/hero", json={"enabled": True, "show_facts": False, "show_price": False},
              headers=csrf(c))
    assert r.json()["hero"]["show_price"] is False
    beats = [{"at": 0.1, "label": "Entry", "text": "Double-height foyer"}, {"at": 0.62, "label": "Pool"}]
    r = c.put(f"{L}/{listing['id']}/beats", json=beats, headers=csrf(c))
    assert [b["label"] for b in r.json()["beats"]] == ["Entry", "Pool"]
    assert c.put(f"{L}/{listing['id']}/beats", json=[{"at": 1.5}], headers=csrf(c)).status_code == 422
    assert c.put(f"{L}/{listing['id']}/beats", json=[{"at": 0.1}] * 21, headers=csrf(c)).status_code == 422


def test_listing_compliance_fields_block_publishing(client, owner_engine):
    me = sign_up(client, "eu@example.com")
    set_workspace(owner_engine, me["current_workspace_id"], username="eu-agent", subscription_state="active",
                  plan_key="agent")
    client.patch("/api/v1/workspace/profile", headers=csrf(client), json={
        "display_name": "EU Agent", "contact_email": "eu@example.com", "country_code": "FR"})
    listing = new_listing(client)
    assert "compliance.energy_rating" in [b["code"] for b in listing["publish_blockers"]]
    r = publish(client, listing["id"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "publish_blocked"
    assert edit(client, listing["id"], compliance={"tenure": "freehold"}).status_code == 422
    edit(client, listing["id"], compliance={"energy_rating": "B"})
    assert publish(client, listing["id"]).status_code == 200


def test_trial_gets_three_listings_ever_and_sixty_days_live(client, owner_engine):
    me = sign_up(client, "trial@example.com")
    make_ready(client, owner_engine, me["current_workspace_id"], username="trial-agent", state="trialing", plan=None)
    first = new_listing(client, "One")
    new_listing(client, "Two")
    third = new_listing(client, "Three")
    assert client.delete(f"{L}/{third['id']}", headers=csrf(client)).status_code == 204
    r = client.post(L, json={"title": "Four"}, headers=csrf(client))
    assert r.status_code == 403 and r.json()["error"]["code"] == "trial_limit"

    live = publish(client, first["id"]).json()
    assert live["is_trial"] is True
    expires = datetime.fromisoformat(live["trial_expires_at"])
    assert timedelta(days=59) < expires - datetime.now(UTC) <= timedelta(days=60)

    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE listings SET trial_expires_at = now() - interval '1 day' WHERE id = :id"),
                     {"id": first["id"]})
    assert client.get(f"{L}/{first['id']}").json()["live_state"] == "expired"
    set_workspace(owner_engine, me["current_workspace_id"], subscription_state="active", plan_key="agent")
    assert client.get(f"{L}/{first['id']}").json()["live_state"] == "live"


def test_free_preview_is_one_private_listing(client):
    sign_up(client, "free@example.com")
    listing = new_listing(client, "My first home")
    assert listing["public_path"] is None
    assert listing["publish_blockers"][0]["code"] == "plan"
    assert publish(client, listing["id"]).status_code == 409
    r = client.post(L, json={"title": "Second"}, headers=csrf(client))
    assert r.status_code == 403 and r.json()["error"]["code"] == "plan_required"


def test_plan_listing_limit(admin, monkeypatch):
    from app import listings as listings_module

    monkeypatch.setitem(listings_module.LISTING_LIMITS, "agent", 1)
    c = admin["client"]
    first = new_listing(c)
    r = c.post(L, json={"title": "Over"}, headers=csrf(c))
    assert r.status_code == 403 and r.json()["error"]["code"] == "listing_limit"
    publish(c, first["id"])
    c.post(f"{L}/{first['id']}/sold", headers=csrf(c))
    assert c.post(L, json={"title": "After sale"}, headers=csrf(c)).status_code == 201


def test_lapsed_accounts(admin, owner_engine):
    c = admin["client"]
    listing = new_listing(c)
    set_workspace(owner_engine, admin["workspace_id"], subscription_state="grace")
    r = c.post(L, json={"title": "New"}, headers=csrf(c))
    assert r.status_code == 403 and r.json()["error"]["code"] == "lapsed_no_new_listings"
    assert edit(c, listing["id"], price_label="Reduced").status_code == 200

    set_workspace(owner_engine, admin["workspace_id"], subscription_state="offline")
    r = edit(c, listing["id"], price_label="Again")
    assert r.status_code == 403 and r.json()["error"]["code"] == "read_only"
    assert c.get(f"{L}/{listing['id']}").status_code == 200


def test_mark_sold_keeps_listing_public(admin):
    c = admin["client"]
    listing = new_listing(c)
    assert c.post(f"{L}/{listing['id']}/sold", headers=csrf(c)).status_code == 409
    publish(c, listing["id"])
    r = c.post(f"{L}/{listing['id']}/sold", headers=csrf(c))
    assert r.json()["live_state"] == "sold" and public_rows()[0].status == "sold"
    assert c.post(f"{L}/{listing['id']}/unpublish", headers=csrf(c)).json()["status"] == "draft"
    assert public_rows() == []


# ---------- roles ----------


def _member(make_client, owner_engine, admin, permissions, email="agent@example.com", licence=""):
    c = admin["client"]
    set_workspace(owner_engine, admin["workspace_id"], plan_key="team")
    role = c.post("/api/v1/team/roles", json={"name": email, "permissions": permissions}, headers=csrf(c)).json()
    member_client = make_client()
    member = sign_up(member_client, email)
    add_member(owner_engine, admin["workspace_id"], member["user"]["id"], role["id"])
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE memberships SET licence_number = :l WHERE user_id = :u"),
                     {"l": licence, "u": member["user"]["id"]})
        membership_id = conn.execute(text("SELECT id::text FROM memberships WHERE user_id = :u AND workspace_id = :w"),
                                     {"u": member["user"]["id"], "w": admin["workspace_id"]}).scalar_one()
    return member_client, membership_id


def test_agent_without_publish_goes_through_approval(admin, make_client, owner_engine):
    agent, _ = _member(make_client, owner_engine, admin, ["listings.create", "listings.edit_own"])
    listing = new_listing(agent, "Agent's home")
    assert listing["agent"] is None and listing["permissions"]["can_submit"] is True
    r = publish(agent, listing["id"])
    assert r.status_code == 403 and r.json()["error"]["code"] == "approval_required"

    r = agent.post(f"{L}/{listing['id']}/submit", headers=csrf(agent))
    assert r.json()["status"] == "pending_approval" and r.json()["awaiting_approval"] is True
    assert agent.post(f"{L}/{listing['id']}/approve", json={}, headers=csrf(agent)).status_code == 403

    c = admin["client"]
    r = c.post(f"{L}/{listing['id']}/approve", json={"acknowledge_compliance": True}, headers=csrf(c))
    assert r.status_code == 200 and r.json()["live_state"] == "live"

    edit(agent, listing["id"], title="Agent's home, updated")
    agent.post(f"{L}/{listing['id']}/submit", headers=csrf(agent))
    pending = c.get(f"{L}/{listing['id']}").json()
    assert pending["awaiting_approval"] is True and pending["live_state"] == "live"
    assert public_rows()[0].live["title"] == "Agent's home"
    c.post(f"{L}/{listing['id']}/approve", json={}, headers=csrf(c))
    assert public_rows()[0].live["title"] == "Agent's home, updated"


def test_own_vs_whole_team_editing(admin, make_client, owner_engine):
    admins_listing = new_listing(admin["client"], "Admin's home")
    agent, _ = _member(make_client, owner_engine, admin, ["listings.create", "listings.edit_own"])
    assert agent.get(f"{L}/{admins_listing['id']}").json()["permissions"]["can_edit"] is False
    assert edit(agent, admins_listing["id"], title="Mine now").status_code == 403
    assert agent.delete(f"{L}/{admins_listing['id']}", headers=csrf(agent)).status_code == 403

    editor, _ = _member(make_client, owner_engine, admin, ["listings.edit_all"], email="editor@example.com")
    assert edit(editor, admins_listing["id"], subtitle="Polished").status_code == 200
    assert editor.post(L, json={"title": "x"}, headers=csrf(editor)).status_code == 403


def test_listing_agent_needs_permission_and_licence(admin, make_client, owner_engine):
    c = admin["client"]
    listing = new_listing(c)
    _, plain = _member(make_client, owner_engine, admin, ["listings.create"], email="plain@example.com")
    r = edit(c, listing["id"], agent_member_id=plain)
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_agent"
    _, unlicensed = _member(make_client, owner_engine, admin, ["listings.listing_agent"], email="new@example.com")
    r = edit(c, listing["id"], agent_member_id=unlicensed)
    assert r.status_code == 422 and r.json()["error"]["code"] == "agent_needs_licence"
    _, licensed = _member(make_client, owner_engine, admin, ["listings.listing_agent"], email="pro@example.com",
                          licence="CA-998877")
    r = edit(c, listing["id"], agent_member_id=licensed)
    assert r.status_code == 200 and r.json()["agent"]["name"] == "pro@example.com"


# ---------- isolation ----------


def test_other_workspaces_cannot_touch_listings(admin, make_client, owner_engine):
    listing = new_listing(admin["client"])
    section_id = listing["sections"][0]["id"]
    rival = make_client()
    me = sign_up(rival, "rival@example.com")
    make_ready(rival, owner_engine, me["current_workspace_id"], username="rival")

    assert rival.get(L).json() == []
    lid = listing["id"]
    for method, path, body in (
        ("get", f"{L}/{lid}", None),
        ("patch", f"{L}/{lid}", {"title": "Stolen"}),
        ("delete", f"{L}/{lid}", None),
        ("post", f"{L}/{lid}/publish", {"acknowledge_compliance": True}),
        ("post", f"{L}/{lid}/sold", None),
        ("post", f"{L}/{lid}/sections", {"type": "quote"}),
        ("patch", f"{L}/{lid}/sections/{section_id}", {"content": {"heading": "x"}}),
        ("delete", f"{L}/{lid}/sections/{section_id}", None),
        ("put", f"{L}/{lid}/hero", {"enabled": False, "show_facts": False, "show_price": False}),
        ("put", f"{L}/{lid}/beats", []),
    ):
        kwargs = {"headers": csrf(rival)}
        if body is not None:
            kwargs["json"] = body
        r = getattr(rival, method)(path, **kwargs)
        assert r.status_code == 404, (method, path, r.status_code)
    assert admin["client"].get(f"{L}/{lid}").json()["title"] == "Villa Aurelia"


def test_database_refuses_attaching_content_to_another_workspaces_listing(admin, make_client, owner_engine):
    listing = new_listing(admin["client"])
    rival = sign_up(make_client(), "rival@example.com")
    with pytest.raises(IntegrityError):
        with tenant_session(rival["user"]["id"], rival["current_workspace_id"]) as s:
            s.execute(text("""INSERT INTO listing_sections (workspace_id, listing_id, type, layout_variant, sort_order)
                              VALUES (:w, :l, 'quote', 'large', 0)"""),
                      {"w": rival["current_workspace_id"], "l": listing["id"]})
    with pytest.raises(IntegrityError):
        with tenant_session(rival["user"]["id"], rival["current_workspace_id"]) as s:
            s.execute(text("INSERT INTO walkthrough_beats (workspace_id, listing_id, at) VALUES (:w, :l, 0.5)"),
                      {"w": rival["current_workspace_id"], "l": listing["id"]})

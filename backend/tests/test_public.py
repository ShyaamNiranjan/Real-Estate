from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app.db import public_session
from tests.auth_helpers import csrf, set_workspace, sign_up
from tests.test_listings import admin, edit, make_ready, new_listing, publish  # noqa: F401
from tests.test_media import add_image

P = "/api/v1/public"
W = "/api/v1/workspace"


def publish_site(c, ack=True):
    return c.post(f"{W}/site/publish", json={"acknowledge_compliance": ack}, headers=csrf(c))


def page(c, path):
    return c.get(f"{P}/sites/ana/listings/{path}")


# ---------- site ----------


def test_holding_page_until_the_site_is_published(admin):
    c = admin["client"]
    r = c.get(f"{P}/sites/ana")
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "holding" and body["noindex"] is True and body["site"] is None
    assert body["holding"]["display_name"] == "Ana Silva"
    assert body["holding"]["contact"]["email"] == "ana@example.com"
    assert body["featured"] == [] and body["listing_count"] == 0
    assert c.get(f"{P}/sites/ana/listings").status_code == 404
    assert c.get(f"{P}/sites/nobody").status_code == 404
    assert c.get(f"{W}").json()["site_state"] == "draft"


def test_site_publish_is_a_snapshot(admin):
    c = admin["client"]
    r = publish_site(c, ack=False)
    assert r.status_code == 409 and r.json()["error"]["code"] == "compliance_ack_required"
    c.patch(f"{W}/profile", headers=csrf(c), json={"tagline": "Homes on the coast", "bio": "Twenty years in Malibu."})
    first, second = new_listing(c, "Villa One"), new_listing(c, "Villa Two")
    publish(c, first["id"])
    r = c.put(f"{W}/site/featured", headers=csrf(c), json={"listing_ids": [second["id"], first["id"]]})
    assert r.json()["profile"]["featured_listing_ids"] == [second["id"], first["id"]]

    r = publish_site(c)
    assert r.status_code == 200, r.text
    assert r.json()["site_state"] == "live" and r.json()["site_has_unpublished_changes"] is False

    body = c.get(f"{P}/sites/ana").json()
    assert body["state"] == "live" and body["noindex"] is False
    assert body["site"]["tagline"] == "Homes on the coast" and body["site"]["bio"] == "Twenty years in Malibu."
    assert body["site"]["compliance"][0]["label"]
    # Only the published one of the two featured homes shows.
    assert [f["title"] for f in body["featured"]] == ["Villa One"] and body["listing_count"] == 1
    assert body["featured"][0]["path"] == "/ana/villa-one"

    r = c.patch(f"{W}/profile", headers=csrf(c), json={"tagline": "New tagline"})
    assert r.json()["site_has_unpublished_changes"] is True
    assert c.get(f"{P}/sites/ana").json()["site"]["tagline"] == "Homes on the coast"
    publish_site(c)
    assert c.get(f"{P}/sites/ana").json()["site"]["tagline"] == "New tagline"

    c.post(f"{W}/site/unpublish", headers=csrf(c))
    assert c.get(f"{P}/sites/ana").json()["state"] == "holding"
    # Listings publish independently of the site.
    assert page(c, "villa-one").status_code == 200


def test_site_publish_rules(admin, owner_engine):
    c = admin["client"]
    r = c.put(f"{W}/site/featured", headers=csrf(c), json={"listing_ids": ["00000000-0000-0000-0000-000000000001"]})
    assert r.json()["error"]["code"] == "invalid_listing"
    set_workspace(owner_engine, admin["workspace_id"], subscription_state="none")
    r = publish_site(c)
    assert r.status_code == 409 and r.json()["error"]["message"] == "Choose a plan to publish."
    assert c.get(W).json()["site_blockers"][0]["code"] == "plan"


def test_properties_filters(admin):
    c = admin["client"]
    for title, price, beds in (("Cottage", 400000, 2), ("Manor", 3000000, 6)):
        listing = new_listing(c, title)
        edit(c, listing["id"], price_amount=price, bedrooms=beds, location="Malibu, CA")
        publish(c, listing["id"])
    publish_site(c)
    titles = lambda **q: [x["title"] for x in c.get(f"{P}/sites/ana/listings", params=q).json()]  # noqa: E731
    assert sorted(titles()) == ["Cottage", "Manor"]
    assert titles(min_price=1000000) == ["Manor"]
    assert titles(max_price=1000000, min_beds=2) == ["Cottage"]
    assert titles(location="malibu") and titles(location="Paris") == []


# ---------- listing pages ----------


def test_listing_page_shows_only_published_content(admin):
    c = admin["client"]
    listing = new_listing(c)
    edit(c, listing["id"], summary="PRIVATE NOTE", subtitle="Ocean views", price_amount=2450000)
    assert page(c, "villa-aurelia").status_code == 404
    publish(c, listing["id"])
    edit(c, listing["id"], subtitle="Draft change")

    r = page(c, "villa-aurelia")
    assert r.status_code == 200 and "s-maxage" in r.headers["cache-control"]
    data = r.json()["page"]
    assert data["path"] == "/ana/villa-aurelia" and data["status"] == "published" and data["site_live"] is False
    content = data["content"]
    assert content["subtitle"] == "Ocean views" and content["price_amount"] == 2450000
    assert content["agent"]["name"] == "admin@example.com"
    assert content["brand"]["display_name"] == "Ana Silva" and data["contact"]["email"] == "ana@example.com"
    assert "PRIVATE NOTE" not in r.text and "created_by" not in r.text and "image_media_id" not in r.text


def test_renamed_listing_redirects_from_the_old_address(admin):
    c = admin["client"]
    listing = new_listing(c)
    publish(c, listing["id"])
    edit(c, listing["id"], slug="villa-aurelia-malibu")
    assert page(c, "villa-aurelia").json()["page"] is not None
    publish(c, listing["id"])
    assert page(c, "villa-aurelia").json() == {"redirect_to": "/ana/villa-aurelia-malibu", "page": None}
    assert page(c, "villa-aurelia-malibu").json()["page"]["path"] == "/ana/villa-aurelia-malibu"


def test_sold_page_links_to_other_homes(admin):
    c = admin["client"]
    sold, other = new_listing(c, "Sold Villa"), new_listing(c, "Other Villa")
    publish(c, sold["id"]), publish(c, other["id"])
    c.post(f"/api/v1/listings/{sold['id']}/sold", headers=csrf(c))
    data = page(c, "sold-villa").json()["page"]
    assert data["status"] == "sold" and data["other_homes"] == []
    publish_site(c)
    data = page(c, "sold-villa").json()["page"]
    assert [h["title"] for h in data["other_homes"]] == ["Other Villa"]


def test_expired_trial_and_offline_pages_return_503(admin, owner_engine):
    c = admin["client"]
    listing = new_listing(c)
    publish(c, listing["id"])
    publish_site(c)
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE listings SET trial_expires_at = :t WHERE id = :id"),
                     {"t": datetime.now(UTC) - timedelta(days=1), "id": listing["id"]})
    set_workspace(owner_engine, admin["workspace_id"], subscription_state="trialing")
    r = page(c, "villa-aurelia")
    assert r.status_code == 503 and r.json()["error"]["code"] == "temporarily_unavailable"
    assert c.get(f"{P}/sites/ana").json()["listing_count"] == 0
    set_workspace(owner_engine, admin["workspace_id"], subscription_state="active")
    assert page(c, "villa-aurelia").status_code == 200

    set_workspace(owner_engine, admin["workspace_id"], subscription_state="offline")
    assert page(c, "villa-aurelia").status_code == 503
    assert c.get(f"{P}/sites/ana").status_code == 503
    assert c.get(f"{P}/sitemaps").json() == []


def test_public_page_carries_published_media(admin):
    c = admin["client"]
    listing = new_listing(c)
    photo = add_image(c, listing["id"])
    publish(c, listing["id"])
    publish_site(c)
    content = page(c, "villa-aurelia").json()["page"]["content"]
    assert content["gallery"][0]["id"] == photo["id"] and "/public/" in content["gallery"][0]["url"]
    card = c.get(f"{P}/sites/ana/listings").json()[0]
    assert card["image"]["url"] == content["gallery"][0]["url"]


# ---------- sitemaps ----------


def test_sitemaps(admin):
    c = admin["client"]
    assert c.get(f"{P}/sitemaps").json() == []
    listing = new_listing(c)
    publish(c, listing["id"])
    assert [s["username"] for s in c.get(f"{P}/sitemaps").json()] == ["ana"]
    assert [e["path"] for e in c.get(f"{P}/sitemaps/ana").json()] == ["/ana/villa-aurelia"]
    publish_site(c)
    paths = [e["path"] for e in c.get(f"{P}/sitemaps/ana").json()]
    assert paths == ["/ana", "/ana/properties", "/ana/about", "/ana/contact", "/ana/villa-aurelia"]


# ---------- draft preview ----------


def test_owner_preview_shows_the_draft(admin, make_client):
    c = admin["client"]
    listing = new_listing(c)
    edit(c, listing["id"], subtitle="Draft subtitle")
    add_image(c, listing["id"])
    r = c.get(f"/api/v1/listings/{listing['id']}/preview")
    assert r.status_code == 200
    body = r.json()
    assert body["noindex"] is True and body["content"]["subtitle"] == "Draft subtitle"
    assert "/file/" in body["content"]["gallery"][0]["url"]
    assert c.get(body["content"]["gallery"][0]["url"]).status_code == 200

    stranger = make_client()
    assert stranger.get(f"/api/v1/listings/{listing['id']}/preview").status_code == 401
    sign_up(stranger, "bob@example.com")
    assert stranger.get(f"/api/v1/listings/{listing['id']}/preview").status_code == 404


# ---------- database layer ----------


def test_public_role_sees_only_published_snapshots(admin):
    c = admin["client"]
    draft, live = new_listing(c, "Draft"), new_listing(c, "Live")
    publish(c, live["id"])
    with public_session() as s:
        rows = s.execute(text("SELECT id FROM listings")).scalars().all()
    assert [str(r) for r in rows] == [live["id"]]
    for column in ("summary", "title", "created_by", "slug"):
        with pytest.raises(ProgrammingError), public_session() as s:
            s.execute(text(f"SELECT {column} FROM listings"))
    for statement in ("SELECT plan_key FROM workspaces", "SELECT * FROM media", "SELECT * FROM users",
                      "SELECT setup FROM workspace_profiles"):
        with pytest.raises(ProgrammingError), public_session() as s:
            s.execute(text(statement))

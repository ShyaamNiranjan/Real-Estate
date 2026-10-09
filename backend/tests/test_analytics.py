from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from app import analytics, email
from app.db import tenant_session
from tests.auth_helpers import csrf, mails_to
from tests.test_enquiries import enquire, visitor
from tests.test_listings import _member, admin, edit, make_ready, new_listing, publish  # noqa: F401

P = "/api/v1/public"
A = "/api/v1/analytics"
PHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1"
DESKTOP = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140.0 Safari/537.36"


def beacon(ip, events, slug="villa-aurelia", ua=DESKTOP, referrer="", view_id=None, headers=None, client=None, **extra):
    body = {"username": "ana", "listing_slug": slug, "path": f"/ana/{slug or ''}", "referrer": referrer,
            "view_id": str(view_id or uuid4()), "events": events, **extra}
    return (client or visitor(ip)).post(f"{P}/events", json=body, headers={"User-Agent": ua, **(headers or {})})


def views(n=1):
    return [{"event": "pageview"}] * n


def events(owner_engine):
    with owner_engine.connect() as conn:
        return conn.execute(text("SELECT * FROM analytics_events ORDER BY id")).all()


@pytest.fixture
def live(admin):
    c = admin["client"]
    listing = new_listing(c)
    c.put(f"/api/v1/listings/{listing['id']}/beats", headers=csrf(c),
          json=[{"at": 0.5, "label": "Kitchen", "text": ""}, {"at": 0.9, "label": "Terrace", "text": ""}])
    publish(c, listing["id"])
    return listing


# ---------- ingest ----------


def test_visits_are_recorded_without_cookies_or_ips(admin, live, owner_engine):
    r = beacon("10.0.0.1", views(), ua=PHONE, referrer="https://www.google.com/",
               headers={"CF-IPCountry": "PT", "CF-IPCity": "Lisbon"})
    assert r.status_code == 204 and "set-cookie" not in r.headers
    beacon("10.0.0.1", views(), referrer="https://www.instagram.com/")
    [first, second] = events(owner_engine)
    assert first.source == "search" and first.device == "mobile" and (first.country, first.city) == ("PT", "Lisbon")
    assert second.source == "link" and second.device == "desktop"
    assert len(first.visitor_hash) == 32 and "10.0.0.1" not in str(first._mapping.values())
    # Same person, different browser → a different visitor; same browser → same visitor.
    assert first.visitor_hash != second.visitor_hash
    beacon("10.0.0.1", views(), ua=PHONE)
    assert events(owner_engine)[2].visitor_hash == first.visitor_hash


def test_bots_headless_browsers_and_own_visits_are_ignored(admin, live, owner_engine):
    beacon("10.0.0.2", views(), ua="Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)")
    beacon("10.0.0.3", views(), ua="Mozilla/5.0 HeadlessChrome/140.0")
    beacon("10.0.0.4", views(), webdriver=True)
    beacon("10.0.0.5", views(), ua="")
    beacon("10.0.0.6", views(), client=admin["client"])
    beacon("10.0.0.7", views(), slug="not-a-listing")
    beacon("10.0.0.8", views(), slug=None)
    assert events(owner_engine) == []


def test_salts_rotate_daily(admin, live, owner_engine):
    with owner_engine.begin() as conn:
        conn.execute(text("INSERT INTO analytics_salts (day, salt) VALUES (:d, '\\x00')"),
                     {"d": date.today() - timedelta(days=5)})
    beacon("10.0.0.9", views())
    with owner_engine.connect() as conn:
        days = conn.execute(text("SELECT day FROM analytics_salts")).scalars().all()
    assert days == [datetime.now(UTC).date()]


# ---------- summaries ----------


def test_listing_summary_with_walkthrough_drop_off(admin, live):
    c = admin["client"]
    for i, depth in enumerate((0.3, 0.6, 1.0)):
        view = uuid4()
        beacon(f"10.1.0.{i}", views() + [{"event": "walk_depth", "value": depth / 2}], view_id=view)
        beacon(f"10.1.0.{i}", [{"event": "walk_depth", "value": depth}, {"event": "gallery_open"}], view_id=view)
    beacon("10.1.0.9", views(), referrer="https://www.bing.com/search?q=villa")
    enquire(c, admin["workspace_id"])

    s = c.get(f"{A}/summary", params={"listing_id": live["id"], "days": 7}).json()
    assert s["totals"] == {"views": 4, "visitors": 4, "enquiries": 1, "enquiry_rate": 0.25}
    assert s["sources"] == {"link": 3, "search": 1}
    assert s["series"][-1]["views"] == 4 and len(s["series"]) == 7
    assert s["clicks"]["gallery_open"] == 3
    w = s["walkthrough"]
    assert w["starts"] == 3 and w["completion_rate"] == pytest.approx(1 / 3, abs=0.001)
    assert w["average_depth"] == pytest.approx(0.633, abs=0.001)
    assert [(b["label"], b["reached"]) for b in w["drop_off"]] == [("Kitchen", pytest.approx(0.667, abs=0.001)),
                                                                     ("Terrace", pytest.approx(0.333, abs=0.001))]

    ws = c.get(f"{A}/summary").json()
    assert ws["walkthrough"] is None and ws["listings"][0]["title"] == "Villa Aurelia"
    assert c.get(f"{A}/summary", params={"days": 12}).status_code == 422


def test_agents_see_only_their_own_listings(admin, make_client, owner_engine):
    c = admin["client"]
    agent_client, agent_member = _member(make_client, owner_engine, admin,
                                         ["analytics.view_own", "listings.listing_agent"], licence="LIC-1")
    mine, other = new_listing(c, "Agent Home"), new_listing(c, "Office Home")
    edit(c, mine["id"], agent_member_id=agent_member)
    publish(c, mine["id"]), publish(c, other["id"])
    beacon("10.2.0.1", views(), slug="agent-home")
    beacon("10.2.0.2", views(3), slug="office-home")

    assert agent_client.get(f"{A}/summary").json()["totals"]["views"] == 1
    assert agent_client.get(f"{A}/summary", params={"listing_id": other["id"]}).status_code == 404
    assert c.get(f"{A}/summary").json()["totals"]["views"] == 4
    nobody, _ = _member(make_client, owner_engine, admin, ["listings.create"], email="desk@example.com")
    assert nobody.get(f"{A}/summary").status_code == 403
    with owner_engine.connect() as conn:
        desk = conn.execute(text("SELECT id FROM users WHERE email = 'desk@example.com'")).scalar_one()
    with tenant_session(desk, admin["workspace_id"]) as s:
        assert s.execute(text("SELECT count(*) FROM analytics_events")).scalar_one() == 0


# ---------- seller reports ----------


def test_seller_report_link(admin, live, make_client, owner_engine):
    c = admin["client"]
    other = new_listing(c, "Other Home")
    publish(c, other["id"])
    beacon("10.3.0.1", views(2))
    beacon("10.3.0.2", views(5), slug="other-home")

    r = c.post(f"{A}/reports", json={"listing_id": live["id"]}, headers=csrf(c))
    assert r.status_code == 201
    url = r.json()["url"]
    assert url.startswith("https://testserver/ana/villa-aurelia/report?t=")
    token = url.split("t=", 1)[1]
    assert c.get(f"{A}/reports", params={"listing_id": live["id"]}).json()[0]["url"] is None

    stranger = make_client()
    report = stranger.get(f"{P}/reports/{token}").json()
    assert report["title"] == "Villa Aurelia" and report["noindex"] is True
    assert report["summary"]["totals"]["views"] == 2 and report["summary"]["walkthrough"]["starts"] == 0
    assert stranger.get(f"{P}/reports/not-a-token").status_code == 404

    report_id = r.json()["id"]
    assert c.delete(f"{A}/reports/{report_id}", headers=csrf(c)).status_code == 204
    assert stranger.get(f"{P}/reports/{token}").status_code == 404

    draft = new_listing(c, "Draft Home")
    r = c.post(f"{A}/reports", json={"listing_id": draft["id"]}, headers=csrf(c))
    assert r.status_code == 409


def test_report_context_opens_exactly_one_listing(admin, live, owner_engine):
    c = admin["client"]
    other = new_listing(c, "Other Home")
    publish(c, other["id"])
    beacon("10.4.0.1", views())
    beacon("10.4.0.2", views(), slug="other-home")
    with tenant_session(None, admin["workspace_id"]) as s:
        assert s.execute(text("SELECT count(*) FROM analytics_events")).scalar_one() == 0
        s.execute(text("SELECT set_config('app.report_listing_id', :l, true)"), {"l": live["id"]})
        assert s.execute(text("SELECT count(*) FROM analytics_events")).scalar_one() == 1


def test_seller_reports_need_the_permission(admin, live, make_client, owner_engine):
    agent_client, _ = _member(make_client, owner_engine, admin, ["analytics.view_all"])
    r = agent_client.post(f"{A}/reports", json={"listing_id": live["id"]}, headers=csrf(agent_client))
    assert r.status_code == 403


# ---------- weekly email ----------


def test_weekly_summary_email(admin, live, owner_engine):
    beacon("10.5.0.1", views(3))
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE analytics_events SET day = day - 1"))
    email.outbox.clear()
    assert analytics.send_weekly_summaries() == 1
    [message] = mails_to("admin@example.com")
    assert message.subject == "Ana Silva week: 3 views, 0 enquiries"
    assert "Villa Aurelia: 3 views" in message.text
    preview = admin["client"].get(f"{A}/weekly-preview").json()
    assert preview["subject"] == message.subject

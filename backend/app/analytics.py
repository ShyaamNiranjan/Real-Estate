"""Cookieless analytics (docs/SCOPE.md 6, 8.11).

No cookies and no stored IPs: a visitor is a hash of (daily random salt, IP, browser, workspace)
and the salt is deleted after a day. Bots, headless browsers and the realtor's own visits are
dropped at ingest. Visibility is enforced by the database (0008): agents see their own listings,
members with "see the whole team's analytics" see everything, and a seller report link opens
exactly one listing.
"""

import hashlib
import re
from datetime import UTC, date, datetime, timedelta
from typing import Literal
from urllib.parse import urlparse
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import email as mail
from app.config import get_settings
from app.db import public_session, tenant_session
from app.deps import Auth, client_ip, cookie_names, in_workspace
from app.errors import ApiError, ErrorResponse
from app.permissions import Access, load_access
from app.ratelimit import Rule, enforce
from app.security import new_token, token_hash
from app.usernames import normalize

public_router = APIRouter(prefix="/api/v1/public", tags=["public"],
                          responses={k: {"model": ErrorResponse} for k in (404, 429)})
router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"],
                   responses={k: {"model": ErrorResponse} for k in (401, 403, 404, 422)})

EventName = Literal["pageview", "leave", "walk_depth", "gallery_open", "floor_plan_view", "enquiry_click",
                    "phone_tap", "whatsapp_tap", "booking_click"]
CLICKS = ("gallery_open", "floor_plan_view", "enquiry_click", "phone_tap", "whatsapp_tap", "booking_click")
INGEST_IP = Rule("analytics-ip", 300, 600)
REPORT_IP = Rule("report-ip", 60, 600)
BOT_UA = re.compile(r"bot|crawl|spider|slurp|headless|lighthouse|pagespeed|preview|facebookexternalhit|"
                    r"whatsapp|telegram|discord|curl|wget|python|httpx|okhttp|java/|go-http|phantom|selenium|"
                    r"puppeteer|playwright", re.I)
SEARCH_HOSTS = re.compile(r"(^|\.)(google|bing|duckduckgo|yahoo|yandex|baidu|ecosia|startpage|qwant|naver|"
                          r"seznam|brave)\.[a-z.]+$", re.I)
WALK_STARTED = 0.02
WALK_COMPLETE = 0.95
PERIODS = {7, 30, 90}


# ---------- ingest ----------


class EventIn(BaseModel):
    event: EventName
    value: float | None = Field(default=None, ge=0, le=1)


class EventsIn(BaseModel):
    username: str = Field(max_length=60)
    listing_slug: str | None = Field(default=None, max_length=80)
    path: str = Field(default="", max_length=200)
    referrer: str = Field(default="", max_length=500)
    view_id: UUID = Field(description="Random id generated once per page load (not stored in the browser).")
    webdriver: bool = Field(default=False, description="navigator.webdriver")
    events: list[EventIn] = Field(min_length=1, max_length=20)


def device_of(ua: str) -> str:
    if re.search(r"ipad|tablet|kindle|silk|(android(?!.*mobile))", ua, re.I):
        return "tablet"
    if re.search(r"mobi|iphone|ipod|android|phone", ua, re.I):
        return "mobile"
    return "desktop"


def source_of(referrer: str) -> str:
    host = (urlparse(referrer).hostname or "").lower() if referrer else ""
    if not host:
        return "link"
    own = {(urlparse(u).hostname or "").lower() for u in (get_settings().app_url, "https://scrollwalk.com")}
    if host in own or host.endswith(".scrollwalk.com"):
        return "internal"
    return "search" if SEARCH_HOSTS.search(host) else "link"


def _location(request: Request) -> tuple[str, str]:
    h = request.headers
    country = (h.get("cf-ipcountry") or h.get("x-vercel-ip-country") or "").upper()
    city = h.get("cf-ipcity") or h.get("x-vercel-ip-city") or ""
    country = country if re.fullmatch(r"[A-Z]{2}", country) and country not in ("XX", "T1") else ""
    return country, city[:80]


def _own_visit(request: Request, workspace_id: UUID) -> bool:
    token = request.cookies.get(cookie_names()[0])
    if not token:
        return False
    with tenant_session() as s:
        row = s.execute(text("SELECT user_id FROM auth_session_lookup(:h)"), {"h": token_hash(token)}).first()
    if row is None:
        return False
    with tenant_session(row.user_id, workspace_id) as s:
        return s.execute(text("""SELECT 1 FROM memberships WHERE workspace_id = :w AND user_id = :u
                                 AND removed_at IS NULL"""), {"w": workspace_id, "u": row.user_id}).first() is not None


@public_router.post("/events", status_code=204)
def ingest(body: EventsIn, request: Request) -> Response:
    """Page beacons. Always answers 204; anything filtered is simply not recorded."""
    done = Response(status_code=204)
    ua = request.headers.get("user-agent", "")
    if not ua or body.webdriver or BOT_UA.search(ua):
        return done
    ip = client_ip(request)
    enforce((INGEST_IP, ip))
    with public_session() as s:
        ws = s.execute(text("SELECT id, subscription_state, site_live FROM workspaces WHERE username = :u"),
                       {"u": normalize(body.username)}).first()
        if ws is None or ws.subscription_state == "offline":
            return done
        listing_id = None
        if body.listing_slug:
            listing_id = s.execute(text("SELECT id FROM listings WHERE workspace_id = :w AND live_slug = :s"),
                                   {"w": ws.id, "s": body.listing_slug.lower()}).scalar_one_or_none()
            if listing_id is None:
                return done
        elif ws.site_live is None:
            return done
    if _own_visit(request, ws.id):
        return done
    country, city = _location(request)
    with tenant_session(None, ws.id) as s:
        salt = s.execute(text("SELECT analytics_salt()")).scalar_one()
        visitor = hashlib.sha256(salt + f"|{ip}|{ua}|{ws.id}".encode()).hexdigest()[:32]
        today = datetime.now(UTC).date()
        rows = [{"w": ws.id, "l": listing_id, "d": today, "v": body.view_id, "h": visitor, "src": source_of(body.referrer),
                 "dev": device_of(ua), "c": country, "city": city, "e": e.event,
                 "val": e.value if e.event == "walk_depth" else None, "p": body.path}
                for e in body.events]
        s.execute(text("""INSERT INTO analytics_events (workspace_id, listing_id, day, view_id, visitor_hash, source,
                                                        device, country, city, event, value, path)
                          VALUES (:w, :l, :d, :v, :h, :src, :dev, :c, :city, :e, :val, :p)"""), rows)
    return done


# ---------- summaries ----------


class DayPoint(BaseModel):
    day: date
    views: int
    visitors: int
    enquiries: int


class Totals(BaseModel):
    views: int
    visitors: int = Field(description="Sum of daily unique visitors (visitors can't be linked across days).")
    enquiries: int
    enquiry_rate: float


class Named(BaseModel):
    name: str
    visitors: int


class BeatReach(BaseModel):
    at: float
    label: str
    reached: float = Field(description="Share of walkthrough starts that got this far (0–1).")


class WalkthroughStats(BaseModel):
    starts: int
    average_depth: float
    completion_rate: float
    drop_off: list[BeatReach]


class ListingStat(BaseModel):
    listing_id: UUID
    title: str
    views: int
    visitors: int


class Summary(BaseModel):
    start: date
    end: date
    totals: Totals
    series: list[DayPoint]
    sources: dict[Literal["link", "search"], int]
    devices: dict[Literal["mobile", "tablet", "desktop"], int]
    countries: list[Named]
    cities: list[Named]
    clicks: dict[str, int]
    walkthrough: WalkthroughStats | None
    listings: list[ListingStat]


def summarize(s: Session, listing_ids: list[UUID], site: bool, start: date, end: date,
              beats: list[dict] | None = None, per_listing: bool = False) -> Summary:
    scope = "e.day BETWEEN :start AND :end AND (e.listing_id = ANY(:ids) OR (:site AND e.listing_id IS NULL))"
    p = {"start": start, "end": end, "ids": listing_ids, "site": site}
    q = lambda sql: s.execute(text(sql.replace("{scope}", scope)), p).all()  # noqa: E731

    per_day = {r.day: r for r in q("""SELECT day, count(*) AS views, count(DISTINCT visitor_hash) AS visitors
                                      FROM analytics_events e WHERE {scope} AND event = 'pageview' GROUP BY day""")}
    enquiries = dict(s.execute(text("SELECT day, n FROM enquiry_daily_counts(:ids, :site, :start)"), p).all())
    series = []
    for i in range((end - start).days + 1):
        d = start + timedelta(days=i)
        r = per_day.get(d)
        series.append(DayPoint(day=d, views=r.views if r else 0, visitors=r.visitors if r else 0,
                               enquiries=enquiries.get(d, 0)))
    visitors = sum(x.visitors for x in series)
    enquiry_total = sum(x.enquiries for x in series)

    def daily_unique(column: str) -> dict[str, int]:
        return {r.k: r.n for r in q(f"""SELECT {column} AS k, count(DISTINCT (day, visitor_hash)) AS n
                                        FROM analytics_events e WHERE {{scope}} AND event = 'pageview'
                                        AND {column} <> '' GROUP BY 1""")}

    sources = daily_unique("source")
    devices = daily_unique("device")
    countries = sorted(daily_unique("country").items(), key=lambda kv: -kv[1])[:10]
    cities = sorted(daily_unique("city").items(), key=lambda kv: -kv[1])[:10]
    clicks = {r.event: r.n for r in q("""SELECT event, count(*) AS n FROM analytics_events e
                                         WHERE {scope} AND event IN ('gallery_open', 'floor_plan_view', 'enquiry_click',
                                         'phone_tap', 'whatsapp_tap', 'booking_click') GROUP BY event""")}

    walkthrough = None
    if beats is not None:
        depths = [r.d for r in q("""SELECT max(value) AS d FROM analytics_events e
                                    WHERE {scope} AND event = 'walk_depth' GROUP BY view_id""")]
        started = [d for d in depths if d is not None and d >= WALK_STARTED]
        n = len(started)
        walkthrough = WalkthroughStats(
            starts=n, average_depth=round(sum(started) / n, 3) if n else 0.0,
            completion_rate=round(sum(d >= WALK_COMPLETE for d in started) / n, 3) if n else 0.0,
            drop_off=[BeatReach(at=b["at"], label=b.get("label", ""),
                                reached=round(sum(d >= b["at"] for d in started) / n, 3) if n else 0.0) for b in beats],
        )

    listings = []
    if per_listing:
        listings = [ListingStat(listing_id=r.listing_id, title=r.title, views=r.views, visitors=r.visitors)
                    for r in q("""SELECT e.listing_id, l.title, count(*) AS views,
                                         count(DISTINCT (e.day, e.visitor_hash)) AS visitors
                                  FROM analytics_events e JOIN listings l ON l.id = e.listing_id
                                  WHERE {scope} AND e.event = 'pageview' GROUP BY e.listing_id, l.title
                                  ORDER BY views DESC LIMIT 20""")]
    return Summary(
        start=start, end=end,
        totals=Totals(views=sum(x.views for x in series), visitors=visitors, enquiries=enquiry_total,
                      enquiry_rate=round(enquiry_total / visitors, 4) if visitors else 0.0),
        series=series, sources={"link": sources.get("link", 0), "search": sources.get("search", 0)},
        devices={k: devices.get(k, 0) for k in ("mobile", "tablet", "desktop")},
        countries=[Named(name=k, visitors=v) for k, v in countries],
        cities=[Named(name=k, visitors=v) for k, v in cities],
        clicks={k: clicks.get(k, 0) for k in CLICKS}, walkthrough=walkthrough, listings=listings,
    )


def _scope(s: Session, access: Access) -> tuple[list[UUID], bool]:
    """Listings this member may see analytics for, and whether site pages are included."""
    if access.has("analytics.view_all"):
        return list(s.execute(text("SELECT id FROM listings")).scalars()), True
    if access.has("analytics.view_own"):
        return list(s.execute(text("""SELECT id FROM listings WHERE agent_member_id = :m
                                      OR (agent_member_id IS NULL AND created_by = :u)"""),
                              {"m": access.membership_id, "u": access.user_id}).scalars()), False
    raise ApiError(403, "permission_denied", "Your role doesn't include analytics.")


def _beats(s: Session, listing_id: UUID) -> list[dict]:
    rows = s.execute(text("SELECT at, label FROM walkthrough_beats WHERE listing_id = :l ORDER BY at"),
                     {"l": listing_id}).all()
    return [{"at": float(r.at), "label": r.label} for r in rows]


@router.get("/summary", response_model=Summary)
def summary(days: int = Query(default=30), listing_id: UUID | None = None,
            auth: Auth = Depends(in_workspace)) -> Summary:
    """Workspace-wide (with top listings) or one listing (with walkthrough depth and drop-off by caption)."""
    if days not in PERIODS:
        raise ApiError(422, "invalid_period", "Choose 7, 30 or 90 days.")
    end = datetime.now(UTC).date()
    start = end - timedelta(days=days - 1)
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        ids, site = _scope(s, load_access(s, auth.user_id, auth.workspace_id))
        if listing_id is not None:
            if listing_id not in ids:
                raise ApiError(404, "not_found", "That listing doesn't exist.")
            return summarize(s, [listing_id], False, start, end, beats=_beats(s, listing_id))
        return summarize(s, ids, site, start, end, per_listing=True)


# ---------- seller reports ----------


class ReportCreate(BaseModel):
    listing_id: UUID


class ReportOut(BaseModel):
    id: UUID
    listing_id: UUID
    created_at: datetime
    url: str | None = Field(default=None, description="Only returned once, when the report is created.")


class SellerReport(BaseModel):
    title: str
    location: str
    path: str
    status: str
    image: dict | None
    agent_name: str
    brand: dict
    published_at: datetime | None
    generated_at: datetime
    noindex: Literal[True] = True
    summary: Summary


@router.post("/reports", status_code=201, response_model=ReportOut)
def create_report(body: ReportCreate, auth: Auth = Depends(in_workspace)) -> ReportOut:
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        access = load_access(s, auth.user_id, auth.workspace_id)
        access.require("analytics.seller_reports")
        ids, _ = _scope(s, access)
        row = s.execute(text("""SELECT l.id, l.live_slug, l.status, w.username FROM listings l
                                JOIN workspaces w ON w.id = l.workspace_id
                                WHERE l.id = :id AND l.deleted_at IS NULL"""), {"id": body.listing_id}).first()
        if row is None or row.id not in ids:
            raise ApiError(404, "not_found", "That listing doesn't exist.")
        if row.status not in ("published", "sold") or not row.username:
            raise ApiError(409, "not_live", "Publish this listing before sharing a seller report.")
        token = new_token()
        report = s.execute(text("""INSERT INTO seller_reports (workspace_id, listing_id, token_hash, created_by)
                                   VALUES (:w, :l, :h, :u) RETURNING id, created_at"""),
                           {"w": auth.workspace_id, "l": row.id, "h": token_hash(token), "u": auth.user_id}).one()
    url = f"{get_settings().app_url}/{row.username}/{row.live_slug}/report?t={token}"
    return ReportOut(id=report.id, listing_id=row.id, created_at=report.created_at, url=url)


@router.get("/reports", response_model=list[ReportOut])
def list_reports(listing_id: UUID = Query(), auth: Auth = Depends(in_workspace)) -> list[ReportOut]:
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        load_access(s, auth.user_id, auth.workspace_id).require("analytics.seller_reports")
        rows = s.execute(text("""SELECT id, listing_id, created_at FROM seller_reports
                                 WHERE listing_id = :l AND revoked_at IS NULL ORDER BY created_at DESC"""),
                         {"l": listing_id}).all()
    return [ReportOut(id=r.id, listing_id=r.listing_id, created_at=r.created_at) for r in rows]


@router.delete("/reports/{report_id}", status_code=204)
def revoke_report(report_id: UUID, auth: Auth = Depends(in_workspace)) -> Response:
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        load_access(s, auth.user_id, auth.workspace_id).require("analytics.seller_reports")
        done = s.execute(text("UPDATE seller_reports SET revoked_at = now() WHERE id = :id AND revoked_at IS NULL "
                              "RETURNING id"), {"id": report_id}).first()
    if done is None:
        raise ApiError(404, "not_found", "That report link doesn't exist.")
    return Response(status_code=204)


@public_router.get("/reports/{token}", response_model=SellerReport)
def open_report(token: str, request: Request) -> SellerReport:
    """The seller report behind an unguessable link: one listing, since it was first published."""
    enforce((REPORT_IP, client_ip(request)))
    with tenant_session() as s:
        found = s.execute(text("SELECT * FROM seller_report_lookup(:h)"), {"h": token_hash(token[:200])}).first()
    if found is None:
        raise ApiError(404, "not_found", "This report link isn't valid any more.")
    with tenant_session(None, found.workspace_id) as s:
        s.execute(text("SELECT set_config('app.report_listing_id', :l, true)"), {"l": str(found.listing_id)})
        listing = s.execute(text("""SELECT l.*, w.username FROM listings l JOIN workspaces w ON w.id = l.workspace_id
                                    WHERE l.id = :id"""), {"id": found.listing_id}).one()
        live = listing.live or {}
        end = datetime.now(UTC).date()
        start = max((listing.published_at or listing.created_at).astimezone(UTC).date(), end - timedelta(days=364))
        result = summarize(s, [listing.id], False, start, end, beats=_beats(s, listing.id))
    from app.public import _card_image

    image = _card_image(live)
    return SellerReport(
        title=live.get("title", listing.title), location=live.get("location", listing.location),
        path=f"/{listing.username}/{listing.live_slug or listing.slug}", status=listing.status,
        image=image.model_dump(mode="json") if image else None,
        agent_name=(live.get("agent") or {}).get("name", ""),
        brand={k: (live.get("brand") or {}).get(k, "") for k in ("display_name", "brokerage_name", "style_preset")},
        published_at=listing.published_at, generated_at=datetime.now(UTC), summary=result,
    )


# ---------- weekly email ----------


class WeeklyEmail(BaseModel):
    subject: str
    text: str


def weekly_email(s: Session, access: Access, display_name: str) -> WeeklyEmail:
    end = datetime.now(UTC).date() - timedelta(days=1)
    start = end - timedelta(days=6)
    ids, site = _scope(s, access)
    result = summarize(s, ids, site, start, end, per_listing=True)
    t = result.totals
    lines = [f"Your week on Scrollwalk ({start:%b %d} – {end:%b %d})", "",
             f"Views: {t.views:,}", f"Visitors: {t.visitors:,}", f"Enquiries: {t.enquiries:,}",
             f"Through a link: {result.sources['link']:,} · Found on Google: {result.sources['search']:,}"]
    if result.listings:
        lines += ["", "Most viewed:"] + [f"- {x.title}: {x.views:,} views" for x in result.listings[:3]]
    lines += ["", "See everything in your Studio."]
    return WeeklyEmail(subject=f"{display_name or 'Your'} week: {t.views:,} views, {t.enquiries:,} enquiries",
                       text="\n".join(lines))


@router.get("/weekly-preview", response_model=WeeklyEmail)
def weekly_preview(auth: Auth = Depends(in_workspace)) -> WeeklyEmail:
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        access = load_access(s, auth.user_id, auth.workspace_id)
        name = s.execute(text("SELECT display_name FROM workspaces WHERE id = :w"), {"w": auth.workspace_id}).scalar_one()
        return weekly_email(s, access, name)


def send_weekly_summaries() -> int:
    """Run weekly (scheduler): one email per member who can see analytics, for workspaces with visits."""
    since = datetime.now(UTC).date() - timedelta(days=7)
    with tenant_session() as s:
        recipients = s.execute(text("SELECT * FROM weekly_summary_recipients(:d)"), {"d": since}).all()
    sent = 0
    for r in recipients:
        with tenant_session(r.user_id, r.workspace_id) as s:
            access = load_access(s, r.user_id, r.workspace_id)
            name = s.execute(text("SELECT display_name FROM workspaces WHERE id = :w"),
                             {"w": r.workspace_id}).scalar_one()
            message = weekly_email(s, access, name)
        mail.send(mail.Email(to=r.email, subject=message.subject, text=message.text))
        sent += 1
    return sent

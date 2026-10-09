"""Public pages: realtor sites, listing pages, sitemaps (docs/SCOPE.md 5, 8.3, 8.9, 8.12).

Read-only, no sign-in, served through the restricted `app_public` database role, which can only
see claimed workspaces and the published snapshot of published or sold listings. Responses are
rebuilt through the models in `app.content`, so nothing outside those shapes can leak.
"""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel
from sqlalchemy import Row, text
from sqlalchemy.orm import Session

from app.content import Contact, Image, ListingCard, ListingContent, SiteContent
from app.db import public_session
from app.errors import ApiError, ErrorResponse
from app.usernames import normalize

router = APIRouter(prefix="/api/v1/public", tags=["public"],
                   responses={k: {"model": ErrorResponse} for k in (404, 503)})

CACHE = "public, max-age=0, s-maxage=30, stale-while-revalidate=300"
NOT_FOUND = ApiError(404, "not_found", "This page doesn't exist.")
UNAVAILABLE = ApiError(503, "temporarily_unavailable", "This page is temporarily unavailable.")
OTHER_HOMES = 4


# ---------- schemas ----------


class HoldingPage(BaseModel):
    display_name: str
    brokerage_name: str
    style_preset: str
    contact: Contact


class SitePage(BaseModel):
    username: str
    state: Literal["live", "holding"]
    noindex: bool
    site: SiteContent | None
    holding: HoldingPage | None
    featured: list[ListingCard]
    listing_count: int
    last_modified: datetime | None


class ListingPage(BaseModel):
    username: str
    path: str
    status: Literal["published", "sold"]
    site_live: bool
    content: ListingContent
    contact: Contact
    other_homes: list[ListingCard]
    published_at: datetime | None
    last_modified: datetime | None


class ListingLookup(BaseModel):
    """Either the page, or `redirect_to` (permanent, 301) when an old address was used."""
    redirect_to: str | None = None
    page: ListingPage | None = None


class SitemapSite(BaseModel):
    username: str
    last_modified: datetime | None


class SitemapEntry(BaseModel):
    path: str
    last_modified: datetime | None


# ---------- helpers ----------


def _workspace(s: Session, username: str) -> Row:
    row = s.execute(
        text("""SELECT id, username, display_name, subscription_state, site_live, site_live_at
                FROM workspaces WHERE username = :u"""),
        {"u": normalize(username)},
    ).first()
    if row is None:
        raise NOT_FOUND
    if row.subscription_state == "offline":
        raise UNAVAILABLE
    return row


def _available(listing: Row, ws: Row) -> bool:
    """Trial listings go preview-only after their 60 days unless the workspace has subscribed."""
    expired = listing.trial_expires_at is not None and listing.trial_expires_at <= datetime.now(UTC)
    return not expired or ws.subscription_state == "active"


def _listings(s: Session, ws: Row) -> list[Row]:
    rows = s.execute(
        text("""SELECT id, status, live_slug, live, live_at, published_at, trial_expires_at FROM listings
                WHERE workspace_id = :w ORDER BY (status = 'sold'), published_at DESC NULLS LAST"""),
        {"w": ws.id},
    ).all()
    return [r for r in rows if _available(r, ws)]


def _card_image(live: dict) -> Image | None:
    if (live.get("hero") or {}).get("image"):
        return Image.model_validate(live["hero"]["image"])
    if live.get("gallery"):
        return Image.model_validate(live["gallery"][0])
    for walk in (live.get("walkthrough") or {}).values():
        frame = f"{walk['count']:04d}"
        return Image(id=UUID(int=0), url=walk["large"]["pattern"].replace("{n}", frame),
                     thumb_url=walk["small"]["pattern"].replace("{n}", frame),
                     width=walk["large"]["width"], height=walk["large"]["height"])
    return None


def _card(ws: Row, row: Row) -> ListingCard:
    live = row.live
    return ListingCard(
        id=row.id, path=f"/{ws.username}/{row.live_slug}", status=row.status, title=live.get("title", ""),
        location=live.get("location", ""), price_amount=live.get("price_amount"),
        price_currency=live.get("price_currency", "USD"), price_label=live.get("price_label", ""),
        bedrooms=live.get("bedrooms"), bathrooms=live.get("bathrooms"), area=live.get("area"),
        area_unit=live.get("area_unit", "sqft"), property_type=live.get("property_type", ""),
        experience_type=live.get("experience_type", "immersive"), image=_card_image(live),
        published_at=row.published_at,
    )


def _cached(response: Response) -> None:
    response.headers["Cache-Control"] = CACHE


# ---------- endpoints ----------


@router.get("/sites/{username}", response_model=SitePage)
def site(username: str, response: Response) -> SitePage:
    with public_session() as s:
        ws = _workspace(s, username)
        _cached(response)
        if ws.site_live is None:
            profile = s.execute(
                text("""SELECT brokerage_name, style_preset, contact_email, contact_phone, whatsapp, booking_url
                        FROM workspace_profiles WHERE workspace_id = :w"""),
                {"w": ws.id},
            ).first()
            holding = HoldingPage(
                display_name=ws.display_name, brokerage_name=profile.brokerage_name if profile else "",
                style_preset=profile.style_preset if profile else "noir",
                contact=Contact(email=profile.contact_email, phone=profile.contact_phone, whatsapp=profile.whatsapp,
                                booking_url=profile.booking_url) if profile else Contact(),
            )
            return SitePage(username=ws.username, state="holding", noindex=True, site=None, holding=holding,
                            featured=[], listing_count=0, last_modified=None)
        content = SiteContent.model_validate(ws.site_live)
        listings = _listings(s, ws)
        by_id = {r.id: r for r in listings if r.status == "published"}
        featured = [_card(ws, by_id[i]) for i in content.featured_listing_ids if i in by_id]
        stamps = [ws.site_live_at, *(r.live_at for r in listings)]
        return SitePage(username=ws.username, state="live", noindex=False, site=content, holding=None,
                        featured=featured, listing_count=len(listings),
                        last_modified=max(t for t in stamps if t is not None))


@router.get("/sites/{username}/listings", response_model=list[ListingCard])
def site_listings(username: str, response: Response,
                  status: Literal["published", "sold"] | None = None,
                  min_price: float | None = Query(default=None, ge=0),
                  max_price: float | None = Query(default=None, ge=0),
                  min_beds: int | None = Query(default=None, ge=0),
                  location: str | None = Query(default=None, max_length=80)) -> list[ListingCard]:
    """Every home on a live site (the Properties page), with simple filters."""
    with public_session() as s:
        ws = _workspace(s, username)
        if ws.site_live is None:
            raise NOT_FOUND
        cards = [_card(ws, r) for r in _listings(s, ws)]
    _cached(response)

    def keep(c: ListingCard) -> bool:
        if status and c.status != status:
            return False
        if min_price is not None and (c.price_amount is None or c.price_amount < min_price):
            return False
        if max_price is not None and (c.price_amount is None or c.price_amount > max_price):
            return False
        if min_beds is not None and (c.bedrooms is None or c.bedrooms < min_beds):
            return False
        return not location or location.strip().lower() in c.location.lower()

    return [c for c in cards if keep(c)]


@router.get("/sites/{username}/listings/{slug}", response_model=ListingLookup)
def listing(username: str, slug: str, response: Response) -> ListingLookup:
    with public_session() as s:
        ws = _workspace(s, username)
        row = s.execute(
            text("""SELECT id, status, live_slug, live, live_at, published_at, trial_expires_at FROM listings
                    WHERE workspace_id = :w AND live_slug = :s"""),
            {"w": ws.id, "s": slug.lower()},
        ).first()
        if row is None:
            moved = s.execute(
                text("""SELECT l.live_slug FROM listing_slug_history h JOIN listings l ON l.id = h.listing_id
                        WHERE h.workspace_id = :w AND h.slug = :s"""),
                {"w": ws.id, "s": slug.lower()},
            ).scalar_one_or_none()
            if moved is None or moved == slug.lower():
                raise NOT_FOUND
            _cached(response)
            return ListingLookup(redirect_to=f"/{ws.username}/{moved}")
        if not _available(row, ws):
            raise UNAVAILABLE
        content = ListingContent.model_validate(row.live)
        site_live = ws.site_live is not None
        contact = SiteContent.model_validate(ws.site_live).contact if site_live else content.contact
        others = []
        if row.status == "sold" and site_live:
            others = [_card(ws, r) for r in _listings(s, ws) if r.status == "published" and r.id != row.id][:OTHER_HOMES]
        _cached(response)
        return ListingLookup(page=ListingPage(
            username=ws.username, path=f"/{ws.username}/{row.live_slug}", status=row.status, site_live=site_live,
            content=content, contact=contact, other_homes=others, published_at=row.published_at,
            last_modified=row.live_at,
        ))


@router.get("/sitemaps", response_model=list[SitemapSite])
def sitemap_index(response: Response) -> list[SitemapSite]:
    """Realtors with anything public (live site or live listings), for the sitemap index."""
    with public_session() as s:
        rows = s.execute(text("""
            SELECT w.username, w.subscription_state, w.site_live_at,
                   (SELECT max(l.live_at) FROM listings l WHERE l.workspace_id = w.id
                      AND (l.trial_expires_at IS NULL OR l.trial_expires_at > now() OR w.subscription_state = 'active'))
                     AS listings_at
            FROM workspaces w WHERE w.subscription_state <> 'offline' ORDER BY w.username
        """)).all()
    _cached(response)
    out = []
    for r in rows:
        stamps = [t for t in (r.site_live_at, r.listings_at) if t is not None]
        if stamps:
            out.append(SitemapSite(username=r.username, last_modified=max(stamps)))
    return out


@router.get("/sitemaps/{username}", response_model=list[SitemapEntry])
def sitemap(username: str, response: Response) -> list[SitemapEntry]:
    with public_session() as s:
        ws = _workspace(s, username)
        listings = _listings(s, ws)
    entries = []
    if ws.site_live is not None:
        entries += [SitemapEntry(path=f"/{ws.username}{p}", last_modified=ws.site_live_at)
                    for p in ("", "/properties", "/about", "/contact")]
    entries += [SitemapEntry(path=f"/{ws.username}/{r.live_slug}", last_modified=r.live_at) for r in listings]
    _cached(response)
    return entries

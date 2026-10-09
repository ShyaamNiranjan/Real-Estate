"""Buyer enquiries (docs/SCOPE.md 6, 8.10, 9.5).

Public form → stored and emailed to the listing's agent and everyone allowed to see all
enquiries. The database decides who can read an enquiry (see 0007): the listing's agent, or
members with "see the whole team's enquiries".

Bot protection: a hidden field people never fill, a signed form token that must be a few seconds
old (bots post instantly), rate limits per IP and per workspace, and Cloudflare Turnstile when
configured. Bots get the same "sent" answer as people, so they learn nothing.
"""

import csv
import io
import time
from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import text

from app import email as mail
from app.config import get_settings
from app.db import public_session, tenant_session
from app.deps import Auth, client_ip, in_workspace
from app.errors import ApiError, ErrorResponse
from app.listings import _writable
from app.permissions import load_access
from app.ratelimit import Rule, enforce
from app.security import keyed, same
from app.usernames import normalize

public_router = APIRouter(prefix="/api/v1/public", tags=["public"],
                          responses={k: {"model": ErrorResponse} for k in (404, 422, 429)})
router = APIRouter(prefix="/api/v1/enquiries", tags=["enquiries"],
                   responses={k: {"model": ErrorResponse} for k in (401, 403, 404, 422)})

FORM_MIN_SECONDS = 3
FORM_MAX_SECONDS = 24 * 3600
ENQUIRY_IP = Rule("enquiry-ip", 5, 600)
ENQUIRY_IP_DAY = Rule("enquiry-ip-day", 20, 86400)
ENQUIRY_WORKSPACE = Rule("enquiry-workspace", 200, 86400)
CONSENT = "By sending this, you agree to be contacted by {agent} about this property."
CONSENT_SITE = "By sending this, you agree to be contacted by {agent}."
PAGE_SIZE = 50


# ---------- form token ----------


def form_token(workspace_id: UUID) -> str:
    issued = str(int(time.time()))
    return f"{issued}.{keyed('enquiry-form', f'{workspace_id}:{issued}')[:32]}"


def _token_ok(token: str, workspace_id: UUID) -> bool:
    issued, _, mac = token.partition(".")
    if not issued.isdigit() or not same(mac, keyed("enquiry-form", f"{workspace_id}:{issued}")[:32]):
        return False
    age = time.time() - int(issued)
    return FORM_MIN_SECONDS <= age <= FORM_MAX_SECONDS


def _turnstile_ok(token: str | None, ip: str) -> bool:
    secret = get_settings().turnstile_secret
    if not secret:
        return True
    if not token:
        return False
    try:
        r = httpx.post("https://challenges.cloudflare.com/turnstile/v0/siteverify",
                       data={"secret": secret, "response": token, "remoteip": ip}, timeout=5)
        return bool(r.json().get("success"))
    except (httpx.HTTPError, ValueError):
        return False


# ---------- schemas ----------


class EnquiryIn(BaseModel):
    username: str = Field(max_length=60)
    listing_slug: str | None = Field(default=None, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    phone: str = Field(default="", max_length=40)
    message: str = Field(default="", max_length=4000)
    consent: Literal[True]
    form_token: str = Field(max_length=80)
    website: str = Field(default="", max_length=200, description="Hidden field; must stay empty.")
    turnstile_token: str | None = Field(default=None, max_length=4096)


class Sent(BaseModel):
    status: Literal["sent"] = "sent"


class EnquiryOut(BaseModel):
    id: UUID
    listing_id: UUID | None
    listing_title: str | None
    agent_name: str | None
    name: str
    email: str
    phone: str
    message: str
    consent_text: str
    page_path: str
    status: Literal["new", "contacted", "closed"]
    created_at: datetime


class EnquiryPage(BaseModel):
    items: list[EnquiryOut]
    next_before: datetime | None
    counts: dict[str, int]


class EnquiryPatch(BaseModel):
    status: Literal["new", "contacted", "closed"]


# ---------- public form ----------


def _target(username: str, slug: str | None):
    """The workspace and (optionally) listing the form was on; only live pages accept enquiries."""
    with public_session() as s:
        ws = s.execute(text("SELECT id, username, display_name, subscription_state, site_live FROM workspaces "
                            "WHERE username = :u"), {"u": normalize(username)}).first()
        if ws is None or ws.subscription_state == "offline":
            raise ApiError(404, "not_found", "This page doesn't exist.")
        if slug is None:
            if ws.site_live is None:
                raise ApiError(404, "not_found", "This page doesn't exist.")
            return ws, None
        listing = s.execute(text("SELECT id, live, live_slug FROM listings WHERE workspace_id = :w AND live_slug = :s"),
                            {"w": ws.id, "s": slug.lower()}).first()
        if listing is None:
            raise ApiError(404, "not_found", "This page doesn't exist.")
        return ws, listing


@public_router.post("/enquiries", status_code=202, response_model=Sent)
def create_enquiry(body: EnquiryIn, request: Request) -> Sent:
    ip = client_ip(request)
    enforce((ENQUIRY_IP, ip), (ENQUIRY_IP_DAY, ip))
    ws, listing = _target(body.username, body.listing_slug)
    if body.website.strip() or not _token_ok(body.form_token, ws.id):
        return Sent()
    if not _turnstile_ok(body.turnstile_token, ip):
        raise ApiError(422, "verification_failed", "Please complete the check and try again.")
    enforce((ENQUIRY_WORKSPACE, str(ws.id)))

    with tenant_session(None, ws.id) as s:
        agent_member_id, agent_name, title = None, ws.display_name, None
        if listing is not None:
            row = s.execute(
                text("""SELECT l.title, l.live, coalesce(l.agent_member_id,
                               (SELECT m.id FROM memberships m WHERE m.workspace_id = l.workspace_id
                                AND m.user_id = l.created_by AND m.removed_at IS NULL)) AS member_id
                        FROM listings l WHERE l.id = :id"""),
                {"id": listing.id},
            ).one()
            agent_member_id = row.member_id
            title = (row.live or {}).get("title") or row.title
            agent_name = ((row.live or {}).get("agent") or {}).get("name") or ws.display_name
        consent = (CONSENT if listing is not None else CONSENT_SITE).format(agent=agent_name)
        enquiry_id = uuid4()
        path = f"/{ws.username}/{listing.live_slug}" if listing is not None else f"/{ws.username}/contact"
        s.execute(
            text("""INSERT INTO enquiries (id, workspace_id, listing_id, agent_member_id, name, email, phone, message,
                                           consent_text, consent_version, page_path)
                    VALUES (:id, :w, :l, :a, :n, :e, :p, :m, :c, :v, :path)"""),
            {"id": enquiry_id, "w": ws.id, "l": listing.id if listing is not None else None, "a": agent_member_id,
             "n": body.name.strip(), "e": body.email, "p": body.phone.strip(), "m": body.message.strip(),
             "c": consent, "v": get_settings().consent_version, "path": path},
        )
        recipients = s.execute(text("SELECT email FROM enquiry_recipients(:w, :a)"),
                               {"w": ws.id, "a": agent_member_id}).scalars().all()

    about = title or "your website"
    lines = [f"New enquiry about {about}", "", f"Name: {body.name.strip()}", f"Email: {body.email}"]
    if body.phone.strip():
        lines.append(f"Phone: {body.phone.strip()}")
    if body.message.strip():
        lines += ["", body.message.strip()]
    lines += ["", "Reply to this email to answer them directly. All enquiries are in your Studio."]
    mail.send(*(mail.Email(to=r, subject=f"New enquiry: {about}", text="\n".join(lines), reply_to=body.email)
                for r in recipients))
    return Sent()


# ---------- Studio ----------


def _require_view(s, auth: Auth):
    access = load_access(s, auth.user_id, auth.workspace_id)
    if not (access.has("enquiries.view_all") or access.has("enquiries.view_own")):
        raise ApiError(403, "permission_denied", "Your role doesn't include enquiries.")
    return access


_SELECT = """SELECT e.*, l.title AS listing_title, coalesce(nullif(u.display_name, ''), u.email) AS agent_name
             FROM enquiries e
             LEFT JOIN listings l ON l.id = e.listing_id
             LEFT JOIN memberships m ON m.id = e.agent_member_id
             LEFT JOIN users u ON u.id = m.user_id"""


def _out(row) -> EnquiryOut:
    return EnquiryOut(id=row.id, listing_id=row.listing_id, listing_title=row.listing_title, agent_name=row.agent_name,
                      name=row.name, email=row.email, phone=row.phone, message=row.message,
                      consent_text=row.consent_text, page_path=row.page_path, status=row.status,
                      created_at=row.created_at)


@router.get("", response_model=EnquiryPage)
def list_enquiries(status: Literal["new", "contacted", "closed"] | None = None, listing_id: UUID | None = None,
                   q: str | None = Query(default=None, max_length=100), before: datetime | None = None,
                   auth: Auth = Depends(in_workspace)) -> EnquiryPage:
    """Newest first, 50 at a time (pass `next_before` as `before` for more). Only what this member may see."""
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        _require_view(s, auth)
        where, params = ["TRUE"], {"limit": PAGE_SIZE + 1}
        if status:
            where.append("e.status = :status")
            params["status"] = status
        if listing_id:
            where.append("e.listing_id = :listing")
            params["listing"] = listing_id
        if q and q.strip():
            where.append("(e.name ILIKE :q OR e.email ILIKE :q OR e.message ILIKE :q)")
            params["q"] = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        if before:
            where.append("e.created_at < :before")
            params["before"] = before
        rows = s.execute(text(f"{_SELECT} WHERE {' AND '.join(where)} ORDER BY e.created_at DESC LIMIT :limit"),
                         params).all()
        counts = dict(s.execute(text("SELECT status, count(*) FROM enquiries GROUP BY status")).all())
    more = len(rows) > PAGE_SIZE
    rows = rows[:PAGE_SIZE]
    return EnquiryPage(items=[_out(r) for r in rows], next_before=rows[-1].created_at if more else None,
                       counts={k: counts.get(k, 0) for k in ("new", "contacted", "closed")})


def _sheet_safe(value) -> str:
    """Stops spreadsheet formula injection (a buyer typing =HYPERLINK(...) into the form)."""
    value = "" if value is None else str(value)
    return "'" + value if value[:1] in ("=", "+", "-", "@", "\t", "\r") else value


@router.get("/export", response_class=Response,
            responses={200: {"content": {"text/csv": {}}, "description": "CSV of the enquiries this member can see."}})
def export_enquiries(auth: Auth = Depends(in_workspace)) -> Response:
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        access = _require_view(s, auth)
        access.require("enquiries.export")
        rows = s.execute(text(f"{_SELECT} ORDER BY e.created_at DESC")).all()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Received", "Name", "Email", "Phone", "Message", "Listing", "Agent", "Status", "Page"])
    for r in rows:
        writer.writerow([_sheet_safe(v) for v in (r.created_at.isoformat(timespec="minutes"), r.name, r.email, r.phone,
                                                  r.message, r.listing_title, r.agent_name, r.status, r.page_path)])
    return Response("\ufeff" + buffer.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="enquiries.csv"'})


@router.get("/{enquiry_id}", response_model=EnquiryOut)
def get_enquiry(enquiry_id: UUID, auth: Auth = Depends(in_workspace)) -> EnquiryOut:
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        _require_view(s, auth)
        row = s.execute(text(f"{_SELECT} WHERE e.id = :id"), {"id": enquiry_id}).first()
        if row is None:
            raise ApiError(404, "not_found", "That enquiry doesn't exist.")
        return _out(row)


@router.patch("/{enquiry_id}", response_model=EnquiryOut)
def update_enquiry(enquiry_id: UUID, body: EnquiryPatch, auth: Auth = Depends(in_workspace)) -> EnquiryOut:
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        _require_view(s, auth)
        _writable(s, auth)
        updated = s.execute(text("UPDATE enquiries SET status = :st, updated_at = now() WHERE id = :id RETURNING id"),
                            {"st": body.status, "id": enquiry_id}).first()
        if updated is None:
            raise ApiError(404, "not_found", "That enquiry doesn't exist.")
        return _out(s.execute(text(f"{_SELECT} WHERE e.id = :id"), {"id": enquiry_id}).one())

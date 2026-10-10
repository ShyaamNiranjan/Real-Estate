"""Sign in with Google: authorization code flow with state, PKCE and nonce.

The ID token comes straight from Google's token endpoint over TLS, which OpenID Connect Core
3.1.3.7 accepts in place of signature checking; issuer, audience, expiry and nonce are still
verified.
"""

import base64
import hashlib
import json
import secrets
import time
from urllib.parse import urlencode
from uuid import uuid4

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import text

from app.auth import ensure_workspace, lookup_user, record_acceptance, start_session
from app.config import get_settings
from app.db import tenant_session
from app.deps import client_ip
from app.ratelimit import Rule, enforce
from app.security import keyed, same

router = APIRouter(prefix="/api/v1/auth/google", tags=["auth"])

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
ISSUERS = {"accounts.google.com", "https://accounts.google.com"}
FLOW_COOKIE = "sw_oauth"
GOOGLE_IP = Rule("google-ip", 30, 600)


class GoogleError(Exception):
    pass


def _configured() -> bool:
    s = get_settings()
    return bool(s.google_client_id and s.google_client_secret)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _fail(reason: str) -> RedirectResponse:
    response = RedirectResponse(f"{get_settings().app_url}/login?error={reason}", status_code=303)
    response.delete_cookie(FLOW_COOKIE, path="/api/v1/auth/google")
    return response


@router.get("/start", include_in_schema=True, status_code=303)
def start(request: Request) -> RedirectResponse:
    if not _configured():
        return _fail("google_unavailable")
    enforce((GOOGLE_IP, client_ip(request)))
    settings = get_settings()
    state, verifier, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(48), secrets.token_urlsafe(24)
    payload = f"{state}.{verifier}.{nonce}"
    query = urlencode({
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        "code_challenge": _b64url(hashlib.sha256(verifier.encode()).digest()),
        "code_challenge_method": "S256",
        "prompt": "select_account",
    })
    response = RedirectResponse(f"{AUTHORIZE_URL}?{query}", status_code=303)
    response.set_cookie(FLOW_COOKIE, f"{payload}.{keyed('oauth', payload)}", max_age=600,
                        path="/api/v1/auth/google", secure=settings.cookie_secure, httponly=True, samesite="lax")
    return response


def exchange_code(code: str, verifier: str) -> dict:
    settings = get_settings()
    reply = httpx.post(TOKEN_URL, timeout=10, data={
        "code": code,
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "redirect_uri": settings.google_redirect_uri,
        "grant_type": "authorization_code",
        "code_verifier": verifier,
    })
    if reply.status_code != 200 or "id_token" not in reply.json():
        raise GoogleError("token exchange failed")
    segment = reply.json()["id_token"].split(".")[1]
    return json.loads(base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)))


def check_claims(claims: dict, nonce: str) -> None:
    settings = get_settings()
    if claims.get("iss") not in ISSUERS or claims.get("aud") != settings.google_client_id:
        raise GoogleError("wrong issuer or audience")
    if claims.get("exp", 0) < time.time() or not same(str(claims.get("nonce", "")), nonce):
        raise GoogleError("expired or replayed")
    if claims.get("email_verified") is not True or not claims.get("email") or not claims.get("sub"):
        raise GoogleError("email not verified by Google")


@router.get("/callback", include_in_schema=False)
def callback(request: Request, code: str = "", state: str = "", error: str = "") -> RedirectResponse:
    if error or not code or not _configured():
        return _fail("google_cancelled" if error else "google_failed")
    raw = request.cookies.get(FLOW_COOKIE, "")
    parts = raw.split(".")
    if len(parts) != 4 or not same(parts[3], keyed("oauth", ".".join(parts[:3]))) or not same(parts[0], state):
        return _fail("google_failed")
    _, verifier, nonce, _ = parts
    try:
        claims = exchange_code(code, verifier)
        check_claims(claims, nonce)
    except (GoogleError, httpx.HTTPError, ValueError):
        return _fail("google_failed")

    user_id = sign_in_google_user(request, claims)
    response = RedirectResponse(f"{get_settings().app_url}/studio", status_code=303)
    response.delete_cookie(FLOW_COOKIE, path="/api/v1/auth/google")
    start_session(response, request, user_id)
    return response


def sign_in_google_user(request: Request, claims: dict):
    sub, email = claims["sub"], claims["email"]
    with tenant_session() as s:
        by_sub = s.execute(text("SELECT * FROM auth_user_by_google_sub(:s)"), {"s": sub}).first()
    if by_sub:
        return by_sub.user_id

    existing = lookup_user(email)
    if existing:
        with tenant_session(existing.user_id) as s:
            if not existing.email_verified_at:
                # Someone registered this email without ever proving they own it. Google just
                # proved the real owner is here, so the unproven password must not survive.
                s.execute(text("DELETE FROM user_credentials WHERE user_id = :u"), {"u": existing.user_id})
            s.execute(
                text("""UPDATE users SET google_sub = :s, email_verified_at = coalesce(email_verified_at, now()),
                               avatar_url = coalesce(avatar_url, :a) WHERE id = :u"""),
                {"s": sub, "a": claims.get("picture"), "u": existing.user_id},
            )
        return existing.user_id

    user_id = uuid4()
    with tenant_session(user_id) as s:
        s.execute(
            text("""INSERT INTO users (id, email, google_sub, display_name, avatar_url, email_verified_at, signup_source)
                    VALUES (:u, :e, :s, :n, :a, now(), 'google')"""),
            {"u": user_id, "e": email, "s": sub, "n": (claims.get("name") or "")[:80], "a": claims.get("picture")},
        )
        record_acceptance(s, user_id, "google", request)
        ensure_workspace(s, user_id)
    return user_id

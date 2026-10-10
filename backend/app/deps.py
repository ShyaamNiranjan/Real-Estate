from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy import text

from app.config import get_settings
from app.db import tenant_session
from app.errors import ApiError
from app.security import csrf_token, same, token_hash

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def cookie_names() -> tuple[str, str]:
    prefix = "__Host-" if get_settings().cookie_secure else ""
    return f"{prefix}sw_session", f"{prefix}sw_csrf"


@dataclass(frozen=True)
class Auth:
    session_id: UUID
    user_id: UUID
    workspace_id: UUID | None
    read_only: bool = False


def current_auth(request: Request) -> Auth:
    token = request.cookies.get(cookie_names()[0])
    if not token:
        raise ApiError(401, "not_signed_in", "Please sign in.")
    with tenant_session() as s:
        row = s.execute(
            text("SELECT * FROM auth_session_lookup(:h)"), {"h": token_hash(token)}
        ).first()
    if row is None:
        raise ApiError(401, "not_signed_in", "Your session has ended. Please sign in again.")
    return Auth(row.session_id, row.user_id, row.workspace_id, row.read_only)


def signed_in(request: Request, auth: Auth = Depends(current_auth)) -> Auth:
    """Signed-in user; state-changing requests must also carry the X-CSRF-Token header. Staff
    "log in as them" sessions are read-only."""
    if request.method not in SAFE_METHODS:
        header = request.headers.get("X-CSRF-Token", "")
        if not header or not same(header, csrf_token(auth.session_id)):
            raise ApiError(403, "csrf_failed", "This request couldn't be verified. Refresh the page and try again.")
        if auth.read_only and request.url.path != "/api/v1/auth/logout":
            raise ApiError(403, "read_only_session", "This is a read-only staff view. Nothing can be changed.")
    return auth


def in_workspace(request: Request, auth: Auth = Depends(signed_in)) -> Auth:
    if auth.workspace_id is None:
        raise ApiError(409, "no_workspace", "You're not in a workspace right now.")
    if request.method not in SAFE_METHODS:
        with tenant_session(auth.user_id, auth.workspace_id) as s:
            frozen = s.execute(text("SELECT frozen_at FROM workspaces WHERE id = :w"),
                               {"w": auth.workspace_id}).scalar()
        if frozen is not None:
            raise ApiError(403, "account_frozen", "This account has been suspended. Contact support@scrollwalk.com.")
    return auth


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"

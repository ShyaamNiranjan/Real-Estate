"""Sign-up, sign-in, email codes, sessions (docs/SCOPE.md sections 8.1 and 9.2).

Unauthenticated endpoints never reveal whether an email has an account: sign-up, resend and
forgot-password always answer 202, and a wrong email costs the same time as a wrong password.
"""

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import Row, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import email as mail
from app.config import get_settings
from app.db import set_context, tenant_session
from app.deps import Auth, client_ip, cookie_names, signed_in
from app.errors import ApiError, ErrorResponse
from app.ratelimit import Rule, enforce
from app.security import (
    code_hash,
    csrf_token,
    hash_password,
    keyed,
    needs_rehash,
    new_code,
    new_token,
    same,
    token_hash,
    verify_password,
)

router = APIRouter(
    prefix="/api/v1/auth",
    tags=["auth"],
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
    },
)

CODE_TTL = timedelta(minutes=10)
CODE_RESEND_AFTER = timedelta(seconds=30)
CODE_MAX_ATTEMPTS = 5

SIGNUP_IP = Rule("signup-ip", 10, 3600)
SIGNUP_EMAIL = Rule("signup-email", 5, 3600)
LOGIN_IP = Rule("login-ip", 30, 600)
LOGIN_EMAIL = Rule("login-email", 10, 600)
CODE_SEND_IP = Rule("code-send-ip", 20, 3600)
CODE_SEND_EMAIL = Rule("code-send-email", 6, 3600)
CODE_CHECK_IP = Rule("code-check-ip", 30, 600)
CODE_CHECK_EMAIL = Rule("code-check-email", 10, 600)

Password = Field(min_length=8, max_length=128)
Code = Field(pattern=r"^\d{6}$")


# ---------- schemas ----------


class SignupIn(BaseModel):
    email: EmailStr
    password: str = Password
    display_name: str = Field(default="", max_length=80)
    accept_terms: Literal[True]


class EmailIn(BaseModel):
    email: EmailStr


class ResendIn(BaseModel):
    email: EmailStr
    purpose: Literal["verify", "reset"]


class VerifyIn(BaseModel):
    email: EmailStr
    code: str = Code


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(max_length=128)


class ResetIn(BaseModel):
    email: EmailStr
    code: str = Code
    password: str = Password


class EmailChangeIn(BaseModel):
    new_email: EmailStr
    password: str = Field(max_length=128)


class CodeIn(BaseModel):
    code: str = Code


class Accepted(BaseModel):
    status: Literal["code_sent"] = "code_sent"


class MeUser(BaseModel):
    id: UUID
    email: str
    display_name: str
    avatar_url: str | None
    email_verified: bool
    has_password: bool


class MeWorkspace(BaseModel):
    id: UUID
    username: str | None
    display_name: str
    is_admin: bool


class Me(BaseModel):
    user: MeUser
    workspaces: list[MeWorkspace]
    current_workspace_id: UUID | None
    csrf_token: str


# ---------- helpers ----------


def _lookup(s: Session, email: str) -> Row | None:
    return s.execute(text("SELECT * FROM auth_user_by_email(:e)"), {"e": email}).first()


def lookup_user(email: str) -> Row | None:
    with tenant_session() as s:
        return _lookup(s, email)


def _ip_hash(request: Request) -> str:
    return keyed("ip", client_ip(request))


def set_password(s: Session, user_id: UUID, password_hash: str) -> None:
    updated = s.execute(
        text("UPDATE user_credentials SET password_hash = :h, updated_at = now() WHERE user_id = :u"),
        {"h": password_hash, "u": user_id},
    ).rowcount
    if not updated:
        s.execute(
            text("INSERT INTO user_credentials (user_id, password_hash) VALUES (:u, :h)"),
            {"u": user_id, "h": password_hash},
        )


def record_acceptance(s: Session, user_id: UUID, method: str, request: Request) -> None:
    settings = get_settings()
    for document, version in (("terms", settings.terms_version), ("privacy", settings.privacy_version)):
        s.execute(
            text("""INSERT INTO legal_acceptances (user_id, document, version, method, ip_hash)
                    VALUES (:u, :d, :v, :m, :ip)"""),
            {"u": user_id, "d": document, "v": version, "m": method, "ip": _ip_hash(request)},
        )


def issue_code(
    s: Session, user_id: UUID, purpose: str, send_to: str, target_email: str | None = None
) -> mail.Email | None:
    """Replaces any open code for this purpose. Returns the email to send after commit, or None
    inside the 30-second resend cooldown."""
    last = s.execute(
        text("SELECT created_at FROM email_codes WHERE user_id = :u AND purpose = :p ORDER BY created_at DESC LIMIT 1"),
        {"u": user_id, "p": purpose},
    ).scalar()
    if last and datetime.now(UTC) - last < CODE_RESEND_AFTER:
        return None
    s.execute(
        text("UPDATE email_codes SET consumed_at = now() WHERE user_id = :u AND purpose = :p AND consumed_at IS NULL"),
        {"u": user_id, "p": purpose},
    )
    code_id, code = uuid4(), new_code()
    s.execute(
        text("""INSERT INTO email_codes (id, user_id, purpose, code_hash, target_email, expires_at)
                VALUES (:id, :u, :p, :h, :t, now() + :ttl)"""),
        {"id": code_id, "u": user_id, "p": purpose, "h": code_hash(code_id, code), "t": target_email, "ttl": CODE_TTL},
    )
    return mail.code_email(send_to, purpose, code)


def check_code(s: Session, user_id: UUID, purpose: str, code: str) -> Row | None:
    """Consumes the code if it matches. A wrong guess is recorded, so the caller must let the
    transaction commit before raising."""
    row = s.execute(
        text("""SELECT id, code_hash, attempts, target_email FROM email_codes
                WHERE user_id = :u AND purpose = :p AND consumed_at IS NULL AND expires_at > now()
                ORDER BY created_at DESC LIMIT 1 FOR UPDATE"""),
        {"u": user_id, "p": purpose},
    ).first()
    if row is None or row.attempts >= CODE_MAX_ATTEMPTS:
        return None
    if same(bytes(row.code_hash), code_hash(row.id, code)):
        s.execute(text("UPDATE email_codes SET consumed_at = now() WHERE id = :id"), {"id": row.id})
        return row
    s.execute(text("UPDATE email_codes SET attempts = attempts + 1 WHERE id = :id"), {"id": row.id})
    return None


def ensure_workspace(s: Session, user_id: UUID) -> UUID:
    """The user's workspace: the one they administer first, else any active membership, else a
    new personal workspace with them as Admin."""
    existing = s.execute(
        text("""SELECT workspace_id FROM memberships WHERE user_id = :u AND removed_at IS NULL
                ORDER BY is_admin DESC, joined_at LIMIT 1"""),
        {"u": user_id},
    ).scalar()
    if existing:
        return existing
    workspace_id = uuid4()
    set_context(s, user_id, workspace_id)
    s.execute(text("INSERT INTO workspaces (id) VALUES (:w)"), {"w": workspace_id})
    s.execute(
        text("INSERT INTO memberships (workspace_id, user_id, is_admin) VALUES (:w, :u, true)"),
        {"w": workspace_id, "u": user_id},
    )
    set_context(s, user_id, None)
    return workspace_id


def start_session(response: Response, request: Request, user_id: UUID) -> Auth:
    settings = get_settings()
    token, session_id = new_token(), uuid4()
    with tenant_session(user_id) as s:
        workspace_id = ensure_workspace(s, user_id)
        s.execute(
            text("""INSERT INTO sessions (id, token_hash, user_id, workspace_id, expires_at, ip_hash, user_agent)
                    VALUES (:id, :h, :u, :w, now() + :ttl, :ip, :ua)"""),
            {
                "id": session_id, "h": token_hash(token), "u": user_id, "w": workspace_id,
                "ttl": timedelta(days=settings.session_days), "ip": _ip_hash(request),
                "ua": request.headers.get("user-agent", "")[:300],
            },
        )
        s.execute(text("UPDATE users SET last_login_at = now() WHERE id = :u"), {"u": user_id})
    session_cookie, csrf_cookie = cookie_names()
    max_age = settings.session_days * 86400
    response.set_cookie(session_cookie, token, max_age=max_age, path="/", secure=settings.cookie_secure,
                        httponly=True, samesite="lax")
    response.set_cookie(csrf_cookie, csrf_token(session_id), max_age=max_age, path="/",
                        secure=settings.cookie_secure, httponly=False, samesite="lax")
    return Auth(session_id, user_id, workspace_id)


def clear_cookies(response: Response) -> None:
    settings = get_settings()
    for name in cookie_names():
        response.delete_cookie(name, path="/", secure=settings.cookie_secure, samesite="lax")


def build_me(auth: Auth) -> Me:
    with tenant_session(auth.user_id) as s:
        user = s.execute(
            text("""SELECT id, email, display_name, avatar_url, email_verified_at,
                           EXISTS (SELECT 1 FROM user_credentials c WHERE c.user_id = users.id) AS has_password
                    FROM users WHERE id = :u"""),
            {"u": auth.user_id},
        ).one()
        workspaces = s.execute(
            text("""SELECT w.id, w.username, w.display_name, m.is_admin
                    FROM memberships m JOIN workspaces w ON w.id = m.workspace_id
                    WHERE m.user_id = :u AND m.removed_at IS NULL AND w.deleted_at IS NULL
                    ORDER BY m.is_admin DESC, m.joined_at"""),
            {"u": auth.user_id},
        ).all()
    return Me(
        user=MeUser(
            id=user.id, email=user.email, display_name=user.display_name, avatar_url=user.avatar_url,
            email_verified=user.email_verified_at is not None, has_password=user.has_password,
        ),
        workspaces=[MeWorkspace(id=w.id, username=w.username, display_name=w.display_name, is_admin=w.is_admin)
                    for w in workspaces],
        current_workspace_id=auth.workspace_id,
        csrf_token=csrf_token(auth.session_id),
    )


INVALID_CODE = ApiError(400, "invalid_code", "That code isn't right or has expired. Check the email or send a new code.")


# ---------- endpoints ----------


@router.post("/signup", status_code=202, response_model=Accepted)
def signup(body: SignupIn, request: Request) -> Accepted:
    enforce((SIGNUP_IP, client_ip(request)), (SIGNUP_EMAIL, body.email))
    existing = lookup_user(body.email)
    outgoing: mail.Email | None
    if existing and existing.email_verified_at:
        outgoing = mail.existing_account_email(body.email)
    else:
        # A never-verified account can be claimed again; the inbox owner wins at verification.
        user_id = existing.user_id if existing else uuid4()
        password_hash = hash_password(body.password)
        try:
            with tenant_session(user_id) as s:
                if existing:
                    s.execute(text("UPDATE users SET display_name = :n WHERE id = :u"),
                              {"n": body.display_name.strip(), "u": user_id})
                else:
                    s.execute(text("INSERT INTO users (id, email, display_name) VALUES (:u, :e, :n)"),
                              {"u": user_id, "e": body.email, "n": body.display_name.strip()})
                set_password(s, user_id, password_hash)
                record_acceptance(s, user_id, "signup", request)
                outgoing = issue_code(s, user_id, "verify", body.email)
        except IntegrityError:
            outgoing = None
    if outgoing:
        mail.send(outgoing)
    return Accepted()


@router.post("/verify", response_model=Me)
def verify(body: VerifyIn, request: Request, response: Response) -> Me:
    enforce((CODE_CHECK_IP, client_ip(request)), (CODE_CHECK_EMAIL, body.email))
    user = lookup_user(body.email)
    if user is None:
        raise INVALID_CODE
    with tenant_session(user.user_id) as s:
        ok = check_code(s, user.user_id, "verify", body.code) is not None
        if ok:
            s.execute(text("UPDATE users SET email_verified_at = coalesce(email_verified_at, now()) WHERE id = :u"),
                      {"u": user.user_id})
    if not ok:
        raise INVALID_CODE
    return build_me(start_session(response, request, user.user_id))


@router.post("/resend", status_code=202, response_model=Accepted)
def resend(body: ResendIn, request: Request) -> Accepted:
    enforce((CODE_SEND_IP, client_ip(request)), (CODE_SEND_EMAIL, body.email))
    user = lookup_user(body.email)
    outgoing = None
    if user and not (body.purpose == "verify" and user.email_verified_at):
        with tenant_session(user.user_id) as s:
            outgoing = issue_code(s, user.user_id, body.purpose, body.email)
    if outgoing:
        mail.send(outgoing)
    return Accepted()


@router.post("/login", response_model=Me)
def login(body: LoginIn, request: Request, response: Response) -> Me:
    enforce((LOGIN_IP, client_ip(request)), (LOGIN_EMAIL, body.email))
    user = lookup_user(body.email)
    if not verify_password(user.password_hash if user else None, body.password):
        raise ApiError(401, "invalid_credentials", "That email and password don't match.")
    if not user.email_verified_at:
        with tenant_session(user.user_id) as s:
            outgoing = issue_code(s, user.user_id, "verify", body.email)
        if outgoing:
            mail.send(outgoing)
        raise ApiError(403, "email_not_verified", "Confirm your email first. We've sent you a new code.")
    if needs_rehash(user.password_hash):
        with tenant_session(user.user_id) as s:
            set_password(s, user.user_id, hash_password(body.password))
    return build_me(start_session(response, request, user.user_id))


@router.post("/password/forgot", status_code=202, response_model=Accepted)
def forgot_password(body: EmailIn, request: Request) -> Accepted:
    enforce((CODE_SEND_IP, client_ip(request)), (CODE_SEND_EMAIL, body.email))
    user = lookup_user(body.email)
    outgoing = None
    if user:
        with tenant_session(user.user_id) as s:
            outgoing = issue_code(s, user.user_id, "reset", body.email)
    if outgoing:
        mail.send(outgoing)
    return Accepted()


@router.post("/password/reset", response_model=Me)
def reset_password(body: ResetIn, request: Request, response: Response) -> Me:
    enforce((CODE_CHECK_IP, client_ip(request)), (CODE_CHECK_EMAIL, body.email))
    user = lookup_user(body.email)
    if user is None:
        raise INVALID_CODE
    password_hash = hash_password(body.password)
    with tenant_session(user.user_id) as s:
        ok = check_code(s, user.user_id, "reset", body.code) is not None
        if ok:
            set_password(s, user.user_id, password_hash)
            s.execute(text("UPDATE users SET email_verified_at = coalesce(email_verified_at, now()) WHERE id = :u"),
                      {"u": user.user_id})
            s.execute(text("UPDATE sessions SET revoked_at = now() WHERE user_id = :u AND revoked_at IS NULL"),
                      {"u": user.user_id})
    if not ok:
        raise INVALID_CODE
    return build_me(start_session(response, request, user.user_id))


@router.get("/me", response_model=Me)
def me(auth: Auth = Depends(signed_in)) -> Me:
    return build_me(auth)


@router.post("/logout", status_code=204)
def logout(response: Response, auth: Auth = Depends(signed_in)) -> Response:
    with tenant_session(auth.user_id) as s:
        s.execute(text("UPDATE sessions SET revoked_at = now() WHERE id = :id"), {"id": auth.session_id})
    response.status_code = 204
    clear_cookies(response)
    return response


@router.post("/logout-all", status_code=204)
def logout_everywhere(response: Response, auth: Auth = Depends(signed_in)) -> Response:
    with tenant_session(auth.user_id) as s:
        s.execute(text("UPDATE sessions SET revoked_at = now() WHERE user_id = :u AND revoked_at IS NULL"),
                  {"u": auth.user_id})
    response.status_code = 204
    clear_cookies(response)
    return response


@router.post("/email/change", status_code=202, response_model=Accepted)
def change_email(body: EmailChangeIn, request: Request, auth: Auth = Depends(signed_in)) -> Accepted:
    enforce((CODE_SEND_IP, client_ip(request)), (CODE_SEND_EMAIL, str(auth.user_id)))
    with tenant_session(auth.user_id) as s:
        current = s.execute(text("SELECT email FROM users WHERE id = :u"), {"u": auth.user_id}).scalar_one()
        user = _lookup(s, current)
    if not verify_password(user.password_hash, body.password):
        raise ApiError(401, "invalid_credentials", "That password isn't right.")
    if lookup_user(body.new_email):
        raise ApiError(409, "email_taken", "That email already has a Scrollwalk account.")
    with tenant_session(auth.user_id) as s:
        outgoing = issue_code(s, auth.user_id, "email_change", body.new_email, target_email=body.new_email)
    if outgoing:
        mail.send(outgoing)
    return Accepted()


@router.post("/email/confirm", response_model=Me)
def confirm_email_change(body: CodeIn, request: Request, auth: Auth = Depends(signed_in)) -> Me:
    enforce((CODE_CHECK_IP, client_ip(request)), (CODE_CHECK_EMAIL, str(auth.user_id)))
    old_email = None
    try:
        with tenant_session(auth.user_id) as s:
            row = check_code(s, auth.user_id, "email_change", body.code)
            if row:
                old_email = s.execute(text("SELECT email FROM users WHERE id = :u"), {"u": auth.user_id}).scalar_one()
                s.execute(text("UPDATE users SET email = :e, email_verified_at = now() WHERE id = :u"),
                          {"e": row.target_email, "u": auth.user_id})
    except IntegrityError:
        raise ApiError(409, "email_taken", "That email already has a Scrollwalk account.")
    if row is None:
        raise INVALID_CODE
    mail.send(mail.email_changed_notice(old_email, row.target_email))
    return build_me(auth)

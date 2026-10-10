"""Super-Admin staff: sign-in with mandatory two-factor, staff accounts and roles, audit log
(docs/SCOPE.md 12, 9.6).

Staff are a separate set of accounts with their own cookie; customer sessions never grant staff
access and staff sessions never touch customer endpoints. Every staff action is written to the
append-only audit log in the same transaction as the action itself.
"""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import email as mail
from app import totp
from app.config import get_settings
from app.db import hq_session
from app.deps import SAFE_METHODS, client_ip
from app.errors import ApiError, ErrorResponse
from app.ratelimit import Rule, enforce
from app.security import hash_password, keyed, new_token, same, token_hash, verify_password

router = APIRouter(
    prefix="/api/v1/hq",
    tags=["hq"],
    responses={k: {"model": ErrorResponse} for k in (400, 401, 403, 404, 409, 422, 429)},
)

STAFF_PERMISSIONS: dict[str, str] = {
    "customers.view": "View customers and open their workspace read-only",
    "customers.impersonate": "Log in as a customer (typed reason, audited)",
    "customers.manage": "Extend trials, give or change plans, freeze accounts",
    "billing.refund": "Issue refunds",
    "revenue.view": "See revenue and profit",
    "content.moderate": "Handle reports and take down listings",
    "trials.manage": "Create and revoke trial invites",
    "pricing.edit": "Edit plans and pricing",
    "announcements.send": "Send announcements",
    "audit.view": "See the audit log",
}

SETUP_TTL = timedelta(hours=72)
LOGIN_IP = Rule("hq-login-ip", 10, 600)
LOGIN_EMAIL = Rule("hq-login-email", 5, 600)
SETUP_IP = Rule("hq-setup-ip", 10, 600)
Code = Field(pattern=r"^\d{6}$")


# ---------- the signed-in staff member ----------


@dataclass(frozen=True)
class Staff:
    session_id: UUID
    staff_id: UUID
    email: str
    is_super: bool
    permissions: frozenset[str]
    ip_hash: str

    def has(self, permission: str) -> bool:
        return self.is_super or permission in self.permissions

    def require(self, permission: str) -> None:
        if not self.has(permission):
            raise ApiError(403, "staff_permission_denied", "Your staff role doesn't allow this.")

    def require_super(self) -> None:
        if not self.is_super:
            raise ApiError(403, "super_admin_only", "Only the Super-Admin can do this.")


def staff_cookie_names() -> tuple[str, str]:
    prefix = "__Host-" if get_settings().cookie_secure else ""
    return f"{prefix}sw_staff", f"{prefix}sw_staff_csrf"


def staff_csrf(session_id: UUID) -> str:
    return keyed("staff-csrf", str(session_id))


def _ip_hash(request: Request) -> str:
    return keyed("ip", client_ip(request))


def current_staff(request: Request) -> Staff:
    token = request.cookies.get(staff_cookie_names()[0])
    if not token:
        raise ApiError(401, "staff_not_signed_in", "Please sign in.")
    settings = get_settings()
    with hq_session() as s:
        row = s.execute(
            text("""UPDATE staff_sessions ss SET last_seen_at = now()
                    FROM staff st
                    WHERE ss.token_hash = :h AND st.id = ss.staff_id AND ss.revoked_at IS NULL
                      AND ss.expires_at > now() AND ss.last_seen_at > now() - :idle
                      AND st.disabled_at IS NULL AND st.totp_enabled_at IS NOT NULL
                    RETURNING ss.id, st.id AS staff_id, st.email, st.is_super, st.role_id"""),
            {"h": token_hash(token), "idle": timedelta(minutes=settings.staff_idle_minutes)},
        ).first()
        if row is None:
            raise ApiError(401, "staff_not_signed_in", "Your session has ended. Please sign in again.")
        perms = s.execute(text("SELECT permission FROM staff_role_permissions WHERE role_id = :r"),
                          {"r": row.role_id}).scalars().all() if row.role_id else []
    if request.method not in SAFE_METHODS:
        header = request.headers.get("X-CSRF-Token", "")
        if not header or not same(header, staff_csrf(row.id)):
            raise ApiError(403, "csrf_failed", "This request couldn't be verified. Refresh the page and try again.")
    return Staff(row.id, row.staff_id, row.email, row.is_super, frozenset(perms) & STAFF_PERMISSIONS.keys(),
                 _ip_hash(request))


def audit(s: Session, staff: Staff | None, action: str, *, workspace_id: UUID | None = None,
          user_id: UUID | None = None, reason: str = "", ip_hash: str = "", **details) -> None:
    s.execute(
        text("""INSERT INTO audit_log (staff_id, staff_email, action, target_workspace_id, target_user_id,
                                       reason, details, ip_hash)
                VALUES (:sid, :email, :a, :w, :u, :r, CAST(:d AS jsonb), :ip)"""),
        {"sid": staff.staff_id if staff else None, "email": staff.email if staff else "", "a": action,
         "w": workspace_id, "u": user_id, "r": reason, "d": json.dumps(details, default=str),
         "ip": staff.ip_hash if staff else ip_hash},
    )


# ---------- schemas ----------


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(max_length=128)
    code: str = Code


class SetupStartIn(BaseModel):
    token: str = Field(max_length=100)


class SetupStartOut(BaseModel):
    email: str
    secret: str = Field(description="Show as text under the QR code for manual entry.")
    otpauth_uri: str = Field(description="Render as a QR code for the authenticator app.")


class SetupFinishIn(BaseModel):
    token: str = Field(max_length=100)
    password: str = Field(min_length=12, max_length=128)
    code: str = Code


class StaffMe(BaseModel):
    id: UUID
    email: str
    display_name: str
    is_super: bool
    permissions: list[str]
    csrf_token: str


class Status(BaseModel):
    status: str


class PermissionOut(BaseModel):
    key: str
    label: str


class StaffRoleIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    description: str = Field(default="", max_length=300)
    permissions: list[str] = Field(default_factory=list, max_length=len(STAFF_PERMISSIONS))


class StaffRoleOut(BaseModel):
    id: UUID
    name: str
    description: str
    permissions: list[str]
    members: int


class StaffRolesOut(BaseModel):
    roles: list[StaffRoleOut]
    catalogue: list[PermissionOut]


class StaffIn(BaseModel):
    email: EmailStr
    display_name: str = Field(default="", max_length=80)
    role_id: UUID


class StaffPatch(BaseModel):
    display_name: str | None = Field(default=None, max_length=80)
    role_id: UUID | None = None
    disabled: bool | None = None


class StaffOut(BaseModel):
    id: UUID
    email: str
    display_name: str
    is_super: bool
    role_id: UUID | None
    role_name: str | None
    status: Literal["active", "setup_pending", "disabled"]
    last_login_at: datetime | None
    created_at: datetime


# ---------- sessions ----------


INVALID_LOGIN = ApiError(401, "invalid_credentials", "That email, password or code isn't right.")


def _me(s: Session, staff_id: UUID, session_id: UUID) -> StaffMe:
    row = s.execute(text("SELECT id, email, display_name, is_super, role_id FROM staff WHERE id = :id"),
                    {"id": staff_id}).one()
    perms = (list(STAFF_PERMISSIONS) if row.is_super else sorted(
        s.execute(text("SELECT permission FROM staff_role_permissions WHERE role_id = :r"),
                  {"r": row.role_id}).scalars().all()) if row.role_id else [])
    return StaffMe(id=row.id, email=row.email, display_name=row.display_name, is_super=row.is_super,
                   permissions=perms, csrf_token=staff_csrf(session_id))


@router.post("/auth/login", response_model=StaffMe)
def login(body: LoginIn, request: Request, response: Response) -> StaffMe:
    """Email, password and the 6-digit code from the authenticator app, all at once."""
    enforce((LOGIN_IP, client_ip(request)), (LOGIN_EMAIL, body.email))
    settings = get_settings()
    with hq_session() as s:
        row = s.execute(text("""SELECT id, email, password_hash, totp_secret, totp_last_step, disabled_at,
                                       totp_enabled_at FROM staff WHERE email = :e"""), {"e": body.email}).first()
        password_ok = verify_password(row.password_hash if row else None, body.password)
        step = None
        if row and password_ok and row.disabled_at is None and row.totp_enabled_at and row.totp_secret:
            step = totp.matching_step(totp.decrypt(bytes(row.totp_secret)), body.code, row.totp_last_step)
        if step is not None:
            step_taken = s.execute(
                text("""UPDATE staff SET totp_last_step = :st, last_login_at = now()
                        WHERE id = :id AND totp_last_step < :st"""), {"st": step, "id": row.id}).rowcount
            if not step_taken:
                step = None
        if step is None:
            if row:
                audit(s, None, "staff.login_failed", ip_hash=_ip_hash(request), staff_email=row.email,
                      password_ok=password_ok)
            failed = True
        else:
            failed = False
            token, session_id = new_token(), uuid4()
            s.execute(
                text("""INSERT INTO staff_sessions (id, token_hash, staff_id, expires_at, ip_hash, user_agent)
                        VALUES (:id, :h, :sid, now() + :ttl, :ip, :ua)"""),
                {"id": session_id, "h": token_hash(token), "sid": row.id,
                 "ttl": timedelta(hours=settings.staff_session_hours), "ip": _ip_hash(request),
                 "ua": request.headers.get("user-agent", "")[:300]},
            )
            s.execute(text("""INSERT INTO audit_log (staff_id, staff_email, action, ip_hash)
                              VALUES (:sid, :e, 'staff.login', :ip)"""),
                      {"sid": row.id, "e": row.email, "ip": _ip_hash(request)})
            me = _me(s, row.id, session_id)
    if failed:
        raise INVALID_LOGIN
    session_cookie, csrf_cookie = staff_cookie_names()
    max_age = settings.staff_session_hours * 3600
    response.set_cookie(session_cookie, token, max_age=max_age, path="/", secure=settings.cookie_secure,
                        httponly=True, samesite="strict")
    response.set_cookie(csrf_cookie, me.csrf_token, max_age=max_age, path="/", secure=settings.cookie_secure,
                        httponly=False, samesite="strict")
    return me


@router.get("/auth/me", response_model=StaffMe)
def me(staff: Staff = Depends(current_staff)) -> StaffMe:
    with hq_session() as s:
        return _me(s, staff.staff_id, staff.session_id)


@router.post("/auth/logout", status_code=204)
def logout(response: Response, staff: Staff = Depends(current_staff)) -> Response:
    with hq_session() as s:
        s.execute(text("UPDATE staff_sessions SET revoked_at = now() WHERE id = :id"), {"id": staff.session_id})
        audit(s, staff, "staff.logout")
    settings = get_settings()
    for name in staff_cookie_names():
        response.delete_cookie(name, path="/", secure=settings.cookie_secure, samesite="strict")
    response.status_code = 204
    return response


# ---------- first-time setup (from the emailed link) ----------


def _setup_row(s: Session, token: str):
    row = s.execute(text("""SELECT id, email, totp_secret FROM staff WHERE setup_token_hash = :h
                            AND setup_expires_at > now() AND disabled_at IS NULL FOR UPDATE"""),
                    {"h": token_hash(token)}).first()
    if row is None:
        raise ApiError(400, "invalid_setup_link", "This setup link has expired. Ask the Super-Admin for a new one.")
    return row


@router.post("/auth/setup/start", response_model=SetupStartOut)
def setup_start(body: SetupStartIn, request: Request) -> SetupStartOut:
    """Step 1 of the setup link: a fresh authenticator secret to scan."""
    enforce((SETUP_IP, client_ip(request)))
    secret = totp.new_secret()
    with hq_session() as s:
        row = _setup_row(s, body.token)
        s.execute(text("UPDATE staff SET totp_secret = :t WHERE id = :id"), {"t": totp.encrypt(secret), "id": row.id})
    return SetupStartOut(email=row.email, secret=secret, otpauth_uri=totp.provisioning_uri(secret, row.email))


@router.post("/auth/setup/finish", response_model=Status)
def setup_finish(body: SetupFinishIn, request: Request) -> Status:
    """Step 2: choose a password and confirm the first code. Then sign in normally."""
    enforce((SETUP_IP, client_ip(request)))
    password_hash = hash_password(body.password)
    with hq_session() as s:
        row = _setup_row(s, body.token)
        step = totp.matching_step(totp.decrypt(bytes(row.totp_secret)), body.code, 0) if row.totp_secret else None
        if step is None:
            raise ApiError(400, "invalid_code", "That code isn't right. Check the time on your phone and try again.")
        s.execute(text("""UPDATE staff SET password_hash = :p, totp_enabled_at = now(), totp_last_step = :st,
                                 setup_token_hash = NULL, setup_expires_at = NULL WHERE id = :id"""),
                  {"p": password_hash, "st": step, "id": row.id})
        s.execute(text("UPDATE staff_sessions SET revoked_at = now() WHERE staff_id = :id AND revoked_at IS NULL"),
                  {"id": row.id})
        s.execute(text("""INSERT INTO audit_log (staff_id, staff_email, action, ip_hash)
                          VALUES (:id, :e, 'staff.setup_completed', :ip)"""),
                  {"id": row.id, "e": row.email, "ip": _ip_hash(request)})
    return Status(status="ready")


def issue_setup_link(s: Session, staff_id: UUID) -> str:
    token = new_token()
    s.execute(text("""UPDATE staff SET setup_token_hash = :h, setup_expires_at = now() + :ttl, password_hash = NULL,
                             totp_secret = NULL, totp_enabled_at = NULL WHERE id = :id"""),
              {"h": token_hash(token), "ttl": SETUP_TTL, "id": staff_id})
    s.execute(text("UPDATE staff_sessions SET revoked_at = now() WHERE staff_id = :id AND revoked_at IS NULL"),
              {"id": staff_id})
    return f"{get_settings().hq_url}/setup#{token}"


def setup_email(to: str, link: str) -> mail.Email:
    return mail.Email(to=to, subject="Set up your Scrollwalk HQ access",
                      text="You've been given staff access to Scrollwalk HQ.\n\n"
                           f"Set your password and two-factor authentication:\n{link}\n\n"
                           "You'll need an authenticator app (Google Authenticator, 1Password, Authy...). "
                           "The link works for 72 hours.")


# ---------- staff accounts (Super-Admin only) ----------


def _staff_out(r) -> StaffOut:
    status = "disabled" if r.disabled_at else "active" if r.totp_enabled_at else "setup_pending"
    return StaffOut(id=r.id, email=r.email, display_name=r.display_name, is_super=r.is_super, role_id=r.role_id,
                    role_name=r.role_name, status=status, last_login_at=r.last_login_at, created_at=r.created_at)


_STAFF_SELECT = """SELECT st.*, r.name AS role_name FROM staff st LEFT JOIN staff_roles r ON r.id = st.role_id"""


@router.get("/staff", response_model=list[StaffOut])
def list_staff(staff: Staff = Depends(current_staff)) -> list[StaffOut]:
    staff.require_super()
    with hq_session() as s:
        return [_staff_out(r) for r in s.execute(text(f"{_STAFF_SELECT} ORDER BY st.is_super DESC, st.created_at"))]


def _role_exists(s: Session, role_id: UUID) -> None:
    if s.execute(text("SELECT 1 FROM staff_roles WHERE id = :r"), {"r": role_id}).first() is None:
        raise ApiError(422, "invalid_role", "Choose one of the staff roles.")


@router.post("/staff", status_code=201, response_model=StaffOut)
def add_staff(body: StaffIn, staff: Staff = Depends(current_staff)) -> StaffOut:
    staff.require_super()
    email = body.email.lower()
    try:
        with hq_session() as s:
            _role_exists(s, body.role_id)
            new_id = s.execute(text("""INSERT INTO staff (email, display_name, role_id, created_by)
                                       VALUES (:e, :n, :r, :by) RETURNING id"""),
                               {"e": email, "n": body.display_name.strip(), "r": body.role_id,
                                "by": staff.staff_id}).scalar_one()
            link = issue_setup_link(s, new_id)
            audit(s, staff, "staff.added", target_staff=str(new_id), email=email, role_id=str(body.role_id))
            row = s.execute(text(f"{_STAFF_SELECT} WHERE st.id = :id"), {"id": new_id}).one()
    except IntegrityError:
        raise ApiError(409, "staff_exists", "This person already has staff access.") from None
    mail.send(setup_email(email, link))
    return _staff_out(row)


def _editable(s: Session, staff: Staff, staff_id: UUID):
    row = s.execute(text("SELECT * FROM staff WHERE id = :id FOR UPDATE"), {"id": staff_id}).first()
    if row is None:
        raise ApiError(404, "not_found", "Staff member not found.")
    if row.is_super:
        raise ApiError(409, "super_admin_protected", "The Super-Admin account can't be changed here.")
    return row


@router.patch("/staff/{staff_id}", response_model=StaffOut)
def update_staff(staff_id: UUID, body: StaffPatch, staff: Staff = Depends(current_staff)) -> StaffOut:
    staff.require_super()
    changes = body.model_dump(exclude_unset=True)
    with hq_session() as s:
        _editable(s, staff, staff_id)
        if changes.get("display_name") is not None:
            s.execute(text("UPDATE staff SET display_name = :n WHERE id = :id"),
                      {"n": changes["display_name"].strip(), "id": staff_id})
        if changes.get("role_id") is not None:
            _role_exists(s, changes["role_id"])
            s.execute(text("UPDATE staff SET role_id = :r WHERE id = :id"), {"r": changes["role_id"], "id": staff_id})
        if changes.get("disabled") is not None:
            s.execute(text("UPDATE staff SET disabled_at = CASE WHEN :d THEN now() END WHERE id = :id"),
                      {"d": changes["disabled"], "id": staff_id})
            if changes["disabled"]:
                s.execute(text("UPDATE staff_sessions SET revoked_at = now() WHERE staff_id = :id AND revoked_at IS NULL"),
                          {"id": staff_id})
        audit(s, staff, "staff.updated", target_staff=str(staff_id), changes=changes)
        return _staff_out(s.execute(text(f"{_STAFF_SELECT} WHERE st.id = :id"), {"id": staff_id}).one())


@router.post("/staff/{staff_id}/reset", response_model=StaffOut)
def reset_staff(staff_id: UUID, staff: Staff = Depends(current_staff)) -> StaffOut:
    """Lost phone or password: signs them out everywhere and emails a new setup link."""
    staff.require_super()
    with hq_session() as s:
        row = _editable(s, staff, staff_id)
        link = issue_setup_link(s, staff_id)
        audit(s, staff, "staff.reset", target_staff=str(staff_id))
        out = _staff_out(s.execute(text(f"{_STAFF_SELECT} WHERE st.id = :id"), {"id": staff_id}).one())
    mail.send(setup_email(row.email, link))
    return out


# ---------- staff roles (Super-Admin only) ----------


def _check_permissions(permissions: list[str]) -> list[str]:
    unknown = set(permissions) - STAFF_PERMISSIONS.keys()
    if unknown:
        raise ApiError(422, "invalid_permission", f"Unknown permission: {sorted(unknown)[0]}")
    return sorted(set(permissions))


def _roles(s: Session) -> StaffRolesOut:
    rows = s.execute(text("""SELECT r.id, r.name, r.description,
                                    coalesce(array_agg(p.permission) FILTER (WHERE p.permission IS NOT NULL), '{}') AS perms,
                                    (SELECT count(*) FROM staff st WHERE st.role_id = r.id) AS members
                             FROM staff_roles r LEFT JOIN staff_role_permissions p ON p.role_id = r.id
                             GROUP BY r.id ORDER BY r.name""")).all()
    return StaffRolesOut(
        roles=[StaffRoleOut(id=r.id, name=r.name, description=r.description, permissions=sorted(r.perms),
                            members=r.members) for r in rows],
        catalogue=[PermissionOut(key=k, label=v) for k, v in STAFF_PERMISSIONS.items()],
    )


@router.get("/roles", response_model=StaffRolesOut)
def list_roles(staff: Staff = Depends(current_staff)) -> StaffRolesOut:
    staff.require_super()
    with hq_session() as s:
        return _roles(s)


def _write_permissions(s: Session, role_id: UUID, permissions: list[str]) -> None:
    s.execute(text("DELETE FROM staff_role_permissions WHERE role_id = :r"), {"r": role_id})
    for p in permissions:
        s.execute(text("INSERT INTO staff_role_permissions (role_id, permission) VALUES (:r, :p)"), {"r": role_id, "p": p})


@router.post("/roles", status_code=201, response_model=StaffRolesOut)
def create_role(body: StaffRoleIn, staff: Staff = Depends(current_staff)) -> StaffRolesOut:
    staff.require_super()
    permissions = _check_permissions(body.permissions)
    try:
        with hq_session() as s:
            role_id = s.execute(text("INSERT INTO staff_roles (name, description) VALUES (:n, :d) RETURNING id"),
                                {"n": body.name.strip(), "d": body.description.strip()}).scalar_one()
            _write_permissions(s, role_id, permissions)
            audit(s, staff, "staff_role.created", role_id=str(role_id), name=body.name, permissions=permissions)
            return _roles(s)
    except IntegrityError:
        raise ApiError(409, "role_exists", "A staff role with this name already exists.") from None


@router.put("/roles/{role_id}", response_model=StaffRolesOut)
def update_role(role_id: UUID, body: StaffRoleIn, staff: Staff = Depends(current_staff)) -> StaffRolesOut:
    staff.require_super()
    permissions = _check_permissions(body.permissions)
    try:
        with hq_session() as s:
            updated = s.execute(text("UPDATE staff_roles SET name = :n, description = :d WHERE id = :id"),
                                {"n": body.name.strip(), "d": body.description.strip(), "id": role_id}).rowcount
            if not updated:
                raise ApiError(404, "not_found", "Staff role not found.")
            _write_permissions(s, role_id, permissions)
            audit(s, staff, "staff_role.updated", role_id=str(role_id), name=body.name, permissions=permissions)
            return _roles(s)
    except IntegrityError:
        raise ApiError(409, "role_exists", "A staff role with this name already exists.") from None


@router.delete("/roles/{role_id}", response_model=StaffRolesOut)
def delete_role(role_id: UUID, staff: Staff = Depends(current_staff)) -> StaffRolesOut:
    staff.require_super()
    with hq_session() as s:
        if s.execute(text("SELECT 1 FROM staff WHERE role_id = :r"), {"r": role_id}).first():
            raise ApiError(409, "role_in_use", "Move the staff in this role to another role first.")
        if not s.execute(text("DELETE FROM staff_roles WHERE id = :id"), {"id": role_id}).rowcount:
            raise ApiError(404, "not_found", "Staff role not found.")
        audit(s, staff, "staff_role.deleted", role_id=str(role_id))
        return _roles(s)

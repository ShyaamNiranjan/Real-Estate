"""Teams (docs/SCOPE.md 10): custom roles, members, invitations.

An invitation link proves the invitee owns the address, so joining through it needs no email code.
The token travels in the link's #fragment, which browsers never send to servers.
"""

from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import Row, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import email as mail
from app.auth import (
    SIGNUP_IP,
    Me,
    build_me,
    ensure_workspace,
    lookup_user,
    record_acceptance,
    set_password,
    start_session,
)
from app.config import get_settings
from app.db import tenant_session
from app.deps import Auth, client_ip, in_workspace, signed_in
from app.errors import ApiError, ErrorResponse
from app.permissions import ALL_PERMISSIONS, CATALOGUE, SUGGESTIONS, Access, PermissionInfo, RoleSuggestion, load_access
from app.plans import TEAM_PLANS, seats
from app.ratelimit import Rule, enforce
from app.security import hash_password, new_token, token_hash

router = APIRouter(
    prefix="/api/v1/team",
    tags=["team"],
    responses={k: {"model": ErrorResponse} for k in (401, 403, 404, 409, 422)},
)
invite_router = APIRouter(
    prefix="/api/v1/invitations",
    tags=["team"],
    responses={k: {"model": ErrorResponse} for k in (401, 403, 404, 409, 410, 422, 429)},
)

INVITE_TTL = timedelta(days=7)
INVITE_SEND = Rule("invite-send", 50, 86400)
INVITE_LOOKUP_IP = Rule("invite-lookup-ip", 30, 600)


class Catalogue(BaseModel):
    permissions: list[PermissionInfo]
    suggestions: list[RoleSuggestion]


class RoleIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    description: str = Field(default="", max_length=200)
    permissions: list[str] = Field(max_length=len(CATALOGUE))


class RoleOut(BaseModel):
    id: UUID
    name: str
    description: str
    permissions: list[str]
    member_count: int


def _require_team_plan(s: Session, workspace_id: UUID) -> None:
    plan = s.execute(text("SELECT plan_key FROM workspaces WHERE id = :w"), {"w": workspace_id}).scalar()
    if plan not in TEAM_PLANS:
        raise ApiError(403, "plan_required", "Roles come with the Team and Brokerage plans.")


def _check_grant(access: Access, requested: set[str], previous: set[str] = frozenset()) -> None:
    unknown = requested - ALL_PERMISSIONS
    if unknown:
        raise ApiError(422, "unknown_permission", f"Unknown permission: {sorted(unknown)[0]}")
    if not (requested - previous) <= access.effective():
        raise ApiError(403, "cannot_grant", "You can't give a role permissions you don't have yourself.")


def _roles(s: Session, role_id: UUID | None = None) -> list[RoleOut]:
    rows = s.execute(
        text("""SELECT r.id, r.name, r.description,
                       coalesce((SELECT array_agg(permission ORDER BY permission) FROM role_permissions rp
                                 WHERE rp.role_id = r.id), '{}') AS permissions,
                       (SELECT count(*) FROM memberships m WHERE m.role_id = r.id AND m.removed_at IS NULL) AS members
                FROM roles r WHERE (CAST(:id AS uuid) IS NULL OR r.id = :id) ORDER BY r.name"""),
        {"id": role_id},
    ).all()
    return [RoleOut(id=r.id, name=r.name, description=r.description, permissions=list(r.permissions),
                    member_count=r.members) for r in rows]


def _set_permissions(s: Session, workspace_id: UUID, role_id: UUID, permissions: set[str]) -> None:
    s.execute(text("DELETE FROM role_permissions WHERE role_id = :r"), {"r": role_id})
    for permission in sorted(permissions):
        s.execute(text("INSERT INTO role_permissions (workspace_id, role_id, permission) VALUES (:w, :r, :p)"),
                  {"w": workspace_id, "r": role_id, "p": permission})


def _manager(s: Session, auth: Auth) -> Access:
    access = load_access(s, auth.user_id, auth.workspace_id)
    access.require("team.manage_roles")
    _require_team_plan(s, auth.workspace_id)
    return access


NAME_TAKEN = ApiError(409, "role_name_taken", "You already have a role with that name.")
NOT_FOUND = ApiError(404, "not_found", "That role doesn't exist.")


@router.get("/permissions", response_model=Catalogue)
def permission_catalogue(_: Auth = Depends(in_workspace)) -> Catalogue:
    return Catalogue(permissions=CATALOGUE, suggestions=SUGGESTIONS)


@router.get("/roles", response_model=list[RoleOut])
def list_roles(auth: Auth = Depends(in_workspace)) -> list[RoleOut]:
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        access = load_access(s, auth.user_id, auth.workspace_id)
        if not (access.has("team.manage_roles") or access.has("team.manage_members")):
            access.require("team.manage_roles")
        return _roles(s)


@router.post("/roles", status_code=201, response_model=RoleOut)
def create_role(body: RoleIn, auth: Auth = Depends(in_workspace)) -> RoleOut:
    requested = set(body.permissions)
    try:
        with tenant_session(auth.user_id, auth.workspace_id) as s:
            _check_grant(_manager(s, auth), requested)
            role_id = s.execute(
                text("INSERT INTO roles (workspace_id, name, description) VALUES (:w, :n, :d) RETURNING id"),
                {"w": auth.workspace_id, "n": body.name.strip(), "d": body.description.strip()},
            ).scalar_one()
            _set_permissions(s, auth.workspace_id, role_id, requested)
            return _roles(s, role_id)[0]
    except IntegrityError:
        raise NAME_TAKEN


@router.put("/roles/{role_id}", response_model=RoleOut)
def update_role(role_id: UUID, body: RoleIn, auth: Auth = Depends(in_workspace)) -> RoleOut:
    requested = set(body.permissions)
    try:
        with tenant_session(auth.user_id, auth.workspace_id) as s:
            access = _manager(s, auth)
            existing = _roles(s, role_id)
            if not existing:
                raise NOT_FOUND
            _check_grant(access, requested, set(existing[0].permissions))
            s.execute(text("UPDATE roles SET name = :n, description = :d, updated_at = now() WHERE id = :r"),
                      {"n": body.name.strip(), "d": body.description.strip(), "r": role_id})
            _set_permissions(s, auth.workspace_id, role_id, requested)
            return _roles(s, role_id)[0]
    except IntegrityError:
        raise NAME_TAKEN


@router.delete("/roles/{role_id}", status_code=204)
def delete_role(role_id: UUID, auth: Auth = Depends(in_workspace)) -> Response:
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        _manager(s, auth)
        existing = _roles(s, role_id)
        if not existing:
            raise NOT_FOUND
        if existing[0].member_count:
            raise ApiError(409, "role_in_use", "Move this role's members to another role first.")
        pending = s.execute(
            text("""SELECT EXISTS (SELECT 1 FROM invitations WHERE role_id = :r
                                   AND accepted_at IS NULL AND revoked_at IS NULL AND expires_at > now())"""),
            {"r": role_id},
        ).scalar()
        if pending:
            raise ApiError(409, "role_in_use", "Withdraw the pending invitations for this role first.")
        s.execute(text("DELETE FROM roles WHERE id = :r"), {"r": role_id})
    return Response(status_code=204)


# ---------- members ----------


class RoleRef(BaseModel):
    id: UUID
    name: str


class MemberOut(BaseModel):
    id: UUID
    name: str
    avatar_url: str | None
    email: str | None = Field(description="Shown to members who manage the team, and to the member themselves.")
    licence_number: str | None = Field(description="Same visibility as email.")
    is_admin: bool
    is_you: bool
    role: RoleRef | None
    can_be_listing_agent: bool
    joined_at: datetime


class MemberPatch(BaseModel):
    role_id: UUID | None = None
    licence_number: str | None = Field(default=None, max_length=60)


class SuccessorIn(BaseModel):
    successor_id: UUID | None = Field(default=None, description="Who takes over their listings and enquiries. Defaults to the Admin.")


def _members(s: Session, access: Access, member_id: UUID | None = None) -> list[MemberOut]:
    rows = s.execute(
        text("""SELECT m.id, m.user_id, m.is_admin, m.licence_number, m.joined_at, m.role_id, r.name AS role_name,
                       u.email, u.avatar_url, coalesce(nullif(u.display_name, ''), u.email::text) AS name,
                       EXISTS (SELECT 1 FROM role_permissions rp WHERE rp.role_id = m.role_id
                               AND rp.permission = 'listings.listing_agent') AS can_list
                FROM memberships m JOIN users u ON u.id = m.user_id LEFT JOIN roles r ON r.id = m.role_id
                WHERE m.workspace_id = :w AND m.removed_at IS NULL AND (CAST(:id AS uuid) IS NULL OR m.id = :id)
                ORDER BY m.is_admin DESC, m.joined_at"""),
        {"w": access.workspace_id, "id": member_id},
    ).all()
    manager = access.has("team.manage_members")
    out = []
    for r in rows:
        you = r.user_id == access.user_id
        private = manager or you
        out.append(MemberOut(
            id=r.id, name=r.name, avatar_url=r.avatar_url, is_admin=r.is_admin, is_you=you,
            email=r.email if private else None, licence_number=r.licence_number if private else None,
            role=RoleRef(id=r.role_id, name=r.role_name) if r.role_id else None,
            can_be_listing_agent=r.is_admin or r.can_list, joined_at=r.joined_at,
        ))
    return out


def _member_permissions(s: Session, member_id: UUID) -> Row | None:
    return s.execute(
        text("""SELECT m.is_admin, m.user_id,
                       coalesce((SELECT array_agg(permission) FROM role_permissions rp WHERE rp.role_id = m.role_id),
                                '{}') AS perms
                FROM memberships m WHERE m.id = :m AND m.removed_at IS NULL"""),
        {"m": member_id},
    ).first()


def _check_outranks(access: Access, target: Row) -> None:
    if target.is_admin:
        raise ApiError(403, "admin_protected", "The Admin's role can't be changed and they can't be removed.")
    if not set(target.perms) <= access.effective():
        raise ApiError(403, "cannot_manage", "This person has permissions you don't, so ask your Admin.")


MEMBER_NOT_FOUND = ApiError(404, "not_found", "That person isn't on your team.")

_REMOVE_ERRORS = {
    "forbidden": ApiError(403, "permission_denied", "Your role doesn't allow this. Ask your Admin."),
    "not_found": MEMBER_NOT_FOUND,
    "is_admin": ApiError(403, "admin_protected", "The Admin's role can't be changed and they can't be removed."),
    "bad_successor": ApiError(422, "invalid_successor", "Choose someone else on the team to take over their work."),
}


def _remove(s: Session, member_id: UUID, successor_id: UUID | None) -> None:
    if successor_id is None:
        successor_id = s.execute(text("SELECT id FROM memberships WHERE is_admin AND removed_at IS NULL")).scalar_one()
    status = s.execute(text("SELECT member_remove(:m, :to)"), {"m": member_id, "to": successor_id}).scalar_one()
    if status != "removed":
        raise _REMOVE_ERRORS[status]


@router.get("/members", response_model=list[MemberOut])
def list_members(auth: Auth = Depends(in_workspace)) -> list[MemberOut]:
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        return _members(s, load_access(s, auth.user_id, auth.workspace_id))


@router.patch("/members/{member_id}", response_model=MemberOut)
def update_member(member_id: UUID, body: MemberPatch, auth: Auth = Depends(in_workspace)) -> MemberOut:
    changes = body.model_dump(exclude_unset=True)
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        access = load_access(s, auth.user_id, auth.workspace_id)
        target = _member_permissions(s, member_id)
        if target is None:
            raise MEMBER_NOT_FOUND
        you = member_id == access.membership_id
        if "licence_number" in changes:
            if not (you or access.has("team.manage_members")):
                access.require("team.manage_members")
            s.execute(text("UPDATE memberships SET licence_number = :l WHERE id = :m"),
                      {"l": (changes["licence_number"] or "").strip(), "m": member_id})
        if "role_id" in changes:
            access.require("team.manage_members")
            _require_team_plan(s, auth.workspace_id)
            if you:
                raise ApiError(403, "cannot_change_own_role", "Ask someone else on the team to change your role.")
            _check_outranks(access, target)
            role = _roles(s, changes["role_id"]) if changes["role_id"] else []
            if not role:
                raise ApiError(422, "invalid_role", "Choose one of your roles.")
            _check_grant(access, set(role[0].permissions))
            s.execute(text("UPDATE memberships SET role_id = :r WHERE id = :m"), {"r": role[0].id, "m": member_id})
        return _members(s, access, member_id)[0]


@router.post("/members/{member_id}/remove", status_code=204)
def remove_member(member_id: UUID, body: SuccessorIn, auth: Auth = Depends(in_workspace)) -> Response:
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        access = load_access(s, auth.user_id, auth.workspace_id)
        access.require("team.manage_members")
        if member_id == access.membership_id:
            raise ApiError(409, "use_leave", "To leave the team yourself, use Leave team.")
        target = _member_permissions(s, member_id)
        if target is None:
            raise MEMBER_NOT_FOUND
        _check_outranks(access, target)
        _remove(s, member_id, body.successor_id)
    return Response(status_code=204)


@router.post("/leave", response_model=Me)
def leave_team(body: SuccessorIn, auth: Auth = Depends(in_workspace)) -> Me:
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        access = load_access(s, auth.user_id, auth.workspace_id)
        if access.is_admin:
            raise ApiError(403, "admin_protected", "The Admin can't leave their own workspace.")
        _remove(s, access.membership_id, body.successor_id)
    with tenant_session(auth.user_id) as s:
        workspace_id = ensure_workspace(s, auth.user_id)
        s.execute(text("UPDATE sessions SET workspace_id = :w WHERE id = :id"), {"w": workspace_id, "id": auth.session_id})
    return build_me(Auth(auth.session_id, auth.user_id, workspace_id))


# ---------- invitations (managing) ----------


class InviteIn(BaseModel):
    email: EmailStr
    role_id: UUID


class InvitationOut(BaseModel):
    id: UUID
    email: str
    role: RoleRef
    invited_by: str
    created_at: datetime
    expires_at: datetime
    status: Literal["open", "expired"]


class SeatsOut(BaseModel):
    used: int = Field(description="Members plus open invitations.")
    total: int


class InvitationList(BaseModel):
    items: list[InvitationOut]
    seats: SeatsOut


def _invitations(s: Session, invitation_id: UUID | None = None) -> list[InvitationOut]:
    rows = s.execute(
        text("""SELECT i.id, i.email, i.role_id, r.name AS role_name, i.created_at, i.expires_at,
                       coalesce(nullif(u.display_name, ''), u.email::text) AS inviter,
                       i.expires_at <= now() AS expired
                FROM invitations i JOIN roles r ON r.id = i.role_id JOIN users u ON u.id = i.invited_by
                WHERE i.accepted_at IS NULL AND i.revoked_at IS NULL
                  AND (CAST(:id AS uuid) IS NULL OR i.id = :id)
                ORDER BY i.created_at DESC"""),
        {"id": invitation_id},
    ).all()
    return [InvitationOut(id=r.id, email=r.email, role=RoleRef(id=r.role_id, name=r.role_name), invited_by=r.inviter,
                          created_at=r.created_at, expires_at=r.expires_at, status="expired" if r.expired else "open")
            for r in rows]


def _seats(s: Session, workspace_id: UUID) -> SeatsOut:
    row = s.execute(
        text("""SELECT w.plan_key,
                       (SELECT count(*) FROM memberships m WHERE m.workspace_id = w.id AND m.removed_at IS NULL)
                     + (SELECT count(*) FROM invitations i WHERE i.workspace_id = w.id AND i.accepted_at IS NULL
                          AND i.revoked_at IS NULL AND i.expires_at > now()) AS used
                FROM workspaces w WHERE w.id = :w"""),
        {"w": workspace_id},
    ).one()
    return SeatsOut(used=row.used, total=seats(s, row.plan_key))


def _inviter(s: Session, access: Access) -> Access:
    access.require("team.manage_members")
    _require_team_plan(s, access.workspace_id)
    return access


def _send_invitation(s: Session, invitation_id: UUID, to: str) -> mail.Email:
    token = new_token()
    row = s.execute(
        text("""UPDATE invitations i SET token_hash = :h, expires_at = now() + :ttl FROM roles r, users u, workspaces w
                WHERE i.id = :id AND r.id = i.role_id AND u.id = i.invited_by AND w.id = i.workspace_id
                RETURNING r.name AS role, coalesce(nullif(u.display_name, ''), u.email::text) AS inviter,
                          w.display_name AS team"""),
        {"h": token_hash(token), "ttl": INVITE_TTL, "id": invitation_id},
    ).one()
    link = f"{get_settings().app_url}/join#{token}"
    return mail.invitation_email(to, row.inviter, row.team or "their team", row.role, link)


@router.get("/invitations", response_model=InvitationList)
def list_invitations(auth: Auth = Depends(in_workspace)) -> InvitationList:
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        load_access(s, auth.user_id, auth.workspace_id).require("team.manage_members")
        return InvitationList(items=_invitations(s), seats=_seats(s, auth.workspace_id))


@router.post("/invitations", status_code=201, response_model=InvitationOut)
def invite(body: InviteIn, auth: Auth = Depends(in_workspace)) -> InvitationOut:
    email = body.email.strip().lower()
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        access = _inviter(s, load_access(s, auth.user_id, auth.workspace_id))
        role = _roles(s, body.role_id)
        if not role:
            raise ApiError(422, "invalid_role", "Choose one of your roles.")
        _check_grant(access, set(role[0].permissions))
        member = s.execute(
            text("""SELECT 1 FROM memberships m JOIN users u ON u.id = m.user_id
                    WHERE m.workspace_id = :w AND m.removed_at IS NULL AND u.email = :e"""),
            {"w": auth.workspace_id, "e": email},
        ).first()
        if member:
            raise ApiError(409, "already_member", "That person is already on your team.")
        s.execute(
            text("UPDATE invitations SET revoked_at = now() WHERE email = :e AND accepted_at IS NULL AND revoked_at IS NULL"),
            {"e": email},
        )
        seats = _seats(s, auth.workspace_id)
        if seats.used >= seats.total:
            raise ApiError(409, "seats_full", "Every seat on your plan is taken. Remove someone or upgrade first.")
        enforce((INVITE_SEND, str(auth.workspace_id)))
        invitation_id = s.execute(
            text("""INSERT INTO invitations (workspace_id, email, role_id, token_hash, invited_by, expires_at)
                    VALUES (:w, :e, :r, :h, :u, now()) RETURNING id"""),
            {"w": auth.workspace_id, "e": email, "r": body.role_id, "h": token_hash(new_token()), "u": auth.user_id},
        ).scalar_one()
        outgoing = _send_invitation(s, invitation_id, email)
        out = _invitations(s, invitation_id)[0]
    mail.send(outgoing)
    return out


@router.post("/invitations/{invitation_id}/resend", response_model=InvitationOut)
def resend_invitation(invitation_id: UUID, auth: Auth = Depends(in_workspace)) -> InvitationOut:
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        _inviter(s, load_access(s, auth.user_id, auth.workspace_id))
        existing = _invitations(s, invitation_id)
        if not existing:
            raise ApiError(404, "not_found", "That invitation doesn't exist.")
        if existing[0].status == "expired":
            seats = _seats(s, auth.workspace_id)
            if seats.used >= seats.total:
                raise ApiError(409, "seats_full", "Every seat on your plan is taken. Remove someone or upgrade first.")
        enforce((INVITE_SEND, str(auth.workspace_id)))
        outgoing = _send_invitation(s, invitation_id, existing[0].email)
        out = _invitations(s, invitation_id)[0]
    mail.send(outgoing)
    return out


@router.delete("/invitations/{invitation_id}", status_code=204)
def revoke_invitation(invitation_id: UUID, auth: Auth = Depends(in_workspace)) -> Response:
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        load_access(s, auth.user_id, auth.workspace_id).require("team.manage_members")
        revoked = s.execute(
            text("""UPDATE invitations SET revoked_at = now()
                    WHERE id = :id AND accepted_at IS NULL AND revoked_at IS NULL"""),
            {"id": invitation_id},
        ).rowcount
    if not revoked:
        raise ApiError(404, "not_found", "That invitation doesn't exist.")
    return Response(status_code=204)


# ---------- invitations (the invitee's side) ----------


class TokenIn(BaseModel):
    token: str = Field(min_length=20, max_length=100)


class InvitationPreview(BaseModel):
    email: str
    team_name: str
    role_name: str
    invited_by: str
    expires_at: datetime
    status: Literal["open", "expired", "accepted", "revoked"]
    has_account: bool = Field(description="True: sign in (password or Google) with this email, then accept. "
                                          "False: create a password with POST /invitations/signup.")


class InviteSignupIn(TokenIn):
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(default="", max_length=80)
    accept_terms: Literal[True]


INVITATION_GONE = ApiError(410, "invitation_invalid", "This invitation has expired or been withdrawn. Ask for a new one.")


def _lookup(token: str) -> Row:
    with tenant_session() as s:
        row = s.execute(text("SELECT * FROM invitation_lookup(:h)"), {"h": token_hash(token)}).first()
    if row is None:
        raise INVITATION_GONE
    return row


def _accept(s: Session, token: str, plan_key: str | None) -> UUID:
    row = s.execute(text("SELECT * FROM invitation_accept(:h, :seats)"),
                    {"h": token_hash(token), "seats": seats(s, plan_key)}).one()
    if row.status == "email_mismatch":
        raise ApiError(403, "invitation_email_mismatch", "This invitation was sent to a different email. "
                                                         "Sign in with that email to accept it.")
    if row.status == "seats_full":
        raise ApiError(409, "seats_full", "This team has no free seats right now. Ask them to make room.")
    if row.status != "joined":
        raise INVITATION_GONE
    return row.workspace_id


def _notify_inviter(user_id: UUID, workspace_id: UUID) -> mail.Email | None:
    with tenant_session(user_id, workspace_id) as s:
        row = s.execute(
            text("""SELECT inviter.email AS to, w.display_name AS team,
                           coalesce(nullif(me.display_name, ''), me.email::text) AS member
                    FROM memberships m JOIN users me ON me.id = m.user_id JOIN workspaces w ON w.id = m.workspace_id
                    JOIN memberships im ON im.workspace_id = m.workspace_id AND im.user_id = m.invited_by
                                       AND im.removed_at IS NULL
                    JOIN users inviter ON inviter.id = im.user_id
                    WHERE m.workspace_id = :w AND m.user_id = :u AND m.removed_at IS NULL"""),
            {"w": workspace_id, "u": user_id},
        ).first()
    return mail.member_joined_notice(row.to, row.member, row.team or "your team") if row else None


@invite_router.post("/lookup", response_model=InvitationPreview)
def preview_invitation(body: TokenIn, request: Request) -> InvitationPreview:
    enforce((INVITE_LOOKUP_IP, client_ip(request)))
    row = _lookup(body.token)
    user = lookup_user(row.email) if row.status == "open" else None
    return InvitationPreview(email=row.email, team_name=row.workspace_name or "A Scrollwalk team",
                             role_name=row.role_name, invited_by=row.inviter_name, expires_at=row.expires_at,
                             status=row.status, has_account=bool(user and user.email_verified_at))


@invite_router.post("/accept", response_model=Me)
def accept_invitation(body: TokenIn, request: Request, auth: Auth = Depends(signed_in)) -> Me:
    """For someone already signed in with the invited email."""
    enforce((INVITE_LOOKUP_IP, client_ip(request)))
    row = _lookup(body.token)
    with tenant_session(auth.user_id) as s:
        workspace_id = _accept(s, body.token, row.plan_key)
        s.execute(text("UPDATE sessions SET workspace_id = :w, last_seen_at = now() WHERE id = :id"),
                  {"w": workspace_id, "id": auth.session_id})
    notice = _notify_inviter(auth.user_id, workspace_id)
    if notice:
        mail.send(notice)
    return build_me(Auth(auth.session_id, auth.user_id, workspace_id))


@invite_router.post("/signup", response_model=Me)
def signup_with_invitation(body: InviteSignupIn, request: Request, response: Response) -> Me:
    """Creates the account and joins the team in one step. The emailed link already proved the inbox."""
    enforce((SIGNUP_IP, client_ip(request)), (INVITE_LOOKUP_IP, client_ip(request)))
    row = _lookup(body.token)
    if row.status != "open":
        raise INVITATION_GONE
    existing = lookup_user(row.email)
    if existing and existing.email_verified_at:
        raise ApiError(409, "account_exists", "You already have a Scrollwalk account. Sign in to accept the invitation.")
    user_id = existing.user_id if existing else uuid4()
    password_hash = hash_password(body.password)
    try:
        with tenant_session(user_id) as s:
            if existing:
                s.execute(text("UPDATE users SET display_name = :n, email_verified_at = now() WHERE id = :u"),
                          {"n": body.display_name.strip(), "u": user_id})
            else:
                s.execute(text("""INSERT INTO users (id, email, display_name, email_verified_at)
                                  VALUES (:u, :e, :n, now())"""),
                          {"u": user_id, "e": row.email, "n": body.display_name.strip()})
            set_password(s, user_id, password_hash)
            record_acceptance(s, user_id, "invite", request)
            workspace_id = _accept(s, body.token, row.plan_key)
    except IntegrityError:
        raise INVITATION_GONE
    notice = _notify_inviter(user_id, workspace_id)
    if notice:
        mail.send(notice)
    return build_me(start_session(response, request, user_id))

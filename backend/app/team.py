"""Custom roles (docs/SCOPE.md 10). Members and invitations arrive with the Teams slice."""

from uuid import UUID

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import tenant_session
from app.deps import Auth, in_workspace
from app.errors import ApiError, ErrorResponse
from app.permissions import ALL_PERMISSIONS, CATALOGUE, SUGGESTIONS, Access, PermissionInfo, RoleSuggestion, load_access

router = APIRouter(
    prefix="/api/v1/team",
    tags=["team"],
    responses={k: {"model": ErrorResponse} for k in (401, 403, 404, 409, 422)},
)

TEAM_PLANS = frozenset({"team", "brokerage"})


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
        s.execute(text("DELETE FROM roles WHERE id = :r"), {"r": role_id})
    return Response(status_code=204)

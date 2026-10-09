"""Workspace permission catalogue and checks (docs/SCOPE.md section 10).

Billing, plan changes, deleting the workspace and transferring Admin are Admin-only and
deliberately absent from the catalogue, so no role can ever be given them.
"""

from dataclasses import dataclass
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.errors import ApiError


class PermissionInfo(BaseModel):
    key: str
    group: str
    label: str
    description: str


def _p(key: str, group: str, label: str, description: str) -> PermissionInfo:
    return PermissionInfo(key=key, group=group, label=label, description=description)


CATALOGUE: list[PermissionInfo] = [
    _p("listings.create", "Listings", "Create listings", "Start new listings."),
    _p("listings.edit_own", "Listings", "Edit their listings", "Edit listings they're the agent on."),
    _p("listings.edit_all", "Listings", "Edit the whole team's listings", "Edit any listing in the workspace."),
    _p("listings.publish_own", "Listings", "Publish their listings",
       "Publish and unpublish their own listings. Without this, listings wait for approval."),
    _p("listings.publish_all", "Listings", "Publish the whole team's listings",
       "Publish, unpublish and approve any listing."),
    _p("listings.delete_own", "Listings", "Delete their listings", "Delete listings they're the agent on."),
    _p("listings.delete_all", "Listings", "Delete the whole team's listings", "Delete any listing."),
    _p("listings.listing_agent", "Listings", "Appear as the listing agent",
       "Be shown as the agent on listings. Needs a licence number where the country requires one."),
    _p("enquiries.view_own", "Enquiries", "See enquiries on their listings", "Read and manage those enquiries."),
    _p("enquiries.view_all", "Enquiries", "See the whole team's enquiries", "Read and manage every enquiry."),
    _p("enquiries.export", "Enquiries", "Export enquiries", "Download enquiries they can see."),
    _p("analytics.view_own", "Analytics", "See analytics for their listings", "Views, visitors and walkthroughs."),
    _p("analytics.view_all", "Analytics", "See the whole team's analytics", "Analytics for every listing and the site."),
    _p("analytics.seller_reports", "Analytics", "Create seller reports", "Share report links with sellers."),
    _p("site.edit_pages", "Website", "Edit pages and sections", "Change the website's pages and content."),
    _p("site.edit_brand", "Website", "Edit brand and style", "Name, style preset, country details."),
    _p("site.edit_contact", "Website", "Edit contact details", "Email, phone, WhatsApp and booking link."),
    _p("site.publish", "Website", "Publish the website", "Put the website live or take it offline."),
    _p("team.manage_members", "Team", "Invite and remove members", "Manage who is on the team."),
    _p("team.manage_roles", "Team", "Create and edit roles", "Manage roles and their permissions."),
]
ALL_PERMISSIONS = frozenset(p.key for p in CATALOGUE)


class RoleSuggestion(BaseModel):
    name: str
    description: str
    permissions: list[str]


SUGGESTIONS = [
    RoleSuggestion(name="Agent", description="Lists homes and handles their own buyers.", permissions=[
        "listings.create", "listings.edit_own", "listings.publish_own", "listings.delete_own",
        "listings.listing_agent", "enquiries.view_own", "analytics.view_own", "analytics.seller_reports",
    ]),
    RoleSuggestion(name="Marketing", description="Keeps the website and listings looking their best.", permissions=[
        "listings.edit_all", "site.edit_pages", "site.edit_brand", "analytics.view_all",
    ]),
    RoleSuggestion(name="Coordinator", description="Prepares listings and follows up on enquiries.", permissions=[
        "listings.create", "listings.edit_all", "enquiries.view_all", "enquiries.export", "analytics.view_all",
    ]),
]


@dataclass(frozen=True)
class Access:
    user_id: UUID
    workspace_id: UUID
    is_admin: bool
    permissions: frozenset[str]

    def has(self, permission: str) -> bool:
        return self.is_admin or permission in self.permissions

    def require(self, *permissions: str) -> None:
        if not all(self.has(p) for p in permissions):
            raise ApiError(403, "permission_denied", "Your role doesn't allow this. Ask your Admin.")

    def require_admin(self) -> None:
        if not self.is_admin:
            raise ApiError(403, "admin_only", "Only the workspace Admin can do this.")

    def effective(self) -> frozenset[str]:
        return ALL_PERMISSIONS if self.is_admin else self.permissions


def load_access(s: Session, user_id: UUID, workspace_id: UUID) -> Access:
    row = s.execute(
        text("""SELECT m.is_admin, coalesce(array_agg(rp.permission) FILTER (WHERE rp.permission IS NOT NULL), '{}') AS perms
                FROM memberships m LEFT JOIN role_permissions rp ON rp.role_id = m.role_id
                WHERE m.workspace_id = :w AND m.user_id = :u AND m.removed_at IS NULL
                GROUP BY m.is_admin"""),
        {"w": workspace_id, "u": user_id},
    ).first()
    if row is None:
        raise ApiError(403, "not_a_member", "You're no longer a member of this workspace.")
    return Access(user_id, workspace_id, row.is_admin, frozenset(row.perms) & ALL_PERMISSIONS)

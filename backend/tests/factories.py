from dataclasses import dataclass
from uuid import UUID, uuid4

from app.db import tenant_session
from app.models import Membership, User, Workspace


@dataclass
class Tenant:
    user_id: UUID
    workspace_id: UUID


def make_user(email: str) -> UUID:
    user_id = uuid4()
    with tenant_session(user_id=user_id) as s:
        s.add(User(id=user_id, email=email))
    return user_id


def make_tenant(email: str, username: str) -> Tenant:
    """A signed-up Admin with their own workspace, created the way the API will create it."""
    user_id, workspace_id = uuid4(), uuid4()
    with tenant_session(user_id=user_id, workspace_id=workspace_id) as s:
        s.add(User(id=user_id, email=email))
        s.add(Workspace(id=workspace_id, username=username, display_name=username.title()))
        s.flush()
        s.add(Membership(workspace_id=workspace_id, user_id=user_id, is_admin=True))
    return Tenant(user_id, workspace_id)

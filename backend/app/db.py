"""Database access.

Three engines, one per database role (docs/SCOPE.md section 9.1):
  rw      the API, always inside a tenant transaction
  public  read-only, published content only
  hq      Super-Admin

Row-level security reads `app.user_id` and `app.workspace_id`. They are set with
set_config(..., is_local => true) so they vanish when the transaction ends and can never
leak to the next request that reuses the pooled connection.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from uuid import UUID

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

from app.config import get_settings

_SET_CONTEXT = text(
    "SELECT set_config('app.user_id', :user_id, true), "
    "set_config('app.workspace_id', :workspace_id, true)"
)


def _engine(url: str) -> Engine:
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=10)


@lru_cache
def rw_engine() -> Engine:
    return _engine(get_settings().database_url)


@lru_cache
def public_engine() -> Engine:
    return _engine(get_settings().public_database_url)


@lru_cache
def hq_engine() -> Engine:
    return _engine(get_settings().hq_database_url)


def set_context(session: Session, user_id: UUID | None, workspace_id: UUID | None) -> None:
    """Only ever pass ids the server has already established (session lookup, a fresh uuid4)."""
    session.execute(
        _SET_CONTEXT,
        {
            "user_id": str(user_id) if user_id else "",
            "workspace_id": str(workspace_id) if workspace_id else "",
        },
    )


@contextmanager
def tenant_session(
    user_id: UUID | None = None, workspace_id: UUID | None = None
) -> Iterator[Session]:
    """One transaction scoped to a user and (optionally) a workspace. Commits on success."""
    with Session(rw_engine()) as session, session.begin():
        set_context(session, user_id, workspace_id)
        yield session


@contextmanager
def public_session() -> Iterator[Session]:
    with Session(public_engine()) as session, session.begin():
        yield session

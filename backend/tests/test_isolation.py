"""Cross-tenant leak tests at the database layer (docs/SCOPE.md section 9.7).

Every test here assumes the application code is buggy (no WHERE clause, wrong id) and
checks that Postgres still refuses to hand over another workspace's data.
"""

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from app.db import public_session, tenant_session
from app.models import Membership, User, UserCredential, Workspace
from tests.factories import make_tenant, make_user


@pytest.fixture
def a():
    return make_tenant("alice@example.com", "alice")


@pytest.fixture
def b():
    return make_tenant("bob@example.com", "bob")


def ids(session, table):
    return {row[0] for row in session.execute(text(f"SELECT id FROM {table}"))}


def test_every_table_has_forced_rls(owner_engine):
    with owner_engine.connect() as conn:
        unprotected = conn.execute(text("""
            SELECT relname FROM pg_class
            WHERE relnamespace = 'public'::regnamespace AND relkind IN ('r', 'p')
              AND relname <> 'alembic_version'
              AND NOT (relrowsecurity AND relforcerowsecurity)
        """)).scalars().all()
    assert unprotected == []


def test_app_roles_cannot_bypass_rls(owner_engine):
    with owner_engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT rolname FROM pg_roles
            WHERE rolname IN ('app_rw', 'app_public', 'app_hq') AND (rolbypassrls OR rolsuper)
        """)).scalars().all()
    assert rows == []


def test_no_context_sees_nothing(a, b):
    with tenant_session() as s:
        for table in ("users", "workspaces", "memberships"):
            assert ids(s, table) == set(), table


def test_tenant_sees_only_its_own_rows(a, b):
    with tenant_session(a.user_id, a.workspace_id) as s:
        assert ids(s, "workspaces") == {a.workspace_id}
        assert ids(s, "users") == {a.user_id}
        assert {m.workspace_id for m in s.query(Membership)} == {a.workspace_id}


def test_unfiltered_update_cannot_touch_other_workspace(a, b, owner_engine):
    with tenant_session(a.user_id, a.workspace_id) as s:
        s.execute(text("UPDATE workspaces SET display_name = 'hacked'"))
        s.execute(text("UPDATE users SET display_name = 'hacked'"))
    with owner_engine.connect() as conn:
        assert conn.execute(text("SELECT display_name FROM workspaces WHERE id = :id"), {"id": b.workspace_id}).scalar() == "Bob"
        assert conn.execute(text("SELECT display_name FROM users WHERE id = :id"), {"id": b.user_id}).scalar() == ""


def test_targeted_update_of_other_workspace_changes_nothing(a, b):
    with tenant_session(a.user_id, a.workspace_id) as s:
        result = s.execute(text("UPDATE workspaces SET display_name = 'x' WHERE id = :id"), {"id": b.workspace_id})
        assert result.rowcount == 0


def test_cannot_add_self_to_other_workspace(a, b):
    with pytest.raises(DBAPIError, match="row-level security"):
        with tenant_session(a.user_id, a.workspace_id) as s:
            s.add(Membership(workspace_id=b.workspace_id, user_id=a.user_id))


def test_cannot_move_a_row_into_other_workspace(a, b):
    with pytest.raises(DBAPIError, match="row-level security"):
        with tenant_session(a.user_id, a.workspace_id) as s:
            s.execute(text("UPDATE memberships SET workspace_id = :b"), {"b": b.workspace_id})


def test_cannot_create_workspace_outside_context(a):
    with pytest.raises(DBAPIError, match="row-level security"):
        with tenant_session(a.user_id, a.workspace_id) as s:
            s.add(Workspace(id=uuid4(), username="sneaky"))


def test_cannot_create_user_as_someone_else(a):
    with pytest.raises(DBAPIError, match="row-level security"):
        with tenant_session(a.user_id, a.workspace_id) as s:
            s.add(User(id=uuid4(), email="mallory@example.com"))


def test_api_cannot_delete_accounts(a):
    for table in ("users", "workspaces", "memberships"):
        with pytest.raises(ProgrammingError, match="permission denied"):
            with tenant_session(a.user_id, a.workspace_id) as s:
                s.execute(text(f"DELETE FROM {table}"))


def test_turning_rls_off_is_refused(a):
    with pytest.raises(DBAPIError, match="row-level security"):
        with tenant_session(a.user_id, a.workspace_id) as s:
            s.execute(text("SET LOCAL row_security = off"))
            s.execute(text("SELECT id FROM workspaces")).all()


def test_context_is_cleared_after_each_transaction(a):
    for _ in range(3):
        with tenant_session(a.user_id, a.workspace_id) as s:
            assert ids(s, "workspaces") == {a.workspace_id}
        with tenant_session() as s:
            assert s.execute(text("SELECT current_setting('app.workspace_id', true)")).scalar() == ""
            assert ids(s, "workspaces") == set()


def test_teammates_visible_only_inside_their_workspace(a, b):
    carol = make_user("carol@example.com")
    with tenant_session(a.user_id, a.workspace_id) as s:
        s.add(Membership(workspace_id=a.workspace_id, user_id=carol, invited_by=a.user_id))
    with tenant_session(a.user_id, a.workspace_id) as s:
        assert ids(s, "users") == {a.user_id, carol}
    with tenant_session(b.user_id, b.workspace_id) as s:
        assert ids(s, "users") == {b.user_id}
    with tenant_session(carol) as s:
        assert ids(s, "workspaces") == {a.workspace_id}


def test_removed_member_loses_access(a):
    carol = make_user("carol@example.com")
    with tenant_session(a.user_id, a.workspace_id) as s:
        s.add(Membership(workspace_id=a.workspace_id, user_id=carol))
    with tenant_session(a.user_id, a.workspace_id) as s:
        s.execute(text("UPDATE memberships SET removed_at = now() WHERE user_id = :c"), {"c": carol})
    with tenant_session(carol) as s:
        assert ids(s, "workspaces") == set()


def test_password_hashes_are_write_only(a, b):
    with tenant_session(a.user_id, a.workspace_id) as s:
        s.add(UserCredential(user_id=a.user_id, password_hash="argon2-hash-a"))
    with pytest.raises(ProgrammingError, match="permission denied"):
        with tenant_session(a.user_id, a.workspace_id) as s:
            s.execute(text("SELECT password_hash FROM user_credentials")).all()
    with pytest.raises(DBAPIError, match="row-level security"):
        with tenant_session(a.user_id, a.workspace_id) as s:
            s.add(UserCredential(user_id=b.user_id, password_hash="overwrite-b"))
    with tenant_session() as s:
        row = s.execute(text("SELECT * FROM auth_user_by_email('ALICE@example.com')")).one()
        assert row.user_id == a.user_id and row.password_hash == "argon2-hash-a"


def test_public_role_sees_only_public_columns(a):
    with public_session() as s:
        assert s.execute(text("SELECT username FROM workspaces")).scalars().all() == ["alice"]
    for query in (
        "SELECT plan_key FROM workspaces",
        "SELECT id FROM users",
        "SELECT id FROM memberships",
        "SELECT user_id FROM user_credentials",
    ):
        with pytest.raises(ProgrammingError, match="permission denied"):
            with public_session() as s:
                s.execute(text(query)).all()


def test_public_role_is_read_only(a):
    with pytest.raises(DBAPIError, match="read-only transaction"):
        with public_session() as s:
            s.execute(text("UPDATE workspaces SET display_name = 'x'"))


def test_public_role_hides_workspaces_without_username():
    workspace_id = uuid4()
    with tenant_session(uuid4(), workspace_id) as s:
        s.add(Workspace(id=workspace_id))
    with public_session() as s:
        assert s.execute(text("SELECT id FROM workspaces")).all() == []

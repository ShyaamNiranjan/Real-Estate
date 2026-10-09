"""Workspace setup: profiles, username holds, roles and permissions.

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE workspace_profiles (
      workspace_id   uuid PRIMARY KEY REFERENCES workspaces(id),
      brokerage_name text NOT NULL DEFAULT '',
      photo_url      text,
      contact_email  citext,
      contact_phone  text,
      whatsapp       text,
      booking_url    text,
      style_preset   text NOT NULL DEFAULT 'noir'
                     CHECK (style_preset IN ('noir', 'coastal', 'terracotta', 'evergreen')),
      compliance     jsonb NOT NULL DEFAULT '{}'::jsonb,
      setup          jsonb NOT NULL DEFAULT '{}'::jsonb,
      updated_at     timestamptz NOT NULL DEFAULT now()
    );

    -- Usernames of deleted workspaces stay blocked until available_at (docs/SCOPE.md 11).
    CREATE TABLE username_holds (
      username       citext PRIMARY KEY,
      workspace_id   uuid,
      released_at    timestamptz NOT NULL DEFAULT now(),
      available_at   timestamptz NOT NULL
    );

    CREATE TABLE roles (
      id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      workspace_id  uuid NOT NULL REFERENCES workspaces(id),
      name          citext NOT NULL CHECK (length(name) BETWEEN 1 AND 40),
      description   text NOT NULL DEFAULT '' CHECK (length(description) <= 200),
      created_at    timestamptz NOT NULL DEFAULT now(),
      updated_at    timestamptz NOT NULL DEFAULT now(),
      UNIQUE (workspace_id, name),
      UNIQUE (workspace_id, id)
    );

    CREATE TABLE role_permissions (
      workspace_id   uuid NOT NULL,
      role_id        uuid NOT NULL,
      permission     text NOT NULL,
      PRIMARY KEY (role_id, permission),
      FOREIGN KEY (workspace_id, role_id) REFERENCES roles (workspace_id, id) ON DELETE CASCADE
    );

    ALTER TABLE memberships ADD COLUMN licence_number text NOT NULL DEFAULT '';
    ALTER TABLE memberships ADD CONSTRAINT memberships_role_same_workspace
      FOREIGN KEY (workspace_id, role_id) REFERENCES roles (workspace_id, id);
    """)

    # Usernames are permanent: the API can set one once, never change or clear it.
    op.execute("""
    CREATE FUNCTION workspaces_username_is_permanent() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF OLD.username IS NOT NULL AND NEW.username IS DISTINCT FROM OLD.username
         AND current_user IN ('app_rw', 'app_public', 'app_hq') THEN
        RAISE EXCEPTION 'username is permanent' USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER workspaces_username_permanent BEFORE UPDATE OF username ON workspaces
      FOR EACH ROW EXECUTE FUNCTION workspaces_username_is_permanent();

    ALTER TABLE workspaces ADD CONSTRAINT workspaces_username_no_double_hyphen CHECK (username !~ '--');
    """)

    for table in ("workspace_profiles", "username_holds", "roles", "role_permissions"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {table}_owner ON {table} TO app_owner USING (true) WITH CHECK (true)")

    op.execute("""
    REVOKE DELETE, TRUNCATE ON workspace_profiles FROM app_rw;
    REVOKE ALL ON username_holds FROM app_rw;

    CREATE POLICY workspace_profiles_rw ON workspace_profiles TO app_rw
      USING (workspace_id = app_workspace_id()) WITH CHECK (workspace_id = app_workspace_id());
    CREATE POLICY roles_rw ON roles TO app_rw
      USING (workspace_id = app_workspace_id()) WITH CHECK (workspace_id = app_workspace_id());
    CREATE POLICY role_permissions_rw ON role_permissions TO app_rw
      USING (workspace_id = app_workspace_id()) WITH CHECK (workspace_id = app_workspace_id());

    GRANT SELECT ON workspace_profiles, username_holds, roles, role_permissions TO app_hq;
    CREATE POLICY workspace_profiles_hq ON workspace_profiles FOR SELECT TO app_hq USING (true);
    CREATE POLICY username_holds_hq ON username_holds FOR SELECT TO app_hq USING (true);
    CREATE POLICY roles_hq ON roles FOR SELECT TO app_hq USING (true);
    CREATE POLICY role_permissions_hq ON role_permissions FOR SELECT TO app_hq USING (true);

    GRANT SELECT (workspace_id, brokerage_name, photo_url, contact_email, contact_phone, whatsapp,
                  booking_url, style_preset, compliance)
      ON workspace_profiles TO app_public;
    CREATE POLICY workspace_profiles_public ON workspace_profiles FOR SELECT TO app_public
      USING (workspace_id IN (SELECT id FROM workspaces));
    """)

    op.execute("""
    CREATE FUNCTION usernames_taken(p_names citext[]) RETURNS SETOF citext
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
      SELECT username FROM workspaces WHERE username = ANY (p_names)
      UNION
      SELECT username FROM username_holds WHERE username = ANY (p_names) AND available_at > now()
    $$;
    REVOKE ALL ON FUNCTION usernames_taken(citext[]) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION usernames_taken(citext[]) TO app_rw;
    """)


def downgrade() -> None:
    op.execute("""
    DROP FUNCTION IF EXISTS usernames_taken(citext[]);
    ALTER TABLE workspaces DROP CONSTRAINT IF EXISTS workspaces_username_no_double_hyphen;
    DROP TRIGGER IF EXISTS workspaces_username_permanent ON workspaces;
    DROP FUNCTION IF EXISTS workspaces_username_is_permanent();
    ALTER TABLE memberships DROP CONSTRAINT IF EXISTS memberships_role_same_workspace;
    ALTER TABLE memberships DROP COLUMN IF EXISTS licence_number;
    DROP TABLE IF EXISTS role_permissions, roles, username_holds, workspace_profiles;
    """)

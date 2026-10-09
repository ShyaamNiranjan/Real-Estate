"""Identity: users, credentials, workspaces, memberships, with row-level security.

Revision ID: 0001
Revises:
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("REVOKE ALL ON alembic_version FROM app_rw, app_public, app_hq")

    op.execute("""
    CREATE FUNCTION app_user_id() RETURNS uuid LANGUAGE sql STABLE AS
      $$ SELECT nullif(current_setting('app.user_id', true), '')::uuid $$;
    CREATE FUNCTION app_workspace_id() RETURNS uuid LANGUAGE sql STABLE AS
      $$ SELECT nullif(current_setting('app.workspace_id', true), '')::uuid $$;
    """)

    op.execute("""
    CREATE TABLE users (
      id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      email             citext NOT NULL UNIQUE,
      email_verified_at timestamptz,
      google_sub        text UNIQUE,
      display_name      text NOT NULL DEFAULT '',
      avatar_url        text,
      created_at        timestamptz NOT NULL DEFAULT now(),
      last_login_at     timestamptz,
      deleted_at        timestamptz,
      CONSTRAINT users_email_shape CHECK (email ~ '^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$' AND length(email) <= 254)
    );

    CREATE TABLE user_credentials (
      user_id       uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
      password_hash text NOT NULL,
      updated_at    timestamptz NOT NULL DEFAULT now()
    );

    CREATE TABLE workspaces (
      id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      username           citext UNIQUE,
      display_name       text NOT NULL DEFAULT '',
      kind               text NOT NULL DEFAULT 'solo',
      country_code       char(2),
      compliance_profile text,
      currency_default   char(3) NOT NULL DEFAULT 'USD',
      area_unit          text NOT NULL DEFAULT 'sqft',
      timezone           text NOT NULL DEFAULT 'UTC',
      plan_key           text,
      subscription_state text NOT NULL DEFAULT 'none',
      site_published_at  timestamptz,
      created_at         timestamptz NOT NULL DEFAULT now(),
      deleted_at         timestamptz,
      CONSTRAINT workspaces_username_shape CHECK (username ~ '^[a-z0-9][a-z0-9-]{1,28}[a-z0-9]$'),
      CONSTRAINT workspaces_kind CHECK (kind IN ('solo', 'team')),
      CONSTRAINT workspaces_area_unit CHECK (area_unit IN ('sqft', 'sqm')),
      CONSTRAINT workspaces_currency CHECK (currency_default ~ '^[A-Z]{3}$'),
      CONSTRAINT workspaces_country CHECK (country_code ~ '^[A-Z]{2}$')
    );

    CREATE TABLE memberships (
      id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      workspace_id uuid NOT NULL REFERENCES workspaces(id),
      user_id      uuid NOT NULL REFERENCES users(id),
      role_id      uuid,
      is_admin     boolean NOT NULL DEFAULT false,
      invited_by   uuid REFERENCES users(id),
      joined_at    timestamptz NOT NULL DEFAULT now(),
      removed_at   timestamptz,
      CONSTRAINT memberships_admin_has_no_role CHECK (NOT (is_admin AND role_id IS NOT NULL))
    );
    CREATE UNIQUE INDEX memberships_one_active ON memberships (workspace_id, user_id) WHERE removed_at IS NULL;
    CREATE UNIQUE INDEX memberships_one_admin ON memberships (workspace_id) WHERE is_admin AND removed_at IS NULL;
    CREATE INDEX memberships_user ON memberships (user_id) WHERE removed_at IS NULL;
    """)

    for table in ("users", "user_credentials", "workspaces", "memberships"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {table}_owner ON {table} TO app_owner USING (true) WITH CHECK (true)")

    # Accounts are soft-deleted; real deletion is a retention job, never the API.
    op.execute("REVOKE DELETE, TRUNCATE ON users, workspaces, memberships FROM app_rw")

    op.execute("""
    CREATE POLICY users_rw_select ON users FOR SELECT TO app_rw USING (
      id = app_user_id()
      OR id IN (SELECT user_id FROM memberships WHERE workspace_id = app_workspace_id() AND removed_at IS NULL)
    );
    CREATE POLICY users_rw_insert ON users FOR INSERT TO app_rw WITH CHECK (id = app_user_id());
    CREATE POLICY users_rw_update ON users FOR UPDATE TO app_rw
      USING (id = app_user_id()) WITH CHECK (id = app_user_id());
    CREATE POLICY users_hq_select ON users FOR SELECT TO app_hq USING (true);
    """)

    # The API can set a password but never read a hash back; sign-in reads it through
    # auth_user_by_email() below.
    op.execute("""
    REVOKE ALL ON user_credentials FROM app_rw;
    GRANT INSERT, UPDATE ON user_credentials TO app_rw;
    GRANT SELECT (user_id) ON user_credentials TO app_rw;
    CREATE POLICY user_credentials_rw ON user_credentials TO app_rw
      USING (user_id = app_user_id()) WITH CHECK (user_id = app_user_id());
    """)

    op.execute("""
    CREATE POLICY workspaces_rw_select ON workspaces FOR SELECT TO app_rw USING (
      id = app_workspace_id()
      OR id IN (SELECT workspace_id FROM memberships WHERE user_id = app_user_id() AND removed_at IS NULL)
    );
    CREATE POLICY workspaces_rw_insert ON workspaces FOR INSERT TO app_rw WITH CHECK (id = app_workspace_id());
    CREATE POLICY workspaces_rw_update ON workspaces FOR UPDATE TO app_rw
      USING (id = app_workspace_id()) WITH CHECK (id = app_workspace_id());
    CREATE POLICY workspaces_hq_select ON workspaces FOR SELECT TO app_hq USING (true);

    GRANT SELECT (id, username, display_name, country_code, compliance_profile, currency_default,
                  area_unit, timezone, site_published_at)
      ON workspaces TO app_public;
    CREATE POLICY workspaces_public_select ON workspaces FOR SELECT TO app_public
      USING (deleted_at IS NULL AND username IS NOT NULL);
    """)

    op.execute("""
    CREATE POLICY memberships_rw_select ON memberships FOR SELECT TO app_rw
      USING (workspace_id = app_workspace_id() OR user_id = app_user_id());
    CREATE POLICY memberships_rw_insert ON memberships FOR INSERT TO app_rw
      WITH CHECK (workspace_id = app_workspace_id());
    CREATE POLICY memberships_rw_update ON memberships FOR UPDATE TO app_rw
      USING (workspace_id = app_workspace_id()) WITH CHECK (workspace_id = app_workspace_id());
    CREATE POLICY memberships_hq_select ON memberships FOR SELECT TO app_hq USING (true);
    """)

    op.execute("GRANT SELECT ON users, workspaces, memberships TO app_hq")

    op.execute("""
    CREATE FUNCTION auth_user_by_email(p_email citext)
    RETURNS TABLE (user_id uuid, password_hash text, email_verified_at timestamptz)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
      SELECT u.id, c.password_hash, u.email_verified_at
      FROM users u LEFT JOIN user_credentials c ON c.user_id = u.id
      WHERE u.email = p_email AND u.deleted_at IS NULL
    $$;

    CREATE FUNCTION auth_user_by_google_sub(p_sub text)
    RETURNS TABLE (user_id uuid, email citext)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
      SELECT u.id, u.email FROM users u WHERE u.google_sub = p_sub AND u.deleted_at IS NULL
    $$;

    REVOKE ALL ON FUNCTION auth_user_by_email(citext), auth_user_by_google_sub(text) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION auth_user_by_email(citext), auth_user_by_google_sub(text) TO app_rw;
    """)


def downgrade() -> None:
    op.execute("""
    DROP FUNCTION IF EXISTS auth_user_by_google_sub(text);
    DROP FUNCTION IF EXISTS auth_user_by_email(citext);
    DROP POLICY IF EXISTS users_rw_select ON users;
    DROP POLICY IF EXISTS workspaces_rw_select ON workspaces;
    DROP TABLE IF EXISTS memberships;
    DROP TABLE IF EXISTS workspaces;
    DROP TABLE IF EXISTS user_credentials;
    DROP TABLE IF EXISTS users;
    DROP FUNCTION IF EXISTS app_workspace_id();
    DROP FUNCTION IF EXISTS app_user_id();
    """)

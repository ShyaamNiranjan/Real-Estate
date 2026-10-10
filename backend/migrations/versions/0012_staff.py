"""Super-Admin: staff accounts with mandatory two-factor, staff roles, staff sessions, the
append-only audit log, and trial invites (docs/SCOPE.md 11, 12, 9.6).

Staff tables are reachable only by app_hq; the customer API role (app_rw) has no access at all.
Customers redeem trial invites through two definer functions.

Revision ID: 0012
Revises: 0011
"""

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

STAFF_TABLES = ("staff_roles", "staff_role_permissions", "staff", "staff_sessions", "audit_log",
                "trial_invites", "trial_redemptions")


def upgrade() -> None:
    op.execute("""
    CREATE TABLE staff_roles (
      id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      name        text NOT NULL UNIQUE CHECK (length(name) BETWEEN 1 AND 60),
      description text NOT NULL DEFAULT '' CHECK (length(description) <= 300),
      created_at  timestamptz NOT NULL DEFAULT now()
    );
    CREATE TABLE staff_role_permissions (
      role_id    uuid NOT NULL REFERENCES staff_roles(id) ON DELETE CASCADE,
      permission text NOT NULL,
      PRIMARY KEY (role_id, permission)
    );
    CREATE TABLE staff (
      id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      email            citext NOT NULL UNIQUE CHECK (length(email) <= 254),
      display_name     text NOT NULL DEFAULT '' CHECK (length(display_name) <= 80),
      is_super         boolean NOT NULL DEFAULT false,
      role_id          uuid REFERENCES staff_roles(id),
      password_hash    text,
      totp_secret      bytea,                 -- encrypted with a key derived from SECRET_KEY
      totp_enabled_at  timestamptz,
      totp_last_step   bigint NOT NULL DEFAULT 0,
      setup_token_hash bytea UNIQUE,
      setup_expires_at timestamptz,
      disabled_at      timestamptz,
      last_login_at    timestamptz,
      created_by       uuid REFERENCES staff(id),
      created_at       timestamptz NOT NULL DEFAULT now(),
      CHECK (NOT is_super OR role_id IS NULL)
    );
    CREATE UNIQUE INDEX staff_one_super ON staff ((true)) WHERE is_super;
    CREATE TABLE staff_sessions (
      id           uuid PRIMARY KEY,
      token_hash   bytea NOT NULL UNIQUE,
      staff_id     uuid NOT NULL REFERENCES staff(id),
      created_at   timestamptz NOT NULL DEFAULT now(),
      last_seen_at timestamptz NOT NULL DEFAULT now(),
      expires_at   timestamptz NOT NULL,
      revoked_at   timestamptz,
      ip_hash      text NOT NULL DEFAULT '',
      user_agent   text NOT NULL DEFAULT ''
    );
    CREATE INDEX staff_sessions_staff ON staff_sessions (staff_id) WHERE revoked_at IS NULL;

    CREATE TABLE audit_log (
      id                  bigserial PRIMARY KEY,
      at                  timestamptz NOT NULL DEFAULT now(),
      staff_id            uuid REFERENCES staff(id),
      staff_email         citext NOT NULL DEFAULT '',
      action              text NOT NULL,
      target_workspace_id uuid,
      target_user_id      uuid,
      reason              text NOT NULL DEFAULT '' CHECK (length(reason) <= 500),
      details             jsonb NOT NULL DEFAULT '{}',
      ip_hash             text NOT NULL DEFAULT ''
    );
    CREATE INDEX audit_log_at ON audit_log (at DESC);
    CREATE INDEX audit_log_workspace ON audit_log (target_workspace_id, at DESC) WHERE target_workspace_id IS NOT NULL;
    CREATE FUNCTION audit_log_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      RAISE EXCEPTION 'audit_log is append-only';
    END $$;
    CREATE TRIGGER audit_log_no_update BEFORE UPDATE OR DELETE ON audit_log
      FOR EACH ROW EXECUTE FUNCTION audit_log_append_only();
    CREATE TRIGGER audit_log_no_truncate BEFORE TRUNCATE ON audit_log
      FOR EACH STATEMENT EXECUTE FUNCTION audit_log_append_only();

    CREATE TABLE trial_invites (
      id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      kind             text NOT NULL CHECK (kind IN ('personal', 'campaign')),
      email            citext CHECK (length(email) <= 254),
      token_hash       bytea UNIQUE,
      code             citext UNIQUE CHECK (code ~ '^[A-Za-z0-9-]{4,30}$'),
      listings_allowed int NOT NULL DEFAULT 3 CHECK (listings_allowed BETWEEN 1 AND 20),
      max_redemptions  int CHECK (max_redemptions > 0),
      redemptions      int NOT NULL DEFAULT 0,
      expires_at       timestamptz NOT NULL,
      note             text NOT NULL DEFAULT '' CHECK (length(note) <= 300),
      created_by       uuid NOT NULL REFERENCES staff(id),
      created_at       timestamptz NOT NULL DEFAULT now(),
      revoked_at       timestamptz,
      CHECK ((kind = 'personal' AND email IS NOT NULL AND token_hash IS NOT NULL AND code IS NULL
              AND coalesce(max_redemptions, 1) = 1)
          OR (kind = 'campaign' AND code IS NOT NULL AND email IS NULL AND token_hash IS NULL))
    );
    CREATE TABLE trial_redemptions (
      id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      invite_id    uuid NOT NULL REFERENCES trial_invites(id),
      workspace_id uuid NOT NULL UNIQUE REFERENCES workspaces(id),
      user_id      uuid NOT NULL UNIQUE REFERENCES users(id),
      redeemed_at  timestamptz NOT NULL DEFAULT now(),
      converted_at timestamptz
    );
    CREATE INDEX trial_redemptions_invite ON trial_redemptions (invite_id);
    """)

    for table in STAFF_TABLES:
        op.execute(f"""
        ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
        CREATE POLICY {table}_owner ON {table} TO app_owner USING (true) WITH CHECK (true);
        CREATE POLICY {table}_hq ON {table} TO app_hq USING (true) WITH CHECK (true);
        REVOKE ALL ON {table} FROM app_rw, app_public;
        """)

    op.execute("""
    GRANT SELECT, INSERT, UPDATE ON staff, staff_sessions, staff_roles, trial_invites TO app_hq;
    GRANT DELETE ON staff_roles TO app_hq;
    GRANT SELECT, INSERT, DELETE ON staff_role_permissions TO app_hq;
    GRANT SELECT ON trial_redemptions TO app_hq;
    GRANT SELECT, INSERT ON audit_log TO app_hq;
    GRANT USAGE ON SEQUENCE audit_log_id_seq TO app_hq;

    -- What a trial link or campaign code shows before redeeming. Only holders of the token or code can ask.
    CREATE FUNCTION trial_invite_lookup(p_token_hash bytea, p_code citext)
    RETURNS TABLE (status text, kind text, email citext, listings_allowed int, expires_at timestamptz)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
      SELECT CASE WHEN t.revoked_at IS NOT NULL THEN 'revoked'
                  WHEN t.expires_at <= now() THEN 'expired'
                  WHEN t.redemptions >= coalesce(t.max_redemptions, 2147483647) THEN 'used'
                  ELSE 'open' END,
             t.kind, t.email, t.listings_allowed, t.expires_at
      FROM trial_invites t
      WHERE (p_token_hash IS NOT NULL AND t.token_hash = p_token_hash)
         OR (p_code IS NOT NULL AND t.code = p_code)
      LIMIT 1
    $$;

    -- Starts a trial for the signed-in Admin's workspace (app.user_id, app.workspace_id). One trial
    -- per person and per workspace, only from the free preview, never after paying.
    CREATE FUNCTION trial_redeem(p_token_hash bytea, p_code citext)
    RETURNS TABLE (status text, listings_allowed int)
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
    DECLARE
      inv trial_invites%ROWTYPE;
      me  uuid := app_user_id();
      ws  uuid := app_workspace_id();
    BEGIN
      IF me IS NULL OR ws IS NULL OR NOT EXISTS (
        SELECT 1 FROM memberships m WHERE m.workspace_id = ws AND m.user_id = me AND m.is_admin AND m.removed_at IS NULL
      ) THEN
        RETURN QUERY SELECT 'forbidden'::text, NULL::int; RETURN;
      END IF;
      SELECT * INTO inv FROM trial_invites t
      WHERE (p_token_hash IS NOT NULL AND t.token_hash = p_token_hash) OR (p_code IS NOT NULL AND t.code = p_code)
      LIMIT 1 FOR UPDATE;
      IF NOT FOUND OR inv.revoked_at IS NOT NULL OR inv.expires_at <= now()
         OR inv.redemptions >= coalesce(inv.max_redemptions, 2147483647) THEN
        RETURN QUERY SELECT 'invalid'::text, NULL::int; RETURN;
      END IF;
      IF inv.kind = 'personal' AND NOT EXISTS (
        SELECT 1 FROM users u WHERE u.id = me AND u.email = inv.email AND u.deleted_at IS NULL
      ) THEN
        RETURN QUERY SELECT 'email_mismatch'::text, NULL::int; RETURN;
      END IF;
      PERFORM 1 FROM workspaces w WHERE w.id = ws FOR UPDATE;
      IF EXISTS (SELECT 1 FROM trial_redemptions r WHERE r.user_id = me OR r.workspace_id = ws) THEN
        RETURN QUERY SELECT 'already_trialed'::text, NULL::int; RETURN;
      END IF;
      IF EXISTS (SELECT 1 FROM workspaces w WHERE w.id = ws AND (w.subscription_state <> 'none' OR w.deleted_at IS NOT NULL))
         OR EXISTS (SELECT 1 FROM subscriptions s WHERE s.workspace_id = ws) THEN
        RETURN QUERY SELECT 'not_eligible'::text, NULL::int; RETURN;
      END IF;
      INSERT INTO trial_redemptions (invite_id, workspace_id, user_id) VALUES (inv.id, ws, me);
      UPDATE trial_invites SET redemptions = redemptions + 1 WHERE id = inv.id;
      UPDATE workspaces SET subscription_state = 'trialing', trial_listing_allowance = inv.listings_allowed
        WHERE id = ws;
      -- The free-preview listing becomes one of the trial listings (60 days live once published).
      UPDATE listings SET is_trial = true WHERE workspace_id = ws AND deleted_at IS NULL;
      RETURN QUERY SELECT 'trialing'::text, inv.listings_allowed;
    END $$;

    -- Called when the current workspace starts paying, for trial conversion figures.
    CREATE FUNCTION trial_converted() RETURNS void
    LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
      UPDATE trial_redemptions SET converted_at = now()
      WHERE workspace_id = app_workspace_id() AND converted_at IS NULL
    $$;

    REVOKE ALL ON FUNCTION trial_invite_lookup(bytea, citext), trial_redeem(bytea, citext), trial_converted()
      FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION trial_invite_lookup(bytea, citext), trial_redeem(bytea, citext), trial_converted()
      TO app_rw;
    """)


def downgrade() -> None:
    op.execute("""
    DROP FUNCTION IF EXISTS trial_converted();
    DROP FUNCTION IF EXISTS trial_redeem(bytea, citext);
    DROP FUNCTION IF EXISTS trial_invite_lookup(bytea, citext);
    DROP TABLE IF EXISTS trial_redemptions, trial_invites, audit_log, staff_sessions, staff,
      staff_role_permissions, staff_roles;
    DROP FUNCTION IF EXISTS audit_log_append_only();
    """)

"""Auth: sessions, email codes, rate limits, legal acceptances.

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

TABLES = ("sessions", "email_codes", "rate_limits", "legal_acceptances")


def upgrade() -> None:
    op.execute("""
    CREATE TABLE sessions (
      id            uuid PRIMARY KEY,
      token_hash    bytea NOT NULL UNIQUE,
      user_id       uuid NOT NULL REFERENCES users(id),
      workspace_id  uuid REFERENCES workspaces(id),
      created_at    timestamptz NOT NULL DEFAULT now(),
      expires_at    timestamptz NOT NULL,
      last_seen_at  timestamptz NOT NULL DEFAULT now(),
      ip_hash       text,
      user_agent    text,
      revoked_at    timestamptz
    );
    CREATE INDEX sessions_user_active ON sessions (user_id) WHERE revoked_at IS NULL;

    CREATE TABLE email_codes (
      id            uuid PRIMARY KEY,
      user_id       uuid NOT NULL REFERENCES users(id),
      purpose       text NOT NULL CHECK (purpose IN ('verify', 'reset', 'email_change')),
      code_hash     bytea NOT NULL,
      target_email  citext,
      attempts      int NOT NULL DEFAULT 0,
      created_at    timestamptz NOT NULL DEFAULT now(),
      expires_at    timestamptz NOT NULL,
      consumed_at   timestamptz
    );
    CREATE INDEX email_codes_lookup ON email_codes (user_id, purpose, created_at DESC);

    CREATE TABLE rate_limits (
      key           text NOT NULL,
      window_start  timestamptz NOT NULL,
      hits          int NOT NULL DEFAULT 0,
      PRIMARY KEY (key, window_start)
    );

    CREATE TABLE legal_acceptances (
      id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      user_id      uuid NOT NULL REFERENCES users(id),
      document     text NOT NULL CHECK (document IN ('terms', 'privacy')),
      version      text NOT NULL,
      method       text NOT NULL,
      ip_hash      text,
      accepted_at  timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX legal_acceptances_user ON legal_acceptances (user_id, document);
    """)

    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {table}_owner ON {table} TO app_owner USING (true) WITH CHECK (true)")

    op.execute("""
    REVOKE DELETE, TRUNCATE ON sessions, email_codes, legal_acceptances FROM app_rw;
    REVOKE UPDATE ON legal_acceptances FROM app_rw;
    REVOKE ALL ON rate_limits FROM app_rw;
    GRANT DELETE ON user_credentials TO app_rw;

    CREATE POLICY sessions_rw ON sessions TO app_rw
      USING (user_id = app_user_id()) WITH CHECK (user_id = app_user_id());
    CREATE POLICY email_codes_rw ON email_codes TO app_rw
      USING (user_id = app_user_id()) WITH CHECK (user_id = app_user_id());
    CREATE POLICY legal_acceptances_rw ON legal_acceptances TO app_rw
      USING (user_id = app_user_id()) WITH CHECK (user_id = app_user_id());
    CREATE POLICY sessions_hq_select ON sessions FOR SELECT TO app_hq USING (true);
    GRANT SELECT ON sessions, legal_acceptances TO app_hq;
    CREATE POLICY legal_acceptances_hq_select ON legal_acceptances FOR SELECT TO app_hq USING (true);
    """)

    # Resolves a session cookie before any user context exists. The workspace is returned
    # only while the user is still an active member of it.
    op.execute("""
    CREATE FUNCTION auth_session_lookup(p_token_hash bytea)
    RETURNS TABLE (session_id uuid, user_id uuid, workspace_id uuid)
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
    BEGIN
      UPDATE sessions s SET last_seen_at = now()
      WHERE s.token_hash = p_token_hash AND s.last_seen_at < now() - interval '10 minutes';

      RETURN QUERY
      SELECT s.id, s.user_id,
             CASE WHEN EXISTS (
               SELECT 1 FROM memberships m
               WHERE m.workspace_id = s.workspace_id AND m.user_id = s.user_id AND m.removed_at IS NULL
             ) THEN s.workspace_id END
      FROM sessions s JOIN users u ON u.id = s.user_id
      WHERE s.token_hash = p_token_hash
        AND s.revoked_at IS NULL AND s.expires_at > now() AND u.deleted_at IS NULL;
    END $$;

    CREATE FUNCTION rate_limit_hit(p_key text, p_window_seconds int, p_limit int)
    RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
    DECLARE
      v_window timestamptz := to_timestamp(floor(extract(epoch FROM now()) / p_window_seconds) * p_window_seconds);
      v_hits int;
    BEGIN
      INSERT INTO rate_limits AS r (key, window_start, hits) VALUES (p_key, v_window, 1)
      ON CONFLICT (key, window_start) DO UPDATE SET hits = r.hits + 1
      RETURNING r.hits INTO v_hits;
      IF random() < 0.01 THEN
        DELETE FROM rate_limits WHERE window_start < now() - interval '1 day';
      END IF;
      RETURN v_hits <= p_limit;
    END $$;

    REVOKE ALL ON FUNCTION auth_session_lookup(bytea), rate_limit_hit(text, int, int) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION auth_session_lookup(bytea), rate_limit_hit(text, int, int) TO app_rw;
    """)


def downgrade() -> None:
    op.execute("""
    DROP FUNCTION IF EXISTS rate_limit_hit(text, int, int);
    DROP FUNCTION IF EXISTS auth_session_lookup(bytea);
    DROP TABLE IF EXISTS legal_acceptances, rate_limits, email_codes, sessions;
    """)

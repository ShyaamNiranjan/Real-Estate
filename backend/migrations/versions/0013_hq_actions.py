"""Super-Admin actions, moderation, announcements, legal versions, platform settings, Admin
transfer and account deletion requests (docs/SCOPE.md 10, 11, 12, 13).

Staff never write customer tables directly: app_hq gets narrow SECURITY DEFINER functions, and
triggers stop the customer API role from touching the staff-only columns (frozen, banned, taken
down, read-only staff sessions, the Admin flag).

Revision ID: 0013
Revises: 0012
"""

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

HQ_FUNCTIONS = ("hq_set_frozen(uuid, boolean, text)", "hq_set_banned(uuid, boolean)",
                "hq_extend_trial(uuid, int, int)", "hq_give_plan(uuid, text)", "hq_end_free_plan(uuid)",
                "hq_schedule_deletion(uuid)", "hq_takedown_listing(uuid, text)", "hq_restore_listing(uuid)",
                "hq_impersonate(uuid, uuid, uuid, bytea, interval)", "hq_revoke_sessions(uuid)")


def upgrade() -> None:
    op.execute("""
    ALTER TABLE workspaces ADD COLUMN frozen_at timestamptz, ADD COLUMN frozen_reason text NOT NULL DEFAULT '',
      ADD COLUMN deletion_requested_at timestamptz;
    ALTER TABLE users ADD COLUMN banned_at timestamptz;
    ALTER TABLE listings ADD COLUMN taken_down_at timestamptz, ADD COLUMN takedown_reason text NOT NULL DEFAULT '';
    ALTER TABLE sessions ADD COLUMN read_only boolean NOT NULL DEFAULT false,
      ADD COLUMN impersonator_staff_id uuid REFERENCES staff(id);

    -- Frozen accounts and taken-down listings disappear from public pages.
    DROP POLICY workspaces_public_select ON workspaces;
    CREATE POLICY workspaces_public_select ON workspaces FOR SELECT TO app_public
      USING (deleted_at IS NULL AND username IS NOT NULL AND frozen_at IS NULL);
    DROP POLICY listings_public ON listings;
    CREATE POLICY listings_public ON listings FOR SELECT TO app_public
      USING (status IN ('published', 'sold') AND deleted_at IS NULL AND live IS NOT NULL AND taken_down_at IS NULL
             AND workspace_id IN (SELECT id FROM workspaces));

    -- Staff-only columns: the customer API role may never change them.
    CREATE FUNCTION guard_staff_columns() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF current_user NOT IN ('app_rw', 'app_public') THEN
        RETURN NEW;
      END IF;
      -- Nested IFs: PL/pgSQL can only resolve NEW.<column> on the table that has it.
      IF TG_TABLE_NAME = 'workspaces' THEN
        IF NEW.frozen_at IS DISTINCT FROM OLD.frozen_at
           OR NEW.deletion_requested_at IS DISTINCT FROM OLD.deletion_requested_at THEN
          RAISE EXCEPTION 'staff-only column';
        END IF;
      ELSIF TG_TABLE_NAME = 'users' THEN
        IF NEW.banned_at IS DISTINCT FROM OLD.banned_at THEN
          RAISE EXCEPTION 'staff-only column';
        END IF;
      ELSIF TG_TABLE_NAME = 'listings' THEN
        IF NEW.taken_down_at IS DISTINCT FROM OLD.taken_down_at THEN
          RAISE EXCEPTION 'staff-only column';
        END IF;
      ELSIF TG_TABLE_NAME = 'memberships' THEN
        IF NEW.is_admin IS DISTINCT FROM OLD.is_admin THEN
          RAISE EXCEPTION 'the Admin changes only through admin_transfer';
        END IF;
      ELSIF TG_TABLE_NAME = 'sessions' THEN
        IF NEW.read_only IS DISTINCT FROM OLD.read_only
           OR NEW.impersonator_staff_id IS DISTINCT FROM OLD.impersonator_staff_id THEN
          RAISE EXCEPTION 'staff-only column';
        END IF;
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER workspaces_guard BEFORE UPDATE ON workspaces FOR EACH ROW EXECUTE FUNCTION guard_staff_columns();
    CREATE TRIGGER users_guard BEFORE UPDATE ON users FOR EACH ROW EXECUTE FUNCTION guard_staff_columns();
    CREATE TRIGGER listings_guard BEFORE UPDATE ON listings FOR EACH ROW EXECUTE FUNCTION guard_staff_columns();
    CREATE TRIGGER memberships_guard BEFORE UPDATE ON memberships FOR EACH ROW EXECUTE FUNCTION guard_staff_columns();
    CREATE TRIGGER sessions_guard BEFORE UPDATE ON sessions FOR EACH ROW EXECUTE FUNCTION guard_staff_columns();
    CREATE FUNCTION sessions_insert_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF current_user = 'app_rw' AND (NEW.read_only OR NEW.impersonator_staff_id IS NOT NULL) THEN
        RAISE EXCEPTION 'staff-only column';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER sessions_insert_guard BEFORE INSERT ON sessions FOR EACH ROW EXECUTE FUNCTION sessions_insert_guard();

    -- Session lookup now reports read-only (staff "log in as them") sessions and refuses banned users.
    DROP FUNCTION auth_session_lookup(bytea);
    CREATE FUNCTION auth_session_lookup(p_token_hash bytea)
    RETURNS TABLE (session_id uuid, user_id uuid, workspace_id uuid, read_only boolean)
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
    BEGIN
      UPDATE sessions s SET last_seen_at = now()
      WHERE s.token_hash = p_token_hash AND s.last_seen_at < now() - interval '10 minutes';

      RETURN QUERY
      SELECT s.id, s.user_id,
             CASE WHEN EXISTS (
               SELECT 1 FROM memberships m
               WHERE m.workspace_id = s.workspace_id AND m.user_id = s.user_id AND m.removed_at IS NULL
             ) THEN s.workspace_id END,
             s.read_only
      FROM sessions s JOIN users u ON u.id = s.user_id
      WHERE s.token_hash = p_token_hash
        AND s.revoked_at IS NULL AND s.expires_at > now() AND u.deleted_at IS NULL AND u.banned_at IS NULL;
    END $$;
    REVOKE ALL ON FUNCTION auth_session_lookup(bytea) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION auth_session_lookup(bytea) TO app_rw;

    -- Reports from "Report this listing" on public pages.
    CREATE TABLE listing_reports (
      id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      workspace_id   uuid NOT NULL REFERENCES workspaces(id),
      listing_id     uuid NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
      category       text NOT NULL CHECK (category IN ('copyright', 'discrimination', 'fraud', 'inappropriate',
                                                      'privacy', 'other')),
      details        text NOT NULL CHECK (length(details) BETWEEN 1 AND 4000),
      reporter_name  text NOT NULL DEFAULT '' CHECK (length(reporter_name) <= 120),
      reporter_email citext NOT NULL CHECK (length(reporter_email) <= 254),
      ip_hash        text NOT NULL DEFAULT '',
      status         text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'dismissed', 'actioned')),
      created_at     timestamptz NOT NULL DEFAULT now(),
      resolved_at    timestamptz,
      resolved_by    uuid REFERENCES staff(id),
      resolution     text NOT NULL DEFAULT '' CHECK (length(resolution) <= 1000)
    );
    CREATE INDEX listing_reports_open ON listing_reports (created_at) WHERE status = 'open';

    CREATE TABLE announcements (
      id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      title       text NOT NULL CHECK (length(title) BETWEEN 1 AND 120),
      body        text NOT NULL CHECK (length(body) BETWEEN 1 AND 4000),
      channel     text NOT NULL CHECK (channel IN ('banner', 'email', 'both')),
      audience    text NOT NULL DEFAULT 'all' CHECK (audience IN ('all', 'paying', 'trialing')),
      starts_at   timestamptz NOT NULL DEFAULT now(),
      ends_at     timestamptz,
      emails_sent int NOT NULL DEFAULT 0,
      created_by  uuid NOT NULL REFERENCES staff(id),
      created_at  timestamptz NOT NULL DEFAULT now()
    );

    CREATE TABLE legal_versions (
      document     text NOT NULL CHECK (document IN ('terms', 'privacy')),
      version      text NOT NULL CHECK (length(version) BETWEEN 1 AND 40),
      material     boolean NOT NULL DEFAULT false,
      summary      text NOT NULL DEFAULT '' CHECK (length(summary) <= 2000),
      published_at timestamptz NOT NULL DEFAULT now(),
      created_by   uuid REFERENCES staff(id),
      PRIMARY KEY (document, version)
    );
    INSERT INTO legal_versions (document, version, published_at)
      VALUES ('terms', '2026-10-draft', '2026-10-01'), ('privacy', '2026-10-draft', '2026-10-01');

    CREATE TABLE platform_settings (
      key        text PRIMARY KEY,
      value      jsonb NOT NULL,
      updated_at timestamptz NOT NULL DEFAULT now()
    );
    INSERT INTO platform_settings (key, value) VALUES ('trial_video_max_mb', '500');
    """)

    for table in ("listing_reports", "announcements", "legal_versions", "platform_settings"):
        op.execute(f"""
        ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
        CREATE POLICY {table}_owner ON {table} TO app_owner USING (true) WITH CHECK (true);
        CREATE POLICY {table}_hq ON {table} TO app_hq USING (true) WITH CHECK (true);
        REVOKE ALL ON {table} FROM app_rw, app_public;
        """)

    op.execute("""
    GRANT SELECT, UPDATE ON listing_reports TO app_hq;
    GRANT SELECT, INSERT, UPDATE ON announcements, legal_versions, platform_settings TO app_hq;
    GRANT SELECT ON legal_versions, platform_settings TO app_rw, app_public;
    CREATE POLICY legal_versions_read ON legal_versions FOR SELECT TO app_rw, app_public USING (true);
    CREATE POLICY platform_settings_read ON platform_settings FOR SELECT TO app_rw USING (true);
    GRANT SELECT (id, title, body, channel, audience, starts_at, ends_at) ON announcements TO app_rw;
    CREATE POLICY announcements_rw ON announcements FOR SELECT TO app_rw USING (
      channel IN ('banner', 'both') AND starts_at <= now() AND (ends_at IS NULL OR ends_at > now())
      AND (audience = 'all' OR EXISTS (
        SELECT 1 FROM workspaces w WHERE w.id = app_workspace_id()
          AND ((audience = 'paying' AND w.subscription_state IN ('active', 'grace'))
            OR (audience = 'trialing' AND w.subscription_state = 'trialing')))));

    GRANT UPDATE, INSERT ON plans TO app_hq;
    CREATE POLICY plans_hq_write ON plans TO app_hq USING (true) WITH CHECK (true);

    -- Public "Report this listing". Only live listings can be reported.
    CREATE FUNCTION listing_report_create(p_username citext, p_slug text, p_category text, p_details text,
                                          p_name text, p_email citext, p_ip_hash text)
    RETURNS uuid LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
      INSERT INTO listing_reports (workspace_id, listing_id, category, details, reporter_name, reporter_email, ip_hash)
      SELECT l.workspace_id, l.id, p_category, p_details, p_name, p_email, p_ip_hash
      FROM listings l JOIN workspaces w ON w.id = l.workspace_id
      WHERE w.username = p_username AND w.deleted_at IS NULL AND w.frozen_at IS NULL AND l.live_slug = p_slug
        AND l.status IN ('published', 'sold') AND l.deleted_at IS NULL AND l.taken_down_at IS NULL
      LIMIT 1
      RETURNING id
    $$;
    REVOKE ALL ON FUNCTION listing_report_create(citext, text, text, text, text, citext, text) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION listing_report_create(citext, text, text, text, text, citext, text) TO app_rw;

    -- ----- staff actions (app_hq only; the HQ API checks staff permissions and writes the audit log) -----

    CREATE FUNCTION hq_set_frozen(p_ws uuid, p_frozen boolean, p_reason text) RETURNS boolean
    LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
      UPDATE workspaces SET frozen_at = CASE WHEN p_frozen THEN coalesce(frozen_at, now()) END,
                            frozen_reason = CASE WHEN p_frozen THEN p_reason ELSE '' END
      WHERE id = p_ws AND deleted_at IS NULL
      RETURNING true
    $$;

    CREATE FUNCTION hq_set_banned(p_user uuid, p_banned boolean) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
    BEGIN
      UPDATE users SET banned_at = CASE WHEN p_banned THEN coalesce(banned_at, now()) END
      WHERE id = p_user AND deleted_at IS NULL;
      IF NOT FOUND THEN RETURN false; END IF;
      IF p_banned THEN
        UPDATE sessions SET revoked_at = now() WHERE user_id = p_user AND revoked_at IS NULL;
        UPDATE workspaces SET frozen_at = coalesce(frozen_at, now()), frozen_reason = 'Account banned'
        WHERE id IN (SELECT workspace_id FROM memberships WHERE user_id = p_user AND is_admin AND removed_at IS NULL);
      END IF;
      RETURN true;
    END $$;

    CREATE FUNCTION hq_extend_trial(p_ws uuid, p_days int, p_extra_listings int) RETURNS text
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
    BEGIN
      PERFORM 1 FROM workspaces WHERE id = p_ws AND deleted_at IS NULL AND subscription_state = 'trialing' FOR UPDATE;
      IF NOT FOUND THEN RETURN 'not_trialing'; END IF;
      UPDATE listings SET trial_expires_at = trial_expires_at + make_interval(days => p_days)
      WHERE workspace_id = p_ws AND is_trial AND trial_expires_at IS NOT NULL AND deleted_at IS NULL;
      UPDATE workspaces SET trial_listing_allowance = coalesce(trial_listing_allowance, 3) + p_extra_listings
      WHERE id = p_ws;
      RETURN 'extended';
    END $$;

    -- A complimentary plan: active with no subscription at the merchant of record.
    CREATE FUNCTION hq_give_plan(p_ws uuid, p_plan text) RETURNS text
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
    BEGIN
      PERFORM 1 FROM workspaces WHERE id = p_ws AND deleted_at IS NULL FOR UPDATE;
      IF NOT FOUND THEN RETURN 'not_found'; END IF;
      IF NOT EXISTS (SELECT 1 FROM plans WHERE key = p_plan) THEN RETURN 'invalid_plan'; END IF;
      IF EXISTS (SELECT 1 FROM subscriptions WHERE workspace_id = p_ws AND status IN ('active', 'past_due')) THEN
        RETURN 'has_subscription';
      END IF;
      UPDATE workspaces SET plan_key = p_plan, subscription_state = 'active', lapsed_at = NULL, grace_ends_at = NULL,
             offline_at = NULL, delete_after = NULL, deletion_requested_at = NULL,
             kind = CASE WHEN p_plan IN ('team', 'brokerage') THEN 'team' ELSE kind END
      WHERE id = p_ws;
      DELETE FROM lifecycle_notices WHERE workspace_id = p_ws
        AND (notice LIKE 'grace%' OR notice LIKE 'delete%' OR notice = 'offline');
      RETURN 'active';
    END $$;

    -- Ends a complimentary plan the same way a lapsed subscription ends: 30 days' grace.
    CREATE FUNCTION hq_end_free_plan(p_ws uuid) RETURNS text
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
    BEGIN
      PERFORM 1 FROM workspaces WHERE id = p_ws AND deleted_at IS NULL AND subscription_state = 'active' FOR UPDATE;
      IF NOT FOUND THEN RETURN 'not_active'; END IF;
      IF EXISTS (SELECT 1 FROM subscriptions WHERE workspace_id = p_ws AND status IN ('active', 'past_due')) THEN
        RETURN 'has_subscription';
      END IF;
      UPDATE workspaces SET subscription_state = 'grace', lapsed_at = now(), grace_ends_at = now() + interval '30 days',
             delete_after = now() + interval '182 days'
      WHERE id = p_ws;
      RETURN 'grace';
    END $$;

    -- Deletion on request: offline now, permanently deleted by the lifecycle job after 7 days.
    CREATE FUNCTION hq_schedule_deletion(p_ws uuid) RETURNS text
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
    BEGIN
      PERFORM 1 FROM workspaces WHERE id = p_ws AND deleted_at IS NULL FOR UPDATE;
      IF NOT FOUND THEN RETURN 'not_found'; END IF;
      IF EXISTS (SELECT 1 FROM subscriptions WHERE workspace_id = p_ws AND status IN ('active', 'past_due')
                 AND NOT cancel_at_period_end) THEN
        RETURN 'has_subscription';
      END IF;
      UPDATE workspaces SET subscription_state = 'offline', lapsed_at = coalesce(lapsed_at, now()),
             grace_ends_at = NULL, offline_at = now(), delete_after = now() + interval '7 days',
             deletion_requested_at = now()
      WHERE id = p_ws;
      RETURN 'scheduled';
    END $$;

    CREATE FUNCTION hq_takedown_listing(p_listing uuid, p_reason text) RETURNS uuid
    LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
      UPDATE listings SET taken_down_at = now(), takedown_reason = p_reason, status = 'draft',
             changes_submitted_at = NULL
      WHERE id = p_listing AND deleted_at IS NULL
      RETURNING workspace_id
    $$;

    CREATE FUNCTION hq_restore_listing(p_listing uuid) RETURNS uuid
    LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
      UPDATE listings SET taken_down_at = NULL, takedown_reason = ''
      WHERE id = p_listing AND taken_down_at IS NOT NULL
      RETURNING workspace_id
    $$;

    CREATE FUNCTION hq_revoke_sessions(p_user uuid) RETURNS int
    LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
      WITH r AS (UPDATE sessions SET revoked_at = now() WHERE user_id = p_user AND revoked_at IS NULL RETURNING 1)
      SELECT count(*)::int FROM r
    $$;

    -- "Log in as them": a short read-only session for the workspace's Admin.
    CREATE FUNCTION hq_impersonate(p_ws uuid, p_staff uuid, p_session uuid, p_token_hash bytea, p_ttl interval)
    RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
    DECLARE
      admin_user uuid;
    BEGIN
      SELECT m.user_id INTO admin_user FROM memberships m JOIN workspaces w ON w.id = m.workspace_id
      WHERE m.workspace_id = p_ws AND m.is_admin AND m.removed_at IS NULL AND w.deleted_at IS NULL;
      IF admin_user IS NULL THEN RETURN NULL; END IF;
      INSERT INTO sessions (id, token_hash, user_id, workspace_id, expires_at, read_only, impersonator_staff_id,
                            user_agent)
      VALUES (p_session, p_token_hash, admin_user, p_ws, now() + p_ttl, true, p_staff, 'Scrollwalk HQ');
      RETURN admin_user;
    END $$;
    """)
    functions = ", ".join(HQ_FUNCTIONS)
    op.execute(f"REVOKE ALL ON FUNCTION {functions} FROM PUBLIC; GRANT EXECUTE ON FUNCTION {functions} TO app_hq;")

    op.execute("""
    -- Customer side: hand the Admin role to another member (Admin only).
    CREATE FUNCTION admin_transfer(p_member uuid, p_my_role uuid) RETURNS text
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
    DECLARE
      ws uuid := app_workspace_id();
      me memberships%ROWTYPE;
    BEGIN
      SELECT * INTO me FROM memberships
      WHERE workspace_id = ws AND user_id = app_user_id() AND is_admin AND removed_at IS NULL FOR UPDATE;
      IF NOT FOUND THEN RETURN 'forbidden'; END IF;
      IF p_member = me.id OR NOT EXISTS (
        SELECT 1 FROM memberships m JOIN users u ON u.id = m.user_id
        WHERE m.id = p_member AND m.workspace_id = ws AND m.removed_at IS NULL
          AND u.deleted_at IS NULL AND u.banned_at IS NULL AND u.email_verified_at IS NOT NULL
      ) THEN
        RETURN 'bad_member';
      END IF;
      IF NOT EXISTS (SELECT 1 FROM roles WHERE id = p_my_role AND workspace_id = ws) THEN
        RETURN 'bad_role';
      END IF;
      UPDATE memberships SET is_admin = false, role_id = p_my_role WHERE id = me.id;
      UPDATE memberships SET is_admin = true, role_id = NULL WHERE id = p_member;
      RETURN 'transferred';
    END $$;

    -- Customer side: the Admin asks for the workspace to be deleted (same rules as staff deletion).
    CREATE FUNCTION workspace_request_deletion() RETURNS text
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
    BEGIN
      IF NOT app_member_is_admin() THEN RETURN 'forbidden'; END IF;
      RETURN hq_schedule_deletion(app_workspace_id());
    END $$;
    REVOKE ALL ON FUNCTION admin_transfer(uuid, uuid), workspace_request_deletion() FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION admin_transfer(uuid, uuid), workspace_request_deletion() TO app_rw;
    """)


def downgrade() -> None:
    functions = ", ".join(HQ_FUNCTIONS)
    op.execute(f"""
    DROP FUNCTION IF EXISTS workspace_request_deletion(), admin_transfer(uuid, uuid), {functions},
      listing_report_create(citext, text, text, text, text, citext, text);
    DROP POLICY IF EXISTS plans_hq_write ON plans;
    REVOKE UPDATE, INSERT ON plans FROM app_hq;
    DROP TABLE IF EXISTS platform_settings, legal_versions, announcements, listing_reports;

    DROP FUNCTION auth_session_lookup(bytea);
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
    REVOKE ALL ON FUNCTION auth_session_lookup(bytea) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION auth_session_lookup(bytea) TO app_rw;

    DROP TRIGGER IF EXISTS sessions_insert_guard ON sessions;
    DROP FUNCTION IF EXISTS sessions_insert_guard();
    DROP TRIGGER IF EXISTS workspaces_guard ON workspaces;
    DROP TRIGGER IF EXISTS users_guard ON users;
    DROP TRIGGER IF EXISTS listings_guard ON listings;
    DROP TRIGGER IF EXISTS memberships_guard ON memberships;
    DROP TRIGGER IF EXISTS sessions_guard ON sessions;
    DROP FUNCTION IF EXISTS guard_staff_columns();

    DROP POLICY listings_public ON listings;
    CREATE POLICY listings_public ON listings FOR SELECT TO app_public
      USING (status IN ('published', 'sold') AND deleted_at IS NULL AND live IS NOT NULL
             AND workspace_id IN (SELECT id FROM workspaces));
    DROP POLICY workspaces_public_select ON workspaces;
    CREATE POLICY workspaces_public_select ON workspaces FOR SELECT TO app_public
      USING (deleted_at IS NULL AND username IS NOT NULL);

    ALTER TABLE sessions DROP COLUMN IF EXISTS impersonator_staff_id, DROP COLUMN IF EXISTS read_only;
    ALTER TABLE listings DROP COLUMN IF EXISTS taken_down_at, DROP COLUMN IF EXISTS takedown_reason;
    ALTER TABLE users DROP COLUMN IF EXISTS banned_at;
    ALTER TABLE workspaces DROP COLUMN IF EXISTS frozen_at, DROP COLUMN IF EXISTS frozen_reason,
      DROP COLUMN IF EXISTS deletion_requested_at;
    """)

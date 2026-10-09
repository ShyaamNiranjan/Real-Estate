"""Cookieless analytics and seller reports.

Revision ID: 0008
Revises: 0007
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

OWN_LISTING = """listing_id IN (SELECT l.id FROM listings l WHERE l.workspace_id = app_workspace_id()
                   AND (l.agent_member_id = app_membership_id()
                        OR (l.agent_member_id IS NULL AND l.created_by = app_user_id())))"""


def upgrade() -> None:
    op.execute(f"""
    -- One random salt per day, deleted after a day: yesterday's visitor hashes can't be linked
    -- to today's or traced back to anyone.
    CREATE TABLE analytics_salts (
      day   date PRIMARY KEY,
      salt  bytea NOT NULL
    );
    ALTER TABLE analytics_salts ENABLE ROW LEVEL SECURITY;
    ALTER TABLE analytics_salts FORCE ROW LEVEL SECURITY;
    CREATE POLICY analytics_salts_owner ON analytics_salts TO app_owner USING (true) WITH CHECK (true);

    CREATE FUNCTION analytics_salt() RETURNS bytea
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
    DECLARE s bytea;
    BEGIN
      DELETE FROM analytics_salts WHERE day < (now() AT TIME ZONE 'UTC')::date - 1;
      INSERT INTO analytics_salts (day, salt) VALUES ((now() AT TIME ZONE 'UTC')::date, gen_random_bytes(32))
        ON CONFLICT (day) DO NOTHING;
      SELECT salt INTO s FROM analytics_salts WHERE day = (now() AT TIME ZONE 'UTC')::date;
      RETURN s;
    END $$;
    REVOKE ALL ON FUNCTION analytics_salt() FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION analytics_salt() TO app_rw;

    CREATE TABLE analytics_events (
      id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      workspace_id  uuid NOT NULL REFERENCES workspaces(id),
      listing_id    uuid,
      day           date NOT NULL,
      view_id       uuid NOT NULL,
      visitor_hash  text NOT NULL CHECK (length(visitor_hash) = 32),
      source        text NOT NULL CHECK (source IN ('link', 'search', 'internal')),
      device        text NOT NULL CHECK (device IN ('mobile', 'tablet', 'desktop')),
      country       text NOT NULL DEFAULT '' CHECK (length(country) <= 2),
      city          text NOT NULL DEFAULT '' CHECK (length(city) <= 80),
      event         text NOT NULL CHECK (event IN ('pageview', 'leave', 'walk_depth', 'gallery_open',
                      'floor_plan_view', 'enquiry_click', 'phone_tap', 'whatsapp_tap', 'booking_click')),
      value         real,
      path          text NOT NULL DEFAULT '' CHECK (length(path) <= 200),
      created_at    timestamptz NOT NULL DEFAULT now(),
      FOREIGN KEY (workspace_id, listing_id) REFERENCES listings (workspace_id, id)
    );
    CREATE INDEX analytics_events_workspace_day ON analytics_events (workspace_id, day);
    CREATE INDEX analytics_events_listing_day ON analytics_events (listing_id, day);

    ALTER TABLE analytics_events ENABLE ROW LEVEL SECURITY;
    ALTER TABLE analytics_events FORCE ROW LEVEL SECURITY;
    CREATE POLICY analytics_events_owner ON analytics_events TO app_owner USING (true) WITH CHECK (true);
    CREATE POLICY analytics_events_rw_insert ON analytics_events FOR INSERT TO app_rw
      WITH CHECK (workspace_id = app_workspace_id());
    -- Readable by members allowed to see all analytics, by agents for their own listings, and
    -- for one listing only when the server has verified a seller report link for it.
    CREATE POLICY analytics_events_rw_select ON analytics_events FOR SELECT TO app_rw USING (
      workspace_id = app_workspace_id() AND (
        app_member_can('analytics.view_all')
        OR (app_member_can('analytics.view_own') AND {OWN_LISTING})
        OR listing_id = nullif(current_setting('app.report_listing_id', true), '')::uuid
      )
    );
    CREATE POLICY analytics_events_hq ON analytics_events FOR SELECT TO app_hq USING (true);
    GRANT SELECT ON analytics_events TO app_hq;
    REVOKE UPDATE, DELETE, TRUNCATE ON analytics_events FROM app_rw;

    CREATE TABLE seller_reports (
      id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      workspace_id  uuid NOT NULL REFERENCES workspaces(id),
      listing_id    uuid NOT NULL,
      token_hash    bytea NOT NULL UNIQUE,
      created_by    uuid REFERENCES users(id),
      created_at    timestamptz NOT NULL DEFAULT now(),
      revoked_at    timestamptz,
      FOREIGN KEY (workspace_id, listing_id) REFERENCES listings (workspace_id, id)
    );
    ALTER TABLE seller_reports ENABLE ROW LEVEL SECURITY;
    ALTER TABLE seller_reports FORCE ROW LEVEL SECURITY;
    CREATE POLICY seller_reports_owner ON seller_reports TO app_owner USING (true) WITH CHECK (true);
    CREATE POLICY seller_reports_rw ON seller_reports TO app_rw
      USING (workspace_id = app_workspace_id() AND app_member_can('analytics.seller_reports'))
      WITH CHECK (workspace_id = app_workspace_id() AND app_member_can('analytics.seller_reports'));
    CREATE POLICY seller_reports_hq ON seller_reports FOR SELECT TO app_hq USING (true);
    GRANT SELECT ON seller_reports TO app_hq;
    REVOKE DELETE, TRUNCATE ON seller_reports FROM app_rw;

    -- Opening a report link: finds the listing for a token before any workspace context exists.
    CREATE FUNCTION seller_report_lookup(p_token_hash bytea)
    RETURNS TABLE (workspace_id uuid, listing_id uuid)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
      SELECT r.workspace_id, r.listing_id FROM seller_reports r
      JOIN listings l ON l.id = r.listing_id AND l.deleted_at IS NULL
      WHERE r.token_hash = p_token_hash AND r.revoked_at IS NULL
    $$;
    REVOKE ALL ON FUNCTION seller_report_lookup(bytea) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION seller_report_lookup(bytea) TO app_rw;

    -- Enquiry counts for analytics, without exposing buyers' details to people who may only see
    -- numbers. Limited to the current workspace and to the listings the caller passes in.
    CREATE FUNCTION enquiry_daily_counts(p_listing_ids uuid[], p_site boolean, p_from date)
    RETURNS TABLE (day date, n bigint)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
      SELECT (created_at AT TIME ZONE 'UTC')::date, count(*) FROM enquiries
      WHERE workspace_id = app_workspace_id() AND created_at >= p_from
        AND (listing_id = ANY (p_listing_ids) OR (p_site AND listing_id IS NULL))
      GROUP BY 1
    $$;
    REVOKE ALL ON FUNCTION enquiry_daily_counts(uuid[], boolean, date) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION enquiry_daily_counts(uuid[], boolean, date) TO app_rw;

    -- Weekly summary job: workspaces with visits in the period and who should receive the email.
    CREATE FUNCTION weekly_summary_recipients(p_from date)
    RETURNS TABLE (workspace_id uuid, user_id uuid, email citext)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
      SELECT DISTINCT m.workspace_id, u.id, u.email FROM memberships m
      JOIN users u ON u.id = m.user_id AND u.deleted_at IS NULL
      JOIN workspaces w ON w.id = m.workspace_id AND w.deleted_at IS NULL AND w.subscription_state <> 'offline'
      WHERE m.removed_at IS NULL
        AND EXISTS (SELECT 1 FROM analytics_events e WHERE e.workspace_id = m.workspace_id AND e.day >= p_from)
        AND (m.is_admin OR EXISTS (SELECT 1 FROM role_permissions rp WHERE rp.role_id = m.role_id
                                   AND rp.permission IN ('analytics.view_all', 'analytics.view_own')))
    $$;
    REVOKE ALL ON FUNCTION weekly_summary_recipients(date) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION weekly_summary_recipients(date) TO app_rw;
    """)


def downgrade() -> None:
    op.execute("""
    DROP FUNCTION IF EXISTS weekly_summary_recipients(date);
    DROP FUNCTION IF EXISTS enquiry_daily_counts(uuid[], boolean, date);
    DROP FUNCTION IF EXISTS seller_report_lookup(bytea);
    DROP TABLE IF EXISTS seller_reports, analytics_events;
    DROP FUNCTION IF EXISTS analytics_salt();
    DROP TABLE IF EXISTS analytics_salts;
    """)

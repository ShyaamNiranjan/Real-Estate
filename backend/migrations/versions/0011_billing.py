"""Billing and account lifecycle: plans, subscriptions, provider events, lapse timeline, exports,
permanent deletion and username holds (docs/SCOPE.md 11).

Revision ID: 0011
Revises: 0010
"""

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    -- Plans are product data, readable by everyone; limits are placeholders until pricing is set.
    CREATE TABLE plans (
      key                 text PRIMARY KEY CHECK (key ~ '^[a-z0-9_]{2,30}$'),
      name                text NOT NULL CHECK (length(name) BETWEEN 1 AND 40),
      seats               int NOT NULL CHECK (seats >= 1),
      listing_limit       int CHECK (listing_limit >= 0),
      features            jsonb NOT NULL DEFAULT '[]'::jsonb,
      price_month         numeric(10, 2),
      price_year          numeric(10, 2),
      currency            char(3) NOT NULL DEFAULT 'USD',
      provider_price_ids  jsonb NOT NULL DEFAULT '{}'::jsonb,
      sales_led           boolean NOT NULL DEFAULT false,
      is_public           boolean NOT NULL DEFAULT true,
      sort_order          int NOT NULL DEFAULT 0,
      updated_at          timestamptz NOT NULL DEFAULT now()
    );
    INSERT INTO plans (key, name, seats, listing_limit, features, sales_led, sort_order) VALUES
      ('agent', 'Agent', 1, 15, '["Your own site", "Walkthrough listings", "Enquiries and analytics"]', false, 1),
      ('team', 'Team', 10, 50, '["Everything in Agent", "Up to 10 people", "Roles and approvals"]', false, 2),
      ('brokerage', 'Brokerage', 50, NULL,
       '["Everything in Team", "Up to 50 people", "Unlimited listings", "Dedicated onboarding"]', true, 3);
    UPDATE workspaces SET plan_key = NULL WHERE plan_key IS NOT NULL AND plan_key NOT IN (SELECT key FROM plans);
    ALTER TABLE workspaces ADD CONSTRAINT workspaces_plan FOREIGN KEY (plan_key) REFERENCES plans (key);

    ALTER TABLE plans ENABLE ROW LEVEL SECURITY;
    ALTER TABLE plans FORCE ROW LEVEL SECURITY;
    CREATE POLICY plans_owner ON plans TO app_owner USING (true) WITH CHECK (true);
    CREATE POLICY plans_rw ON plans FOR SELECT TO app_rw USING (true);
    CREATE POLICY plans_public ON plans FOR SELECT TO app_public USING (is_public);
    CREATE POLICY plans_hq ON plans FOR SELECT TO app_hq USING (true);
    REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON plans FROM app_rw;
    GRANT SELECT ON plans TO app_public, app_hq;

    ALTER TABLE workspaces
      ADD COLUMN lapsed_at     timestamptz,
      ADD COLUMN grace_ends_at timestamptz,
      ADD COLUMN offline_at    timestamptz,
      ADD COLUMN delete_after  timestamptz;

    CREATE TABLE subscriptions (
      workspace_id              uuid PRIMARY KEY REFERENCES workspaces(id),
      provider                  text NOT NULL,
      provider_customer_id      text NOT NULL DEFAULT '',
      provider_subscription_id  text NOT NULL,
      plan_key                  text NOT NULL REFERENCES plans(key),
      billing_interval          text NOT NULL CHECK (billing_interval IN ('month', 'year')),
      status                    text NOT NULL CHECK (status IN ('active', 'past_due', 'canceled', 'expired')),
      current_period_end        timestamptz,
      cancel_at_period_end      boolean NOT NULL DEFAULT false,
      last_event_at             timestamptz NOT NULL,
      created_at                timestamptz NOT NULL DEFAULT now(),
      updated_at                timestamptz NOT NULL DEFAULT now(),
      UNIQUE (provider, provider_subscription_id)
    );

    -- Provider webhooks, kept for idempotency and support. Never readable by the API role.
    CREATE TABLE billing_events (
      id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      provider           text NOT NULL,
      provider_event_id  text NOT NULL,
      type               text NOT NULL,
      workspace_id       uuid REFERENCES workspaces(id),
      payload            jsonb NOT NULL,
      received_at        timestamptz NOT NULL DEFAULT now(),
      processed_at       timestamptz,
      error              text NOT NULL DEFAULT '',
      UNIQUE (provider, provider_event_id)
    );

    -- Each reminder email goes out once per lapse (re-armed when the account is paid again).
    CREATE TABLE lifecycle_notices (
      workspace_id  uuid NOT NULL REFERENCES workspaces(id),
      notice        text NOT NULL CHECK (length(notice) <= 80),
      sent_at       timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (workspace_id, notice)
    );

    CREATE TABLE exports (
      id            uuid PRIMARY KEY,
      workspace_id  uuid NOT NULL REFERENCES workspaces(id),
      requested_by  uuid NOT NULL REFERENCES users(id),
      status        text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'ready', 'failed', 'expired')),
      key           text,
      bytes         bigint NOT NULL DEFAULT 0,
      error         text NOT NULL DEFAULT '',
      created_at    timestamptz NOT NULL DEFAULT now(),
      started_at    timestamptz,
      finished_at   timestamptz,
      expires_at    timestamptz
    );
    CREATE INDEX exports_queue ON exports (created_at) WHERE status = 'queued';

    CREATE FUNCTION app_member_is_admin() RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
      SELECT EXISTS (SELECT 1 FROM memberships m WHERE m.workspace_id = app_workspace_id()
                     AND m.user_id = app_user_id() AND m.removed_at IS NULL AND m.is_admin)
    $$;
    REVOKE ALL ON FUNCTION app_member_is_admin() FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION app_member_is_admin() TO app_rw;
    """)

    for table in ("subscriptions", "billing_events", "lifecycle_notices", "exports"):
        op.execute(f"""
        ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
        CREATE POLICY {table}_owner ON {table} TO app_owner USING (true) WITH CHECK (true);
        CREATE POLICY {table}_hq ON {table} FOR SELECT TO app_hq USING (true);
        GRANT SELECT ON {table} TO app_hq;
        """)

    op.execute("""
    CREATE POLICY subscriptions_rw ON subscriptions TO app_rw
      USING (workspace_id = app_workspace_id()) WITH CHECK (workspace_id = app_workspace_id());
    REVOKE DELETE, TRUNCATE ON subscriptions FROM app_rw;
    CREATE POLICY lifecycle_notices_rw ON lifecycle_notices TO app_rw
      USING (workspace_id = app_workspace_id()) WITH CHECK (workspace_id = app_workspace_id());
    -- Exports contain every buyer enquiry: Admins only.
    CREATE POLICY exports_rw ON exports TO app_rw
      USING (workspace_id = app_workspace_id() AND app_member_is_admin())
      WITH CHECK (workspace_id = app_workspace_id() AND app_member_is_admin());
    REVOKE DELETE, TRUNCATE ON exports FROM app_rw;
    REVOKE ALL ON billing_events FROM app_rw;

    -- Returns the event's id if it still needs processing (new, or an earlier attempt failed).
    CREATE FUNCTION billing_event_record(p_provider text, p_event_id text, p_type text, p_workspace uuid, p_payload jsonb)
    RETURNS uuid LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
      INSERT INTO billing_events (provider, provider_event_id, type, workspace_id, payload)
      VALUES (p_provider, p_event_id, p_type, (SELECT id FROM workspaces WHERE id = p_workspace), p_payload)
      ON CONFLICT (provider, provider_event_id) DO UPDATE SET received_at = now()
        WHERE billing_events.processed_at IS NULL
      RETURNING id
    $$;
    CREATE FUNCTION billing_event_done(p_id uuid, p_error text) RETURNS void
    LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
      UPDATE billing_events SET processed_at = CASE WHEN p_error = '' THEN now() END, error = left(p_error, 500)
      WHERE id = p_id
    $$;

    -- Workspaces the hourly lifecycle job needs to look at.
    CREATE FUNCTION lifecycle_workspaces() RETURNS SETOF uuid
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
      SELECT w.id FROM workspaces w WHERE w.deleted_at IS NULL AND (
        w.subscription_state IN ('grace', 'offline')
        OR EXISTS (SELECT 1 FROM listings l WHERE l.workspace_id = w.id AND l.is_trial AND l.deleted_at IS NULL
                   AND l.trial_expires_at BETWEEN now() AND now() + interval '8 days')
        OR EXISTS (SELECT 1 FROM subscriptions s WHERE s.workspace_id = w.id AND s.billing_interval = 'year'
                   AND s.status = 'active' AND NOT s.cancel_at_period_end
                   AND s.current_period_end BETWEEN now() AND now() + interval '8 days')
      )
    $$;

    -- Marks finished downloads past their 7 days as expired; returns their storage keys to delete.
    CREATE FUNCTION exports_expire() RETURNS SETOF text
    LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
      UPDATE exports SET status = 'expired' WHERE status = 'ready' AND expires_at <= now() RETURNING key
    $$;

    CREATE FUNCTION claim_export() RETURNS TABLE (id uuid, workspace_id uuid, requested_by uuid)
    LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
      UPDATE exports e SET status = 'running', started_at = now()
      WHERE e.id = (SELECT x.id FROM exports x WHERE x.status = 'queued' ORDER BY x.created_at
                    FOR UPDATE SKIP LOCKED LIMIT 1)
      RETURNING e.id, e.workspace_id, e.requested_by
    $$;

    -- Usernames: held for 60 days after deletion; only the previous owner may reclaim during the hold.
    ALTER TABLE username_holds ADD COLUMN owner_user_id uuid REFERENCES users(id);
    CREATE OR REPLACE FUNCTION usernames_taken(p_names citext[]) RETURNS SETOF citext
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
      SELECT username FROM workspaces WHERE username = ANY (p_names)
      UNION
      SELECT username FROM username_holds WHERE username = ANY (p_names) AND available_at > now()
        AND owner_user_id IS DISTINCT FROM app_user_id()
    $$;
    CREATE FUNCTION username_held(p_name citext) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
      SELECT EXISTS (SELECT 1 FROM username_holds WHERE username = p_name AND available_at > now())
        AND NOT EXISTS (SELECT 1 FROM workspaces WHERE username = p_name)
    $$;

    -- Permanent deletion. Refuses unless the workspace is offline and past its deletion date, so
    -- the API role can never delete a live account even if asked to.
    CREATE FUNCTION workspace_purge(p_ws uuid) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
    DECLARE
      w workspaces%ROWTYPE;
      owner_id uuid;
    BEGIN
      SELECT * INTO w FROM workspaces WHERE id = p_ws FOR UPDATE;
      IF NOT FOUND OR w.deleted_at IS NOT NULL OR w.subscription_state <> 'offline'
         OR w.delete_after IS NULL OR w.delete_after > now() THEN
        RETURN false;
      END IF;
      SELECT user_id INTO owner_id FROM memberships WHERE workspace_id = p_ws AND is_admin AND removed_at IS NULL;

      DELETE FROM ai_generations WHERE workspace_id = p_ws;
      DELETE FROM analytics_events WHERE workspace_id = p_ws;
      DELETE FROM seller_reports WHERE workspace_id = p_ws;
      DELETE FROM enquiries WHERE workspace_id = p_ws;
      DELETE FROM processing_jobs WHERE workspace_id = p_ws;
      DELETE FROM listing_hero WHERE workspace_id = p_ws;
      DELETE FROM media WHERE workspace_id = p_ws AND parent_id IS NOT NULL;
      DELETE FROM media WHERE workspace_id = p_ws;
      DELETE FROM listing_slug_history WHERE workspace_id = p_ws;
      DELETE FROM listing_sections WHERE workspace_id = p_ws;
      DELETE FROM walkthrough_beats WHERE workspace_id = p_ws;
      DELETE FROM listings WHERE workspace_id = p_ws;
      DELETE FROM compliance_acknowledgements WHERE workspace_id = p_ws;
      DELETE FROM invitations WHERE workspace_id = p_ws;
      DELETE FROM exports WHERE workspace_id = p_ws;
      DELETE FROM lifecycle_notices WHERE workspace_id = p_ws;
      DELETE FROM subscriptions WHERE workspace_id = p_ws;
      UPDATE memberships SET role_id = NULL, licence_number = '', removed_at = coalesce(removed_at, now())
        WHERE workspace_id = p_ws;
      DELETE FROM role_permissions WHERE workspace_id = p_ws;
      DELETE FROM roles WHERE workspace_id = p_ws;
      DELETE FROM workspace_profiles WHERE workspace_id = p_ws;
      UPDATE sessions SET workspace_id = NULL WHERE workspace_id = p_ws;
      IF w.username IS NOT NULL THEN
        INSERT INTO username_holds (username, workspace_id, released_at, available_at, owner_user_id)
        VALUES (w.username, p_ws, now(), now() + interval '60 days', owner_id)
        ON CONFLICT (username) DO UPDATE SET workspace_id = EXCLUDED.workspace_id, released_at = now(),
          available_at = EXCLUDED.available_at, owner_user_id = EXCLUDED.owner_user_id;
      END IF;
      UPDATE workspaces SET username = NULL, display_name = '', site_live = NULL, site_live_at = NULL,
             deleted_at = now() WHERE id = p_ws;
      RETURN true;
    END $$;

    REVOKE ALL ON FUNCTION billing_event_record(text, text, text, uuid, jsonb), billing_event_done(uuid, text),
      lifecycle_workspaces(), exports_expire(), claim_export(), username_held(citext), workspace_purge(uuid) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION billing_event_record(text, text, text, uuid, jsonb), billing_event_done(uuid, text),
      lifecycle_workspaces(), exports_expire(), claim_export(), workspace_purge(uuid) TO app_rw;
    GRANT EXECUTE ON FUNCTION username_held(citext) TO app_rw, app_public;
    """)


def downgrade() -> None:
    op.execute("""
    DROP FUNCTION IF EXISTS workspace_purge(uuid);
    DROP FUNCTION IF EXISTS username_held(citext);
    CREATE OR REPLACE FUNCTION usernames_taken(p_names citext[]) RETURNS SETOF citext
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
      SELECT username FROM workspaces WHERE username = ANY (p_names)
      UNION
      SELECT username FROM username_holds WHERE username = ANY (p_names) AND available_at > now()
    $$;
    ALTER TABLE username_holds DROP COLUMN IF EXISTS owner_user_id;
    DROP FUNCTION IF EXISTS claim_export();
    DROP FUNCTION IF EXISTS exports_expire();
    DROP FUNCTION IF EXISTS lifecycle_workspaces();
    DROP FUNCTION IF EXISTS billing_event_done(uuid, text);
    DROP FUNCTION IF EXISTS billing_event_record(text, text, text, uuid, jsonb);
    DROP TABLE IF EXISTS exports, lifecycle_notices, billing_events, subscriptions;
    DROP FUNCTION IF EXISTS app_member_is_admin();
    ALTER TABLE workspaces DROP COLUMN IF EXISTS lapsed_at, DROP COLUMN IF EXISTS grace_ends_at,
      DROP COLUMN IF EXISTS offline_at, DROP COLUMN IF EXISTS delete_after;
    ALTER TABLE workspaces DROP CONSTRAINT IF EXISTS workspaces_plan;
    DROP TABLE IF EXISTS plans;
    """)

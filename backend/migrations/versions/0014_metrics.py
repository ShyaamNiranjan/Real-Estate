"""Super-Admin dashboard data: payments, MRR history, costs, sign-up sources (docs/SCOPE.md 12).

Payments and MRR changes are written only by SECURITY DEFINER code (the billing webhook path and
a trigger on subscriptions); the customer API role can't read them. Staff read them and keep the
monthly cost entries.

Revision ID: 0014
Revises: 0013
"""

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE users
      ADD COLUMN signup_source text NOT NULL DEFAULT 'link'
        CHECK (signup_source IN ('link', 'google', 'referral', 'invite')),
      ADD COLUMN signup_referral text NOT NULL DEFAULT '' CHECK (length(signup_referral) <= 64);

    -- Monthly recurring value of the subscription when it was last updated (yearly prices / 12),
    -- so later price edits don't rewrite history.
    ALTER TABLE subscriptions ADD COLUMN mrr numeric(12, 2) NOT NULL DEFAULT 0;

    CREATE TABLE payments (
      id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      provider             text NOT NULL,
      provider_payment_id  text NOT NULL,
      workspace_id         uuid NOT NULL REFERENCES workspaces(id),
      kind                 text NOT NULL CHECK (kind IN ('charge', 'refund', 'failed')),
      amount               numeric(12, 2) NOT NULL CHECK (amount >= 0),
      fee                  numeric(12, 2) NOT NULL DEFAULT 0 CHECK (fee >= 0),
      tax                  numeric(12, 2) NOT NULL DEFAULT 0 CHECK (tax >= 0),
      currency             char(3) NOT NULL DEFAULT 'USD',
      occurred_at          timestamptz NOT NULL,
      created_at           timestamptz NOT NULL DEFAULT now(),
      UNIQUE (provider, provider_payment_id, kind)
    );
    CREATE INDEX payments_time ON payments (occurred_at);
    CREATE INDEX payments_workspace ON payments (workspace_id, occurred_at);

    CREATE TABLE mrr_changes (
      id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      workspace_id  uuid NOT NULL REFERENCES workspaces(id),
      mrr_before    numeric(12, 2) NOT NULL,
      mrr_after     numeric(12, 2) NOT NULL,
      occurred_at   timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX mrr_changes_time ON mrr_changes (occurred_at);
    CREATE INDEX mrr_changes_workspace ON mrr_changes (workspace_id, occurred_at);

    CREATE TABLE cost_entries (
      id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      month       date NOT NULL CHECK (extract(day FROM month) = 1),
      category    text NOT NULL CHECK (category IN ('hosting', 'database', 'storage', 'ai', 'email', 'worker',
                                                    'domain', 'other')),
      amount      numeric(12, 2) NOT NULL CHECK (amount >= 0),
      note        text NOT NULL DEFAULT '' CHECK (length(note) <= 200),
      created_by  uuid REFERENCES staff(id),
      created_at  timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX cost_entries_month ON cost_entries (month);
    """)

    for table in ("payments", "mrr_changes", "cost_entries"):
        op.execute(f"""
        ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
        CREATE POLICY {table}_owner ON {table} TO app_owner USING (true) WITH CHECK (true);
        CREATE POLICY {table}_hq ON {table} TO app_hq USING (true) WITH CHECK (true);
        REVOKE ALL ON {table} FROM app_rw, app_public;
        """)

    op.execute("""
    GRANT SELECT ON payments, mrr_changes TO app_hq;
    GRANT SELECT, INSERT, DELETE ON cost_entries TO app_hq;

    -- Failed sign-in pressure for the Health panel. Keys are HMACs, never emails or IPs.
    GRANT SELECT ON rate_limits TO app_hq;
    CREATE POLICY rate_limits_hq ON rate_limits FOR SELECT TO app_hq USING (true);

    CREATE FUNCTION mrr_track() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
    DECLARE
      before numeric := 0;
      after numeric := CASE WHEN NEW.status IN ('active', 'past_due') THEN NEW.mrr ELSE 0 END;
    BEGIN
      IF TG_OP = 'UPDATE' AND OLD.status IN ('active', 'past_due') THEN
        before := OLD.mrr;
      END IF;
      IF before IS DISTINCT FROM after THEN
        INSERT INTO mrr_changes (workspace_id, mrr_before, mrr_after) VALUES (NEW.workspace_id, before, after);
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER subscriptions_mrr AFTER INSERT OR UPDATE ON subscriptions
      FOR EACH ROW EXECUTE FUNCTION mrr_track();
    REVOKE ALL ON FUNCTION mrr_track() FROM PUBLIC;

    CREATE FUNCTION payment_record(p_provider text, p_payment_id text, p_ws uuid, p_kind text, p_amount numeric,
                                   p_fee numeric, p_tax numeric, p_currency text, p_at timestamptz)
    RETURNS boolean LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
      WITH ins AS (
        INSERT INTO payments (provider, provider_payment_id, workspace_id, kind, amount, fee, tax, currency, occurred_at)
        VALUES (p_provider, p_payment_id, p_ws, p_kind, p_amount, p_fee, p_tax, p_currency, p_at)
        ON CONFLICT DO NOTHING RETURNING 1)
      SELECT EXISTS (SELECT 1 FROM ins)
    $$;
    REVOKE ALL ON FUNCTION payment_record(text, text, uuid, text, numeric, numeric, numeric, text, timestamptz) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION payment_record(text, text, uuid, text, numeric, numeric, numeric, text, timestamptz) TO app_rw;
    """)


def downgrade() -> None:
    op.execute("""
    DROP FUNCTION IF EXISTS payment_record(text, text, uuid, text, numeric, numeric, numeric, text, timestamptz);
    DROP TRIGGER IF EXISTS subscriptions_mrr ON subscriptions;
    DROP FUNCTION IF EXISTS mrr_track();
    DROP POLICY IF EXISTS rate_limits_hq ON rate_limits;
    REVOKE SELECT ON rate_limits FROM app_hq;
    DROP TABLE IF EXISTS cost_entries, mrr_changes, payments;
    ALTER TABLE subscriptions DROP COLUMN IF EXISTS mrr;
    ALTER TABLE users DROP COLUMN IF EXISTS signup_referral, DROP COLUMN IF EXISTS signup_source;
    """)

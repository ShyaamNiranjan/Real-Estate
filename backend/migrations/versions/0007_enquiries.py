"""Enquiries from buyers.

Revision ID: 0007
Revises: 0006
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE enquiries (
      id               uuid PRIMARY KEY,
      workspace_id     uuid NOT NULL REFERENCES workspaces(id),
      listing_id       uuid,
      agent_member_id  uuid,
      name             text NOT NULL CHECK (length(name) BETWEEN 1 AND 120),
      email            citext NOT NULL CHECK (length(email) <= 254),
      phone            text NOT NULL DEFAULT '' CHECK (length(phone) <= 40),
      message          text NOT NULL DEFAULT '' CHECK (length(message) <= 4000),
      consent_text     text NOT NULL,
      consent_version  text NOT NULL,
      page_path        text NOT NULL DEFAULT '' CHECK (length(page_path) <= 200),
      status           text NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'contacted', 'closed')),
      created_at       timestamptz NOT NULL DEFAULT now(),
      updated_at       timestamptz NOT NULL DEFAULT now(),
      FOREIGN KEY (workspace_id, listing_id) REFERENCES listings (workspace_id, id),
      FOREIGN KEY (workspace_id, agent_member_id) REFERENCES memberships (workspace_id, id)
    );
    CREATE INDEX enquiries_inbox ON enquiries (workspace_id, created_at DESC);
    CREATE INDEX enquiries_listing ON enquiries (listing_id);

    -- Permission checks inside policies: does the current user hold this permission in the
    -- current workspace (Admins hold everything)? SECURITY DEFINER so it can read roles.
    CREATE FUNCTION app_member_can(p_permission text) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
      SELECT EXISTS (
        SELECT 1 FROM memberships m
        WHERE m.workspace_id = app_workspace_id() AND m.user_id = app_user_id() AND m.removed_at IS NULL
          AND (m.is_admin OR EXISTS (SELECT 1 FROM role_permissions rp
                                     WHERE rp.role_id = m.role_id AND rp.permission = p_permission))
      )
    $$;
    CREATE FUNCTION app_membership_id() RETURNS uuid
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
      SELECT id FROM memberships
      WHERE workspace_id = app_workspace_id() AND user_id = app_user_id() AND removed_at IS NULL
    $$;
    REVOKE ALL ON FUNCTION app_member_can(text), app_membership_id() FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION app_member_can(text), app_membership_id() TO app_rw;

    ALTER TABLE enquiries ENABLE ROW LEVEL SECURITY;
    ALTER TABLE enquiries FORCE ROW LEVEL SECURITY;
    CREATE POLICY enquiries_owner ON enquiries TO app_owner USING (true) WITH CHECK (true);
    -- Anyone may leave an enquiry for a workspace (the public form runs in that workspace's context)...
    CREATE POLICY enquiries_rw_insert ON enquiries FOR INSERT TO app_rw
      WITH CHECK (workspace_id = app_workspace_id());
    -- ...but buyers' details are visible only to the listing's agent and members allowed to see all.
    CREATE POLICY enquiries_rw_select ON enquiries FOR SELECT TO app_rw USING (
      workspace_id = app_workspace_id() AND (
        app_member_can('enquiries.view_all')
        OR (app_member_can('enquiries.view_own') AND agent_member_id = app_membership_id())
      )
    );
    CREATE POLICY enquiries_rw_update ON enquiries FOR UPDATE TO app_rw USING (
      workspace_id = app_workspace_id() AND (
        app_member_can('enquiries.view_all')
        OR (app_member_can('enquiries.view_own') AND agent_member_id = app_membership_id())
      )
    ) WITH CHECK (workspace_id = app_workspace_id());
    CREATE POLICY enquiries_hq ON enquiries FOR SELECT TO app_hq USING (true);
    GRANT SELECT ON enquiries TO app_hq;
    REVOKE DELETE, TRUNCATE ON enquiries FROM app_rw;

    -- Who to email about a new enquiry: the listing's agent plus everyone who sees all enquiries.
    -- The public form has no signed-in user, so this reads members on its behalf.
    CREATE FUNCTION enquiry_recipients(p_workspace_id uuid, p_agent_member_id uuid)
    RETURNS TABLE (email citext)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
      SELECT DISTINCT u.email FROM memberships m JOIN users u ON u.id = m.user_id
      WHERE m.workspace_id = p_workspace_id AND m.removed_at IS NULL AND u.deleted_at IS NULL
        AND (m.id = p_agent_member_id OR m.is_admin
             OR EXISTS (SELECT 1 FROM role_permissions rp
                        WHERE rp.role_id = m.role_id AND rp.permission = 'enquiries.view_all'))
    $$;
    REVOKE ALL ON FUNCTION enquiry_recipients(uuid, uuid) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION enquiry_recipients(uuid, uuid) TO app_rw;
    """)


def downgrade() -> None:
    op.execute("""
    DROP TABLE IF EXISTS enquiries;
    DROP FUNCTION IF EXISTS enquiry_recipients(uuid, uuid);
    DROP FUNCTION IF EXISTS app_member_can(text);
    DROP FUNCTION IF EXISTS app_membership_id();
    """)

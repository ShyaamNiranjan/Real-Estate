"""Team invitations, joining, and handing over a departing member's work.

Revision ID: 0009
Revises: 0008
"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE invitations (
      id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      workspace_id uuid NOT NULL REFERENCES workspaces(id),
      email        citext NOT NULL CHECK (length(email) <= 254),
      role_id      uuid NOT NULL,
      token_hash   bytea NOT NULL UNIQUE,
      invited_by   uuid NOT NULL REFERENCES users(id),
      created_at   timestamptz NOT NULL DEFAULT now(),
      expires_at   timestamptz NOT NULL,
      accepted_at  timestamptz,
      accepted_by  uuid REFERENCES users(id),
      revoked_at   timestamptz,
      FOREIGN KEY (workspace_id, role_id) REFERENCES roles (workspace_id, id) ON DELETE CASCADE
    );
    CREATE UNIQUE INDEX invitations_one_open ON invitations (workspace_id, email)
      WHERE accepted_at IS NULL AND revoked_at IS NULL;

    ALTER TABLE invitations ENABLE ROW LEVEL SECURITY;
    ALTER TABLE invitations FORCE ROW LEVEL SECURITY;
    CREATE POLICY invitations_owner ON invitations TO app_owner USING (true) WITH CHECK (true);
    -- Invitee emails are visible only to members who manage the team.
    CREATE POLICY invitations_rw ON invitations TO app_rw
      USING (workspace_id = app_workspace_id() AND app_member_can('team.manage_members'))
      WITH CHECK (workspace_id = app_workspace_id() AND app_member_can('team.manage_members'));
    CREATE POLICY invitations_hq ON invitations FOR SELECT TO app_hq USING (true);
    GRANT SELECT ON invitations TO app_hq;
    REVOKE DELETE, TRUNCATE ON invitations FROM app_rw;

    -- What the invite link shows before anyone signs in. Only the holder of the emailed token can ask.
    CREATE FUNCTION invitation_lookup(p_token_hash bytea)
    RETURNS TABLE (email citext, workspace_name text, role_name text, inviter_name text,
                   expires_at timestamptz, status text, plan_key text)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
      SELECT i.email, w.display_name, r.name, coalesce(nullif(u.display_name, ''), u.email::text), i.expires_at,
             CASE WHEN i.accepted_at IS NOT NULL THEN 'accepted'
                  WHEN i.revoked_at IS NOT NULL OR w.deleted_at IS NOT NULL THEN 'revoked'
                  WHEN i.expires_at <= now() THEN 'expired'
                  ELSE 'open' END,
             w.plan_key
      FROM invitations i
      JOIN workspaces w ON w.id = i.workspace_id
      JOIN roles r ON r.id = i.role_id
      JOIN users u ON u.id = i.invited_by
      WHERE i.token_hash = p_token_hash
    $$;

    -- Joins the signed-in user (app.user_id) to the invitation's workspace. The user's email must
    -- be the invited one, and the workspace must still have a free seat.
    CREATE FUNCTION invitation_accept(p_token_hash bytea, p_seats int)
    RETURNS TABLE (status text, workspace_id uuid)
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
    DECLARE
      inv invitations%ROWTYPE;
      me  uuid := app_user_id();
    BEGIN
      SELECT * INTO inv FROM invitations i
      WHERE i.token_hash = p_token_hash AND i.accepted_at IS NULL AND i.revoked_at IS NULL
        AND i.expires_at > now()
        AND EXISTS (SELECT 1 FROM workspaces w WHERE w.id = i.workspace_id AND w.deleted_at IS NULL)
      FOR UPDATE;
      IF NOT FOUND OR me IS NULL THEN
        RETURN QUERY SELECT 'invalid'::text, NULL::uuid; RETURN;
      END IF;
      IF NOT EXISTS (SELECT 1 FROM users u WHERE u.id = me AND u.email = inv.email AND u.deleted_at IS NULL) THEN
        RETURN QUERY SELECT 'email_mismatch'::text, NULL::uuid; RETURN;
      END IF;
      IF NOT EXISTS (SELECT 1 FROM memberships m
                     WHERE m.workspace_id = inv.workspace_id AND m.user_id = me AND m.removed_at IS NULL) THEN
        PERFORM 1 FROM workspaces w WHERE w.id = inv.workspace_id FOR UPDATE;
        IF (SELECT count(*) FROM memberships m
            WHERE m.workspace_id = inv.workspace_id AND m.removed_at IS NULL) >= p_seats THEN
          RETURN QUERY SELECT 'seats_full'::text, NULL::uuid; RETURN;
        END IF;
        INSERT INTO memberships (workspace_id, user_id, role_id, invited_by)
        VALUES (inv.workspace_id, me, inv.role_id, inv.invited_by);
      END IF;
      UPDATE invitations SET accepted_at = now(), accepted_by = me WHERE id = inv.id;
      RETURN QUERY SELECT 'joined'::text, inv.workspace_id;
    END $$;

    -- Removes a member (or lets a member leave) and hands their listings and enquiries to another
    -- member. Runs as definer because the remover may not be allowed to see those enquiries.
    CREATE FUNCTION member_remove(p_member uuid, p_successor uuid)
    RETURNS text
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
    DECLARE
      ws uuid := app_workspace_id();
      leaving memberships%ROWTYPE;
    BEGIN
      IF ws IS NULL OR NOT (app_member_can('team.manage_members') OR p_member = app_membership_id()) THEN
        RETURN 'forbidden';
      END IF;
      SELECT * INTO leaving FROM memberships
      WHERE id = p_member AND workspace_id = ws AND removed_at IS NULL FOR UPDATE;
      IF NOT FOUND THEN RETURN 'not_found'; END IF;
      IF leaving.is_admin THEN RETURN 'is_admin'; END IF;
      IF p_successor = p_member OR NOT EXISTS (
        SELECT 1 FROM memberships WHERE id = p_successor AND workspace_id = ws AND removed_at IS NULL
      ) THEN
        RETURN 'bad_successor';
      END IF;
      UPDATE listings SET agent_member_id = p_successor, updated_at = now()
      WHERE workspace_id = ws AND (agent_member_id = p_member
                                   OR (agent_member_id IS NULL AND created_by = leaving.user_id));
      UPDATE enquiries SET agent_member_id = p_successor
      WHERE workspace_id = ws AND agent_member_id = p_member;
      UPDATE memberships SET removed_at = now() WHERE id = p_member;
      RETURN 'removed';
    END $$;

    REVOKE ALL ON FUNCTION invitation_lookup(bytea), invitation_accept(bytea, int), member_remove(uuid, uuid)
      FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION invitation_lookup(bytea), invitation_accept(bytea, int), member_remove(uuid, uuid)
      TO app_rw;
    """)


def downgrade() -> None:
    op.execute("""
    DROP FUNCTION IF EXISTS member_remove(uuid, uuid);
    DROP FUNCTION IF EXISTS invitation_accept(bytea, int);
    DROP FUNCTION IF EXISTS invitation_lookup(bytea);
    DROP TABLE IF EXISTS invitations;
    """)

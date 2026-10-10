"""AI writing help: generation log (limits and cost), AI-drafted markers.

Revision ID: 0010
Revises: 0009
"""

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE ai_generations (
      id              uuid PRIMARY KEY,
      workspace_id    uuid NOT NULL REFERENCES workspaces(id),
      listing_id      uuid NOT NULL,
      user_id         uuid NOT NULL REFERENCES users(id),
      kind            text NOT NULL CHECK (kind IN ('full', 'rewrite_section')),
      provider        text NOT NULL,
      model           text NOT NULL,
      prompt_version  text NOT NULL,
      attempts        smallint NOT NULL DEFAULT 0,
      input_tokens    int NOT NULL DEFAULT 0,
      output_tokens   int NOT NULL DEFAULT 0,
      cost_usd        numeric(12, 6) NOT NULL DEFAULT 0,
      status          text NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'ok', 'fallback', 'failed')),
      error           text NOT NULL DEFAULT '' CHECK (length(error) <= 300),
      created_at      timestamptz NOT NULL DEFAULT now(),
      finished_at     timestamptz,
      FOREIGN KEY (workspace_id, listing_id) REFERENCES listings (workspace_id, id)
    );
    CREATE INDEX ai_generations_listing ON ai_generations (listing_id, created_at DESC);
    CREATE INDEX ai_generations_workspace ON ai_generations (workspace_id, created_at DESC);

    ALTER TABLE ai_generations ENABLE ROW LEVEL SECURITY;
    ALTER TABLE ai_generations FORCE ROW LEVEL SECURITY;
    CREATE POLICY ai_generations_owner ON ai_generations TO app_owner USING (true) WITH CHECK (true);
    CREATE POLICY ai_generations_rw ON ai_generations TO app_rw
      USING (workspace_id = app_workspace_id()) WITH CHECK (workspace_id = app_workspace_id());
    CREATE POLICY ai_generations_hq ON ai_generations FOR SELECT TO app_hq USING (true);
    GRANT SELECT ON ai_generations TO app_hq;
    REVOKE DELETE, TRUNCATE ON ai_generations FROM app_rw;

    ALTER TABLE listing_sections ADD COLUMN ai_drafted boolean NOT NULL DEFAULT false;
    ALTER TABLE listings ADD COLUMN ai_tone text NOT NULL DEFAULT ''
      CHECK (ai_tone IN ('', 'luxury', 'modern', 'warm', 'minimal'));
    """)


def downgrade() -> None:
    op.execute("""
    ALTER TABLE listings DROP COLUMN IF EXISTS ai_tone;
    ALTER TABLE listing_sections DROP COLUMN IF EXISTS ai_drafted;
    DROP TABLE IF EXISTS ai_generations;
    """)

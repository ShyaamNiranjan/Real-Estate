"""Media and the processing job queue.

Revision ID: 0005
Revises: 0004
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE media (
      id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      workspace_id   uuid NOT NULL REFERENCES workspaces(id),
      listing_id     uuid,
      parent_id      uuid,
      kind           text NOT NULL CHECK (kind IN ('gallery', 'floor_plan', 'hero', 'video', 'frames')),
      aspect         text CHECK (aspect IN ('landscape', 'portrait')),
      status         text NOT NULL DEFAULT 'uploading'
                     CHECK (status IN ('uploading', 'processing', 'ready', 'failed')),
      original_name  text NOT NULL DEFAULT '' CHECK (length(original_name) <= 200),
      content_type   text NOT NULL DEFAULT '',
      bytes          bigint NOT NULL DEFAULT 0 CHECK (bytes >= 0),
      width          int,
      height         int,
      duration_ms    int,
      key            text NOT NULL,
      public_key     text,
      variants       jsonb NOT NULL DEFAULT '{}'::jsonb,
      label          text NOT NULL DEFAULT '' CHECK (length(label) <= 60),
      alt            text NOT NULL DEFAULT '' CHECK (length(alt) <= 200),
      sort_order     int NOT NULL DEFAULT 0,
      warnings       jsonb NOT NULL DEFAULT '[]'::jsonb,
      error          text,
      created_by     uuid REFERENCES users(id),
      created_at     timestamptz NOT NULL DEFAULT now(),
      updated_at     timestamptz NOT NULL DEFAULT now(),
      deleted_at     timestamptz,
      UNIQUE (workspace_id, id),
      FOREIGN KEY (workspace_id, listing_id) REFERENCES listings (workspace_id, id),
      FOREIGN KEY (workspace_id, parent_id) REFERENCES media (workspace_id, id)
    );
    CREATE INDEX media_listing ON media (listing_id, kind, sort_order) WHERE deleted_at IS NULL;

    CREATE TABLE processing_jobs (
      id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      workspace_id    uuid NOT NULL REFERENCES workspaces(id),
      media_id        uuid NOT NULL,
      kind            text NOT NULL CHECK (kind IN ('video')),
      status          text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'done', 'failed')),
      attempts        int NOT NULL DEFAULT 0,
      error           text,
      run_after       timestamptz NOT NULL DEFAULT now(),
      locked_at       timestamptz,
      started_at      timestamptz,
      finished_at     timestamptz,
      worker_seconds  numeric(10, 1),
      created_at      timestamptz NOT NULL DEFAULT now(),
      FOREIGN KEY (workspace_id, media_id) REFERENCES media (workspace_id, id)
    );
    CREATE INDEX processing_jobs_queue ON processing_jobs (created_at) WHERE status IN ('queued', 'running');

    ALTER TABLE listing_hero ADD CONSTRAINT listing_hero_media_same_workspace
      FOREIGN KEY (workspace_id, image_media_id) REFERENCES media (workspace_id, id);
    """)

    for table in ("media", "processing_jobs"):
        op.execute(f"""
        ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
        CREATE POLICY {table}_owner ON {table} TO app_owner USING (true) WITH CHECK (true);
        CREATE POLICY {table}_rw ON {table} TO app_rw
          USING (workspace_id = app_workspace_id()) WITH CHECK (workspace_id = app_workspace_id());
        CREATE POLICY {table}_hq ON {table} FOR SELECT TO app_hq USING (true);
        GRANT SELECT ON {table} TO app_hq;
        """)

    op.execute("""
    REVOKE DELETE, TRUNCATE ON media, processing_jobs FROM app_rw;

    -- The worker picks the next job across all workspaces, then works inside that job's
    -- workspace context like any request. Jobs stuck "running" for 30 minutes are retried.
    CREATE FUNCTION claim_processing_job()
    RETURNS TABLE (job_id uuid, workspace_id uuid, media_id uuid, kind text, attempts int)
    LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
      UPDATE processing_jobs j
      SET status = 'running', locked_at = now(), started_at = coalesce(j.started_at, now()), attempts = j.attempts + 1
      WHERE j.id = (
        SELECT id FROM processing_jobs
        WHERE (status = 'queued' AND run_after <= now())
           OR (status = 'running' AND locked_at < now() - interval '30 minutes')
        ORDER BY created_at
        FOR UPDATE SKIP LOCKED
        LIMIT 1
      )
      RETURNING j.id, j.workspace_id, j.media_id, j.kind, j.attempts
    $$;
    REVOKE ALL ON FUNCTION claim_processing_job() FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION claim_processing_job() TO app_rw;
    """)


def downgrade() -> None:
    op.execute("""
    DROP FUNCTION IF EXISTS claim_processing_job();
    ALTER TABLE listing_hero DROP CONSTRAINT IF EXISTS listing_hero_media_same_workspace;
    DROP TABLE IF EXISTS processing_jobs, media;
    """)

"""Listings, sections, hero, walkthrough beats, slug history, compliance acknowledgement, waitlist.

Revision ID: 0004
Revises: 0003
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

TENANT_TABLES = ("listings", "listing_slug_history", "listing_sections", "listing_hero",
                 "walkthrough_beats", "compliance_acknowledgements")


def upgrade() -> None:
    op.execute("""
    ALTER TABLE workspaces ADD COLUMN listings_created_total int NOT NULL DEFAULT 0;
    ALTER TABLE workspaces ADD COLUMN trial_listing_allowance int;
    ALTER TABLE memberships ADD CONSTRAINT memberships_workspace_id_id UNIQUE (workspace_id, id);

    CREATE TABLE listings (
      id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      workspace_id     uuid NOT NULL REFERENCES workspaces(id),
      agent_member_id  uuid,
      created_by       uuid NOT NULL REFERENCES users(id),
      slug             text NOT NULL CHECK (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$' AND length(slug) <= 80),
      title            text NOT NULL DEFAULT '' CHECK (length(title) <= 120),
      subtitle         text NOT NULL DEFAULT '' CHECK (length(subtitle) <= 160),
      summary          text NOT NULL DEFAULT '' CHECK (length(summary) <= 6000),
      location         text NOT NULL DEFAULT '' CHECK (length(location) <= 160),
      price_amount     numeric(14, 2) CHECK (price_amount >= 0),
      price_currency   char(3) NOT NULL CHECK (price_currency ~ '^[A-Z]{3}$'),
      price_label      text NOT NULL DEFAULT '' CHECK (length(price_label) <= 40),
      bedrooms         smallint CHECK (bedrooms BETWEEN 0 AND 99),
      bathrooms        numeric(3, 1) CHECK (bathrooms BETWEEN 0 AND 99),
      area             numeric(10, 1) CHECK (area > 0),
      area_unit        text NOT NULL CHECK (area_unit IN ('sqft', 'sqm')),
      property_type    text NOT NULL DEFAULT '' CHECK (length(property_type) <= 40),
      status           text NOT NULL DEFAULT 'draft'
                       CHECK (status IN ('draft', 'pending_approval', 'published', 'sold')),
      experience_type  text NOT NULL DEFAULT 'immersive' CHECK (experience_type IN ('photo', 'immersive')),
      mobile_mode      text NOT NULL DEFAULT 'rotate' CHECK (mobile_mode IN ('rotate', 'fit', 'fill')),
      is_trial         boolean NOT NULL DEFAULT false,
      published_at     timestamptz,
      trial_expires_at timestamptz,
      compliance       jsonb NOT NULL DEFAULT '{}'::jsonb,
      seo_title        text NOT NULL DEFAULT '' CHECK (length(seo_title) <= 70),
      seo_description  text NOT NULL DEFAULT '' CHECK (length(seo_description) <= 170),
      -- What the public sees: a snapshot taken at each Publish. Edits stay in the draft
      -- columns above until the next Publish (nothing auto-publishes).
      live_slug        text,
      live             jsonb,
      live_at          timestamptz,
      changes_submitted_at timestamptz,
      created_at       timestamptz NOT NULL DEFAULT now(),
      updated_at       timestamptz NOT NULL DEFAULT now(),
      deleted_at       timestamptz,
      UNIQUE (workspace_id, id),
      FOREIGN KEY (workspace_id, agent_member_id) REFERENCES memberships (workspace_id, id)
    );
    CREATE UNIQUE INDEX listings_slug ON listings (workspace_id, slug) WHERE deleted_at IS NULL;
    CREATE UNIQUE INDEX listings_live_slug ON listings (workspace_id, live_slug)
      WHERE deleted_at IS NULL AND live_slug IS NOT NULL;
    CREATE INDEX listings_workspace ON listings (workspace_id, updated_at DESC) WHERE deleted_at IS NULL;

    CREATE TABLE listing_slug_history (
      workspace_id  uuid NOT NULL REFERENCES workspaces(id),
      slug          text NOT NULL,
      listing_id    uuid NOT NULL,
      changed_at    timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (workspace_id, slug),
      FOREIGN KEY (workspace_id, listing_id) REFERENCES listings (workspace_id, id)
    );

    CREATE TABLE listing_sections (
      id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      workspace_id    uuid NOT NULL REFERENCES workspaces(id),
      listing_id      uuid NOT NULL,
      type            text NOT NULL,
      layout_variant  text NOT NULL,
      content         jsonb NOT NULL DEFAULT '{}'::jsonb,
      sort_order      int NOT NULL,
      is_visible      boolean NOT NULL DEFAULT true,
      updated_at      timestamptz NOT NULL DEFAULT now(),
      FOREIGN KEY (workspace_id, listing_id) REFERENCES listings (workspace_id, id)
    );
    CREATE INDEX listing_sections_listing ON listing_sections (listing_id, sort_order);

    CREATE TABLE listing_hero (
      listing_id      uuid PRIMARY KEY,
      workspace_id    uuid NOT NULL REFERENCES workspaces(id),
      enabled         boolean NOT NULL DEFAULT true,
      image_media_id  uuid,
      show_facts      boolean NOT NULL DEFAULT true,
      show_price      boolean NOT NULL DEFAULT true,
      FOREIGN KEY (workspace_id, listing_id) REFERENCES listings (workspace_id, id)
    );

    CREATE TABLE walkthrough_beats (
      id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      workspace_id  uuid NOT NULL REFERENCES workspaces(id),
      listing_id    uuid NOT NULL,
      at            numeric(5, 4) NOT NULL CHECK (at >= 0 AND at <= 1),
      label         text NOT NULL DEFAULT '' CHECK (length(label) <= 40),
      text          text NOT NULL DEFAULT '' CHECK (length(text) <= 200),
      FOREIGN KEY (workspace_id, listing_id) REFERENCES listings (workspace_id, id)
    );
    CREATE INDEX walkthrough_beats_listing ON walkthrough_beats (listing_id, at);

    CREATE TABLE compliance_acknowledgements (
      workspace_id  uuid PRIMARY KEY REFERENCES workspaces(id),
      user_id       uuid NOT NULL REFERENCES users(id),
      accepted_at   timestamptz NOT NULL DEFAULT now()
    );

    CREATE TABLE waitlist (
      id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      name              text NOT NULL CHECK (length(name) <= 80),
      email             citext NOT NULL UNIQUE,
      instagram_handle  text NOT NULL DEFAULT '' CHECK (length(instagram_handle) <= 40),
      market            text NOT NULL DEFAULT '' CHECK (length(market) <= 80),
      ip_hash           text,
      created_at        timestamptz NOT NULL DEFAULT now(),
      invited_at        timestamptz
    );
    """)

    for table in (*TENANT_TABLES, "waitlist"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {table}_owner ON {table} TO app_owner USING (true) WITH CHECK (true)")

    for table in TENANT_TABLES:
        op.execute(f"""
        CREATE POLICY {table}_rw ON {table} TO app_rw
          USING (workspace_id = app_workspace_id()) WITH CHECK (workspace_id = app_workspace_id());
        CREATE POLICY {table}_hq ON {table} FOR SELECT TO app_hq USING (true);
        GRANT SELECT ON {table} TO app_hq;
        """)

    # Listings are soft-deleted (the slug is freed, the row and its history stay).
    op.execute("""
    REVOKE DELETE, TRUNCATE ON listings, listing_slug_history, compliance_acknowledgements FROM app_rw;
    REVOKE UPDATE ON compliance_acknowledgements FROM app_rw;
    REVOKE ALL ON waitlist FROM app_rw;
    GRANT SELECT ON waitlist TO app_hq;
    CREATE POLICY waitlist_hq ON waitlist FOR SELECT TO app_hq USING (true);
    """)

    # Public pages only ever see the published snapshot of published or sold listings in
    # claimed workspaces: never drafts, the agent's private notes (summary) or internal fields.
    op.execute("""
    GRANT SELECT (id, workspace_id, status, live_slug, live, live_at, published_at, trial_expires_at)
      ON listings TO app_public;
    CREATE POLICY listings_public ON listings FOR SELECT TO app_public
      USING (status IN ('published', 'sold') AND deleted_at IS NULL AND live IS NOT NULL
             AND workspace_id IN (SELECT id FROM workspaces));

    GRANT SELECT (workspace_id, slug, listing_id) ON listing_slug_history TO app_public;
    CREATE POLICY listing_slug_history_public ON listing_slug_history FOR SELECT TO app_public
      USING (listing_id IN (SELECT id FROM listings));
    """)

    op.execute("""
    CREATE FUNCTION waitlist_join(p_name text, p_email citext, p_instagram text, p_market text, p_ip_hash text)
    RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
    BEGIN
      INSERT INTO waitlist (name, email, instagram_handle, market, ip_hash)
      VALUES (p_name, p_email, p_instagram, p_market, p_ip_hash)
      ON CONFLICT (email) DO NOTHING;
      RETURN FOUND;
    END $$;
    REVOKE ALL ON FUNCTION waitlist_join(text, citext, text, text, text) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION waitlist_join(text, citext, text, text, text) TO app_rw;
    """)


def downgrade() -> None:
    op.execute("""
    DROP FUNCTION IF EXISTS waitlist_join(text, citext, text, text, text);
    DROP POLICY IF EXISTS listing_slug_history_public ON listing_slug_history;
    DROP TABLE IF EXISTS waitlist, compliance_acknowledgements, walkthrough_beats, listing_hero,
                         listing_sections, listing_slug_history, listings;
    ALTER TABLE memberships DROP CONSTRAINT IF EXISTS memberships_workspace_id_id;
    ALTER TABLE workspaces DROP COLUMN IF EXISTS trial_listing_allowance;
    ALTER TABLE workspaces DROP COLUMN IF EXISTS listings_created_total;
    """)

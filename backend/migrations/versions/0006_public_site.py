"""Realtor site publishing: site snapshot, About page text, featured homes.

Revision ID: 0006
Revises: 0005
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE workspace_profiles
      ADD COLUMN tagline text NOT NULL DEFAULT '' CHECK (length(tagline) <= 160),
      ADD COLUMN bio text NOT NULL DEFAULT '' CHECK (length(bio) <= 4000),
      ADD COLUMN featured_listing_ids uuid[] NOT NULL DEFAULT '{}' CHECK (cardinality(featured_listing_ids) <= 8);

    -- Like listings, the public site is a snapshot taken at Publish; edits stay private until then.
    ALTER TABLE workspaces
      ADD COLUMN site_live jsonb,
      ADD COLUMN site_live_at timestamptz;

    -- Public pages need to know whether a site is live and whether the account is offline (503).
    GRANT SELECT (site_live, site_live_at, subscription_state) ON workspaces TO app_public;
    """)


def downgrade() -> None:
    op.execute("""
    REVOKE SELECT (site_live, site_live_at, subscription_state) ON workspaces FROM app_public;
    ALTER TABLE workspaces DROP COLUMN IF EXISTS site_live, DROP COLUMN IF EXISTS site_live_at;
    ALTER TABLE workspace_profiles DROP COLUMN IF EXISTS tagline, DROP COLUMN IF EXISTS bio,
      DROP COLUMN IF EXISTS featured_listing_ids;
    """)

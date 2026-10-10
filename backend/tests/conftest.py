"""Tests run against scrollwalk_test, never scrollwalk_dev.

The app's own settings are pointed at the test database before anything connects, so the
real tenant_session()/public_session() helpers are what gets tested.
"""

import os
import tempfile
from argparse import Namespace
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from app.config import get_settings

_settings = get_settings()
for name in ("migrations_database_url", "database_url", "public_database_url", "hq_database_url"):
    test_url = getattr(_settings, f"test_{name}")
    if not test_url or "scrollwalk_test" not in test_url:
        raise RuntimeError(f"TEST_{name.upper()} must point at scrollwalk_test")
    os.environ[name.upper()] = test_url
os.environ["STORAGE_BACKEND"] = "local"
os.environ["LOCAL_MEDIA_DIR"] = tempfile.mkdtemp(prefix="sw-test-media-")
os.environ["APP_URL"] = "https://testserver"
os.environ["AI_PROVIDER"] = "stub"
os.environ.pop("AI_API_KEY", None)
get_settings.cache_clear()

BACKEND = Path(__file__).resolve().parent.parent
TABLES = (
    "audit_log", "staff_sessions", "trial_redemptions", "trial_invites", "staff", "staff_role_permissions",
    "staff_roles",
    "exports", "lifecycle_notices", "billing_events", "subscriptions",
    "ai_generations", "analytics_events", "analytics_salts", "seller_reports", "enquiries", "processing_jobs", "media", "listing_slug_history", "listing_sections", "listing_hero", "walkthrough_beats",
    "compliance_acknowledgements", "listings", "waitlist",
    "invitations", "role_permissions", "roles", "workspace_profiles", "username_holds",
    "sessions", "email_codes", "rate_limits", "legal_acceptances",
    "memberships", "user_credentials", "workspaces", "users",
)


def _alembic(url: str) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    cfg.cmd_opts = Namespace(x=[f"url={url}"])
    return cfg


@pytest.fixture(scope="session")
def owner_engine():
    settings = get_settings()
    cfg = _alembic(settings.migrations_database_url)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    engine = create_engine(settings.migrations_database_url)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def clean(owner_engine):
    from app import email

    with owner_engine.begin() as conn:
        conn.execute(text("ALTER TABLE audit_log DISABLE TRIGGER audit_log_no_truncate"))
        conn.execute(text(f"TRUNCATE {', '.join(TABLES)} CASCADE"))
        conn.execute(text("ALTER TABLE audit_log ENABLE TRIGGER audit_log_no_truncate"))
        conn.execute(text("""UPDATE plans SET seats = d.seats, listing_limit = d.lim, provider_price_ids = '{}'
                             FROM (VALUES ('agent', 1, 15), ('team', 10, 50), ('brokerage', 50, NULL::int))
                                  AS d(key, seats, lim) WHERE plans.key = d.key"""))
    email.outbox.clear()
    yield


@pytest.fixture
def client(owner_engine):
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app, base_url="https://testserver")


@pytest.fixture
def make_client(owner_engine):
    from fastapi.testclient import TestClient

    from app.main import app

    return lambda: TestClient(app, base_url="https://testserver")

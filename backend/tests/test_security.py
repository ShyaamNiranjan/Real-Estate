"""Guards that keep holding as the API grows: every endpoint is signed in unless it's on the public
list, staff code is reachable only by the staff role, and database functions that bypass row-level
security are locked down."""

import re

from fastapi.routing import APIRoute
from sqlalchemy import text

from app.deps import signed_in
from app.staff import current_staff

# Endpoints that work without a customer or staff session (each has its own protection: rate limits,
# signed tokens, honeypots, webhook signatures).
PUBLIC = [
    r"^/api/v1/health$",
    r"^/api/v1/public/",
    r"^/api/v1/auth/(signup|verify|resend|login|password/forgot|password/reset)$",
    r"^/api/v1/auth/google/(start|callback)$",
    r"^/api/v1/waitlist$",
    r"^/api/v1/invitations/(lookup|signup)$",
    r"^/api/v1/trial/lookup$",
    r"^/api/v1/hq/auth/(login|setup/start|setup/finish)$",
    r"^/api/v1/billing/webhooks/\{provider\}$",
    r"^/api/v1/media/local/(upload/\{token\}|file/\{token\}|public/\{key:path\})$",
]


def _calls(dependant) -> set:
    found = {dependant.call}
    for sub in dependant.dependencies:
        found |= _calls(sub)
    return found


def test_every_endpoint_needs_a_session_unless_listed_public(client):
    from app.main import app

    unguarded = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        calls = _calls(route.dependant)
        guarded = signed_in in calls or current_staff in calls
        public = any(re.search(p, route.path) for p in PUBLIC)
        if not guarded and not public:
            unguarded.append(f"{sorted(route.methods)} {route.path}")
        if route.path.startswith("/api/v1/hq/") and not public:
            assert current_staff in calls, f"{route.path} must use the staff session"
            assert signed_in not in calls, f"{route.path} must not accept customer sessions"
    assert unguarded == []


def test_security_definer_functions_pin_search_path_and_are_not_public(owner_engine):
    with owner_engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT p.oid::regprocedure::text AS fn,
                   coalesce(array_to_string(p.proconfig, ','), '') LIKE '%search_path=%' AS pinned,
                   EXISTS (SELECT 1 FROM aclexplode(coalesce(p.proacl, acldefault('f', p.proowner))) a
                           WHERE a.grantee = 0 AND a.privilege_type = 'EXECUTE') AS public_exec
            FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
            WHERE n.nspname = 'public' AND p.prosecdef""")).all()
    assert rows
    assert [r.fn for r in rows if not r.pinned] == []
    assert [r.fn for r in rows if r.public_exec] == []


def test_staff_functions_are_only_callable_by_the_staff_role(owner_engine):
    with owner_engine.connect() as conn:
        leaks = conn.execute(text("""
            SELECT p.oid::regprocedure::text AS fn, r AS role
            FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace,
                 unnest(ARRAY['app_rw', 'app_public']) r
            WHERE n.nspname = 'public' AND p.proname LIKE 'hq\\_%'
              AND has_function_privilege(r, p.oid, 'EXECUTE')""")).all()
    assert leaks == []


def test_customer_roles_cannot_touch_staff_or_money_tables(owner_engine):
    tables = ("staff", "staff_sessions", "staff_roles", "staff_role_permissions", "audit_log", "trial_invites",
              "trial_redemptions", "listing_reports", "billing_events", "payments", "mrr_changes", "cost_entries",
              "rate_limits")
    with owner_engine.connect() as conn:
        leaks = conn.execute(text("""
            SELECT t, r, priv FROM unnest(CAST(:tables AS text[])) t, unnest(ARRAY['app_rw', 'app_public']) r,
                   unnest(ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE']) priv
            WHERE has_table_privilege(r, 'public.' || t, priv)"""), {"tables": list(tables)}).all()
        assert leaks == []
        # The API sets passwords and codes for the signed-in user only (row-level security) and can never
        # read a password hash back; the public role can't touch either table.
        assert not conn.execute(text("SELECT has_column_privilege('app_rw', 'user_credentials', 'password_hash', "
                                     "'SELECT')")).scalar()
        assert not conn.execute(text("""SELECT bool_or(has_table_privilege('app_public', 'public.' || t, p))
                                        FROM unnest(ARRAY['user_credentials', 'email_codes']) t,
                                             unnest(ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE']) p""")).scalar()


def test_api_docs_are_off_in_production(monkeypatch):
    import importlib

    from app import config, main

    monkeypatch.setenv("ENVIRONMENT", "production")
    config.get_settings.cache_clear()
    try:
        prod = importlib.reload(main)
        assert prod.app.docs_url is None and prod.app.redoc_url is None and prod.app.openapi_url is None
    finally:
        monkeypatch.delenv("ENVIRONMENT")
        config.get_settings.cache_clear()
        importlib.reload(main)

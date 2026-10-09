# Progress

Update at the end of every working session: what was done, what's next, what's blocked. Newest first.

## Oct 10, 2026 — slice 1: backend skeleton
- Done:
  - Local databases `scrollwalk_dev` and `scrollwalk_test` with roles `app_owner`, `app_rw`, `app_public`, `app_hq` (`scripts/db-bootstrap.ps1`).
  - FastAPI app (`backend/app`), Python 3.11 venv in `backend/.venv`, `GET /api/v1/health`.
  - Migration `0001_identity`: users, user_credentials (write-only for the API), workspaces, memberships; forced row-level security on all four; sign-in lookups through `auth_user_by_email` / `auth_user_by_google_sub`.
  - `tenant_session(user_id, workspace_id)` sets the row-level security context per transaction.
  - 20 database-level leak tests passing (`backend/tests/test_isolation.py`), including a guard that fails if any future table lacks forced row-level security.
- Next: slice 2, sign-up and sign-in (Argon2, sessions and CSRF, 6-digit email codes, rate limits, Google), and the first OpenAPI contract for Claude.
- Blocked: nothing.

**Running the backend**
```powershell
cd backend
.\.venv\Scripts\alembic upgrade head          # apply migrations to scrollwalk_dev
.\.venv\Scripts\python -m pytest              # tests run against scrollwalk_test only
.\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

## Oct 10, 2026
- Done: scope locked and written to `docs/SCOPE.md`.

# Progress

Update at the end of every working session: what was done, what's next, what's blocked. Newest first.

## Oct 10, 2026 — slice 2: sign-up and sign-in
- Done:
  - Migration `0002_auth`: sessions, email_codes, rate_limits, legal_acceptances (all forced row-level security).
  - Endpoints under `/api/v1/auth`: signup, verify, resend, login, password forgot/reset, me, logout, logout-all, email change/confirm, Google start/callback.
  - Argon2id passwords; opaque session tokens stored hashed in a `__Host-` HttpOnly Secure SameSite=Lax cookie; signed CSRF token; Origin check on writes; security headers.
  - 6-digit codes: hashed with the server key, 10 minutes, 5 guesses, 30-second resend cooldown, new code kills the old one.
  - Database-backed rate limits per IP and per email.
  - No account enumeration: signup, resend and forgot always answer 202; wrong email and wrong password look and time the same.
  - Google: state + PKCE + nonce; takes over never-verified squatter accounts (their password is deleted).
  - Terms and privacy acceptance recorded with version and method.
  - Contract: `docs/api/openapi.json` + `docs/api/README.md` for the frontend; a test fails if the contract drifts.
  - 57 tests passing.
- Emails print to the server console until Resend is connected. Google needs `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` in `backend/.env`.
- Next: slice 3, usernames and workspace setup (claim username with suggestions and reserved words, About you, contact methods, compliance profiles), and roles and permissions groundwork.

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

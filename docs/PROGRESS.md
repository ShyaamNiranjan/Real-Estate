# Progress

Update at the end of every working session: what was done, what's next, what's blocked. Newest first.

## Oct 10, 2026 — plan
- Build runs in parallel: backend (Cursor agent) slice by slice; frontend (Claude) starts now from `docs/FRONTEND.md`.
- Founder sets up accounts on Oct 11: merchant of record application, Resend + DNS for `mail.scrollwalk.com`, Gemini key, then Google OAuth, R2, hosting.

## Frontend waiting on backend
- (none: the waitlist endpoint is live as `POST /api/v1/waitlist`, replace the mock)

## Oct 10, 2026 — frontend steps 1–3 (Claude, commit da15581)
- Next.js app in `web/`: landing + waitlist (real endpoint), sign up, code entry, sign in, forgot/reset, Google button, Studio placeholder with change email and sign out. Build, typecheck, lint, API-drift check pass.
- Backend fixes from its report: `POST /api/v1/auth/email/resend` (fresh code for a pending email change, no password needed); validation `fields` messages are now plain English.
- Claude's next task is on hold until the founder says go.

## Oct 10, 2026 — slice 6: public pages
- Done:
  - Migration `0006_public_site`: site snapshot (`site_live`), About page text (tagline, bio), featured homes (up to 8).
  - Site publishing: publish / unpublish, blockers (plan, username, name, contact, country fields), the same one-time compliance notice as listings, unpublished-changes flag. Site and listings publish independently.
  - Listing snapshots are now self-contained: agent name and licence, contact options, brand and compliance fields with labels, so a listing renders even while the site is offline.
  - Public API (`/api/v1/public`, read-only database role, no sign-in): site home (or the noindex holding page), Properties with filters, listing page, 301 data for renamed listings, sold pages with other homes, 503 for expired trial listings and offline accounts, sitemaps.
  - Every public response is rebuilt through fixed models (`app/content.py`), so only listed fields can reach a public page; tests check private notes and internal ids never appear and that the public database role can't read drafts or private columns.
  - Owner-only draft preview with signed media links.
  - 132 tests passing.
- Not yet: IndexNow pings on publish (needs the key; with the SEO pass), seller report page (with analytics).
- Next: slice 7, enquiries (public form with bot protection and rate limits, routing to the listing agent and team, email alerts, Studio inbox and export).

## Oct 10, 2026 — slice 5: media
- Done:
  - Migration `0005_media`: media, processing_jobs (forced row-level security; the API can't hard-delete either); media, frame sets and the hero image are tied to their listing's workspace by composite foreign keys.
  - Storage layer: Cloudflare R2 (presigned uploads locked to the announced size and type) and a local stand-in served by the API with signed links, used until the R2 keys arrive. Originals and drafts are private; Publish copies to `public/` (cached forever, media never changes in place).
  - Upload → direct PUT → complete. On complete we check the file that actually arrived (size, type); images are decoded and re-encoded to WebP (2400 px and 640 px), which strips EXIF and GPS and refuses anything that isn't a real image.
  - Gallery (40), floor plans (10), hero image (a new one replaces the old; or pick a gallery photo), labels, alt text, order, delete (public copies stay so the live page doesn't break).
  - Video worker `python -m app.worker`: Postgres job queue (several workers can run side by side, stuck jobs retried, 3 attempts), quality check (too short, below 1080p, too dark), wrong-orientation rejection with a clear message, two-pass stabilisation, duplicate-frame removal (pauses), even sampling to 240 frames, WebP sets at 1920 px and 1280 px, email when ready or failed. A new walkthrough replaces the previous one for that orientation.
  - Immersive listings can't publish until the walkthrough is ready; the live snapshot now carries gallery, floor plans, hero image and frame URL patterns.
  - Trial video cap 500 MB (placeholder in `plans.py`).
  - 119 tests passing, including the full ffmpeg pipeline on a generated clip.
- Not yet: a cleanup sweep for public copies no live page uses any more (with lifecycle work); "shaky footage" warning (stabilisation runs regardless).
- Next: slice 6, public pages API (realtor site and listing pages from live snapshots, agent name, 503 for expired/offline, 301s for old slugs, preview links for drafts).

## Oct 10, 2026 — slice 4: listings and waitlist
- Done:
  - Migration `0004_listings`: listings, listing_sections, listing_hero, walkthrough_beats, listing_slug_history, compliance_acknowledgements, waitlist.
  - **Draft and live are separate**: Publish takes a snapshot (`live`) that is all the public can read; later edits show `has_unpublished_changes` until the next Publish.
  - Composite foreign keys tie every section, hero, caption, slug-history row and listing agent to the same workspace as its listing (a tested cross-tenant write is refused by the database).
  - Slugs from titles (accents folded, `-2` for duplicates, section words avoided); renaming a live listing records the old address for a 301 at the next Publish; old live addresses are never reused.
  - Section library (9 types, fixed layout variants, strict content schemas), default set of 8 sections on create, "At a glance" auto-filled from details until edited, add after / edit / hide / delete / reorder.
  - Hero settings, walkthrough captions (up to 20).
  - Publishing: blockers (plan, workspace setup, title, country listing fields such as the EU energy rating), one-time compliance acknowledgement, approval flow for roles without publish (first publish and later changes; the live version stays up while changes wait), unpublish, mark sold.
  - Limits: free preview 1 listing; trial 3 listings ever (deleting doesn't free a slot), each live 60 days then `expired`; plan limit counts active listings; grace = no new listings, offline = read-only.
  - Listing agent: needs the permission and, in licensed countries, a licence number.
  - Waitlist: `POST /api/v1/waitlist`, always 202, confirmation email once, rate-limited, unreadable by the API.
  - 108 tests passing.
- Not yet: walkthrough-ready check before publishing (comes with the media slice).
- Next: slice 5, media (R2 presigned uploads with a local stand-in until keys arrive, gallery, floor plans, hero image, walkthrough upload and the processing job queue).

## Oct 10, 2026 — slice 3: workspace setup
- Done:
  - Migration `0003_workspace_setup`: workspace_profiles, username_holds, roles, role_permissions; member licence number; roles can only be assigned within their own workspace (composite foreign key).
  - Usernames: rules, reserved words and brands, three live suggestions, claim only by the Admin of a trialing/active/grace workspace, `confirm_permanent` required; a database trigger refuses any change once set; held names of deleted accounts stay blocked.
  - Profile: About you, country → compliance profile (US, GB, AE, IN, CA, AU, EU, OTHER) with currency and unit defaults, compliance fields validated per profile, contact methods (international phone format, https booking link), style preset, time zone.
  - `publish_blockers` computed for the workspace; setup guide progress.
  - Permission catalogue (20 switches, no Admin-only powers), role suggestions, role CRUD with "can't grant more than you have", role-in-use protection, team plans only.
  - 84 tests passing.
- Next: slice 4, listings (create, details, sections, slugs with 301 history, hero settings, statuses, approval flow, trial counting) and the waitlist endpoint.

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
.\.venv\Scripts\python -m app.worker          # video processing (needs ffmpeg on PATH)
```

## Oct 10, 2026
- Done: scope locked and written to `docs/SCOPE.md`.

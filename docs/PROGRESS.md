# Progress

Update at the end of every working session: what was done, what's next, what's blocked. Newest first.

## Oct 10, 2026 — plan
- Build runs in parallel: backend (Cursor agent) slice by slice; frontend (Claude) starts now from `docs/FRONTEND.md`.
- Founder sets up accounts on Oct 11: merchant of record application, Resend + DNS for `mail.scrollwalk.com`, Gemini key, then Google OAuth, R2, hosting.

## Frontend waiting on backend
- (none: the waitlist endpoint is live as `POST /api/v1/waitlist`, replace the mock)

## Oct 10, 2026 — slice 12a: Super-Admin sign-in, customers, trial invites, audit log
- Slice 12 is split in three: 12a (Milestone A, needed for the Oct 23 trials), 12b (staff actions, reports and takedowns, announcements, legal versions, IndexNow, Admin transfer), 12c (dashboard numbers, CI, full security review).
- Done (12a):
  - Migration `0012_staff`: staff, staff roles and permissions, staff sessions, append-only audit log (the database refuses updates, deletes and truncation), trial invites and redemptions. The customer API role can't read any of these.
  - Staff are separate accounts with their own cookie (SameSite=Strict, 12-hour sessions, signed out after 60 idle minutes). Sign-in is email + password + authenticator code in one step; each code works once. Two-factor secrets are encrypted at rest.
  - No staff sign-up: the first Super-Admin is created on the server with `python -m app.staff_cli create-super <email> "<name>"` (prints and emails a 72-hour setup link to choose a password and scan the QR code). `reset-super` recovers a lost phone.
  - Super-Admin manages staff (add by email with a setup link, change role, disable, reset two-factor) and staff roles over a permission catalogue (view customers, log in as customer, manage customers, refunds, revenue, moderation, trial invites, pricing, announcements, audit log).
  - Customers list (search by username, name or email; filter by state and plan; most popular plan) and a read-only customer view (members, listings, subscription, trial, usage counts, recent staff actions). Buyers' enquiry contents are never shown. Opening a customer is audited.
  - Trial invites: personal links (one email, single use, emailed) and campaign codes (e.g. REZA30, usage cap, expiry), listings allowed, note, revoke, redemptions and conversions. Customers check a link or code with `POST /api/v1/trial/lookup` and start the trial with `POST /api/v1/trial/redeem`: one trial per person and per workspace, only from the free preview, never after paying. The preview listing becomes a trial listing.
  - Every staff action and every staff sign-in (including failures) is in the audit log.
  - 229 tests passing.
- Next: 12b.

## Oct 10, 2026 — slice 11: billing and account lifecycle
- Done:
  - Migration `0011_billing`: plans in the database (Agent 1 seat / 15 listings, Team 10 / 50, Brokerage 50 / unlimited, sales-led), subscriptions, billing events (idempotent, invisible to the API role), lifecycle reminders sent once, downloads (Admin only, enforced in the database).
  - Merchant-of-record adapter with a local stand-in (`BILLING_PROVIDER=stub`), so the full flow works without keys: checkout page, plan change, cancel at period end, resume, payment method/invoices page, simulated renewal, failed payment and end. The stand-in refuses to start in production. A real provider is one more class in `app/billing_providers.py`.
  - Signed webhooks: bad signatures get 400; each event applies exactly once; older events never overwrite newer ones; unknown workspaces/plans are recorded and rejected.
  - Checkout rules: Brokerage is "Talk to us", downgrades must fit current listings and seats, auto-renewal/no-refund wording returned for the checkout screen.
  - Lifecycle (`python -m app.jobs lifecycle`, hourly): lapse → 30 days' grace (live, no new listings) → offline (503 pages, read-only Studio) → permanent deletion 6 months after lapsing. Emails at lapse, 7 and 1 days before offline, offline, 30 and 7 days before deletion. Resubscribing restores everything at the same addresses. Trial-listing (7 and 1 days) and annual renewal (7 days) reminders.
  - Deletion removes every row and file for the workspace; the username is held 60 days ("no longer available", 410) and only the previous owner can reclaim it.
  - "Download everything" (`/api/v1/export`): zip of every listing's text, captions, original photos/floor plans/videos, profile and enquiries CSV. Built by the worker (or `python -m app.jobs exports`), emailed when ready, link valid 1 hour and refreshed on each visit, file kept 7 days. One at a time, 3 per day. Works when offline.
  - 209 tests passing.
- Before trials (by Oct 18–20): merchant-of-record API key, webhook secret, product/price IDs and a sandbox account, then add the provider class and test checkout end to end. Schedule `lifecycle` hourly.
- Next: slice 12, Super-Admin, audit log, trial invites, legal versions, IndexNow, security review, CI.

## Oct 10, 2026 — slice 10: AI writing help
- Done:
  - Migration `0010_ai`: `ai_generations` (who, which listing, provider, model, prompt version, attempts, tokens, cost, status) for limits and cost metering; sections remember whether they're AI-drafted; listings remember the tone.
  - One OpenAI-compatible client switched by settings (`AI_PROVIDER`, `AI_BASE_URL`, `AI_MODEL`, `AI_API_KEY` in `backend/.env` only). Without a key a local stand-in streams template text, so the frontend can be built now. Tests never call a real provider.
  - Text only: structured details, photo labels and the summary with emails, phone numbers and links removed. No images, names, contact details, brokerage or buyer data. A test checks exactly what is sent.
  - Full generation streamed live (server-sent events): hero line, Story, Spaces, Location with highlights, FAQ, walkthrough captions, SEO title and description, photo descriptions. Tones: Luxury, Modern, Warm, Minimal. Spelling follows the country.
  - Guardrails: versioned prompt files (`app/prompts/listing_v1.md`, `rewrite_v1.md`), facts-only with `[Add …]` placeholders, fair-housing phrase list in the prompt and checked on every output, length limits enforced, one automatic retry, then the template fallback ("We've started your page…").
  - Placeholders block publishing. AI-drafted sections are labelled until edited. Regenerating asks before replacing the agent's own text.
  - Per-section Rewrite (shorter, more luxurious, more factual) returns a proposal; nothing is saved until the agent keeps it.
  - Limits: 10 full generations per listing per day, 60 rewrites per listing per day, 300 AI requests per workspace per day, 60 per user per hour.
  - 187 tests passing.
- Before trials: put the Gemini key in `backend/.env` (`AI_PROVIDER=openai_compatible`), run the prompt against sample listings, then switch to GPT-6 Luna with its prices (`AI_INPUT_USD_PER_MILLION`, `AI_OUTPUT_USD_PER_MILLION`) and rerun by Oct 19–20.
- Next: slice 11, billing and account lifecycle.

## Oct 10, 2026 — slice 9: team invites and members
- Done:
  - Migration `0009_team`: invitations (token stored hashed, 7-day expiry, one open invitation per email). Only members who manage the team can see invitations, enforced in the database.
  - Invite by email into a role: Team/Brokerage plans only, you can't invite into a role with permissions you lack, seats count members plus open invitations (placeholder seats: Team 5, Brokerage 25). Resend (new link, old link dies), withdraw, re-invite replaces.
  - Joining: the emailed link proves the inbox, so new people set a password and are in (no code); existing users sign in and accept. The account email must match the invitation. The inviter gets a "joined" email.
  - Members: list (contact details only for managers and yourself), change role (immediate), licence number (self or manager), remove with handover of listings and enquiries to a chosen member (default the Admin), leave team. The Admin is protected; managers can't touch members with stronger permissions.
  - Workspace switching; sign-in returns to the workspace used last; removed members land back in their own workspace.
  - 173 tests passing.
- Next: slice 10, AI writing help.

## Oct 10, 2026 — slice 8: analytics
- Done:
  - Migration `0008_analytics`: analytics_events, daily salts, seller_reports.
  - Cookieless ingest `POST /api/v1/public/events`: visitor = hash of a random daily salt (deleted after a day), IP, browser and workspace; no IP or cookie stored. Bots, headless browsers (`navigator.webdriver`) and the realtor's own visits (recognised by their Studio session) are dropped. Source: "Through a link" or "Found on Google" (search engines), internal navigation kept separate. Device from the browser, country and city from Cloudflare/Vercel headers.
  - Database-enforced visibility: agents see their own listings, "whole team" members and the Admin see everything including site pages; buyers' details stay behind the enquiry permissions (analytics only gets counts).
  - Summary for 7/30/90 days: views, daily unique visitors, enquiries and rate, sources, devices, countries, cities, clicks, top listings; per listing: walkthrough starts, average depth, completion and drop-off by caption.
  - Seller reports: unguessable link (stored hashed, shown once), revocable, opens exactly one listing's numbers since publishing.
  - Weekly summary email (`python -m app.jobs weekly`, needs a scheduler) and a Studio preview.
  - 155 tests passing.
- Next: slice 9, team invites and members.

## Oct 10, 2026 — slice 7: enquiries
- Done:
  - Migration `0007_enquiries`. The database decides who can read an enquiry: the listing's agent (with "see own listings' enquiries"), members with "see the whole team's enquiries", and the Admin. Anyone else, including a request with no signed-in user, sees nothing; the API can't delete enquiries.
  - Public form `POST /api/v1/public/enquiries` for listing pages and the site's Contact page. Only live pages accept enquiries. Consent line stored with its version.
  - Bot protection: hidden trap field, signed form token that must be 3 seconds to 24 hours old, rate limits (5 per 10 minutes and 20 per day per IP, 200 per day per workspace), Cloudflare Turnstile when `TURNSTILE_SECRET` is set. Bots get the same "sent" answer.
  - Email alert to the listing's agent and everyone who sees all enquiries, with reply-to set to the buyer.
  - Studio inbox: newest first with paging, filter by status and listing, search, status (new, contacted, closed), CSV export (needs the export permission; formula injection neutralised). Read-only when the account is offline.
  - Trial workspaces can't publish a website (scope: trials are listings only).
  - 146 tests passing.
- Deployment note: the API rate-limits by the connecting address. Behind Vercel/Cloudflare, run uvicorn with `--proxy-headers --forwarded-allow-ips` set to the proxy's addresses, or every visitor shares one limit.
- Next: slice 8, analytics.

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

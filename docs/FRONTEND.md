# Frontend brief (Claude)

Read first: `docs/SCOPE.md` (what we're building, every locked decision), `docs/api/README.md` (how to call the API), `docs/PROGRESS.md` (what's done). This file is the frontend's own plan.

## Ground rules
- **Next.js (App Router, TypeScript)** in a new `web/` folder at the repo root. Public realtor sites and listing pages are server-rendered; Studio (`/studio`) and Super-Admin (`/hq`) are client-rendered.
- **The prototype is the visual reference.** It's the Vite app in `src/` on branch `ye-prototype` (run `npm run dev`). Port components and CSS from it (`src/components/ScrollExperience.tsx`, `src/public/*`, `src/admin/*`, `src/styles/*`) rather than redesigning. Its data layer (Supabase calls, `localStorage` stand-ins, `src/lib/supabase.ts`, `src/lib/prototype.ts`) is **not** carried over.
- **All data comes from FastAPI** through a typed client generated from `docs/api/openapi.json` (e.g. `openapi-typescript` + `openapi-fetch`). Never hand-write API types. Next.js rewrites `/api/:path*` to `http://localhost:8000/api/:path*` in development so the browser stays same-origin.
- **No secrets in `web/`**, no direct database or third-party calls from the browser or from Next.js server code. Only the API.
- **Accessibility:** WCAG 2.1 AA. **Motion:** respect `prefers-reduced-motion`. **Numbers** in the Studio use the sans font with lining tabular figures.
- When an endpoint you need doesn't exist yet, build the screen against the documented shape in SCOPE.md with a clearly marked mock, and note it in `docs/PROGRESS.md` under "Frontend waiting on backend".

## Running the backend locally
```powershell
cd backend
.\.venv\Scripts\alembic upgrade head
.\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```
Emails (sign-up codes) print in that terminal. API docs: http://localhost:8000/docs

## Order of work
1. **Foundation:** `web/` Next.js app, design tokens and fonts from the prototype, typed API client, `/api` rewrite, session handling (`GET /auth/me`, CSRF header on writes), error display from `{error: {code, message, fields}}`.
2. **Waitlist page** on the Scrollwalk landing (needs to be live before Oct 23; backend endpoint coming, mock until then).
3. **Sign-in screens** (contract ready): sign up, code entry, sign in, forgot/reset, Google button, change email.
4. **Walkthrough player** ported from `ScrollExperience.tsx` to the standard in SCOPE.md 8.7 (canvas, smoothing, frame blending, memory window, no initial hold, rotate cue), plus the hero banner and "Scroll to walk in." first frame (`src/public/ListingHero.tsx`, `src/styles/hero.css`).
5. **Studio shell and setup guide** (contract ready): dashboard frame from the prototype redesign, the one-tile-at-a-time setup guide (About you with username check and claim, How buyers reach you, Your style, Invite team), dashboard checklist with publish blockers from `GET /workspace`.
6. **Team page roles** (contract ready): Create role with name, description, permission switches grouped as returned by `GET /team/permissions`, suggestion chips that prefill but don't save.
7. Then listings, editor, media, public pages, enquiries, analytics, billing and Super-Admin as each backend slice lands (watch `docs/PROGRESS.md`).

## Contract-ready endpoints (today)
- `/api/v1/auth/*`: see `docs/api/README.md`.
- `GET /api/v1/workspace`: workspace, profile, `setup` progress, `publish_blockers`, `is_admin`, `my_permissions`, `can_claim_username`.
- `PATCH /api/v1/workspace/profile`: About you, country (sets compliance profile, currency, units), compliance fields, contact methods, style preset.
- `GET /api/v1/workspace/username/check?username=` → `{available, reason, suggestions}`; debounce ~300 ms.
- `POST /api/v1/workspace/username {username, confirm_permanent: true}`: only when `can_claim_username`; show the "This will be your link forever" confirmation first.
- `POST /api/v1/workspace/setup {step, status}`: setup guide progress.
- `GET /api/v1/workspace/compliance-profiles`: field labels, hints, which are required, per country.
- `GET /api/v1/team/permissions`, `GET|POST /api/v1/team/roles`, `PUT|DELETE /api/v1/team/roles/{id}`.
- Hide or disable controls the user lacks permission for using `my_permissions`; the API enforces it regardless.
- `POST /api/v1/waitlist {name, email, instagram_handle, market}` → always `202 {status: "joined"}`.
- Listings: `GET|POST /api/v1/listings`, `GET|PATCH|DELETE /api/v1/listings/{id}`; sections `POST /listings/{id}/sections {type, layout_variant?, after_id?}`, `PATCH|DELETE /listings/{id}/sections/{sid}`, `PUT /listings/{id}/sections/order {ids}`; `PUT /listings/{id}/hero`, `PUT /listings/{id}/beats`; status `POST /listings/{id}/publish {acknowledge_compliance}`, `/submit`, `/approve`, `/unpublish`, `/sold`. Each listing returns `permissions` (what this user can do to it), `publish_blockers`, `live_state` (draft, pending_approval, live, sold, expired, offline), `has_unpublished_changes` and `awaiting_approval`. Show the compliance notice and send `acknowledge_compliance: true` when publish answers `409 compliance_ack_required`.
- Media (gallery, floor plans, hero image, walkthrough videos):
  1. `POST /api/v1/media/uploads {listing_id, kind: gallery|floor_plan|hero|video, filename, content_type, size, aspect?}` → `{media, upload: {url, method, headers}}`. `aspect` (landscape|portrait) is required for videos. Allowed: JPEG/PNG/WebP up to 25 MB; MP4/MOV up to 2 GB (500 MB on trial).
  2. `PUT` the file **directly to `upload.url`** with exactly `upload.headers` (no cookies, no CSRF header; it's a signed storage URL). Use `XMLHttpRequest` for a progress bar. Locally the URL points at the API; in production it will be Cloudflare R2.
  3. `POST /api/v1/media/{id}/complete`. Images come back `ready` with `thumb_url` / `large_url` (signed, expire after an hour, so refetch the list rather than caching URLs). Videos come back `processing`; poll `GET /api/v1/media?listing_id=` every ~5 s until `ready` or `failed` (`error` is a sentence to show). The uploader also gets an email.
  - A ready video has `frames {media_id, count, first, middle, last}` for a poster/preview, and `warnings` (`too_short`, `low_resolution`, `too_dark`) to show as gentle tips. All frames for a Studio preview: `GET /api/v1/media/{frames.media_id}/frames?size=small|large`.
  - `PATCH /api/v1/media/{id} {label?, alt?}`, `PUT /api/v1/media/order {listing_id, kind, ids}`, `DELETE /api/v1/media/{id}`.
  - A hero upload becomes the hero image automatically; `PUT /listings/{id}/hero {…, image_media_id}` picks any ready gallery photo instead (omit to keep, `null` to clear).
  - Immersive listings can't publish until a walkthrough is ready (`publish_blockers` codes `walkthrough` / `walkthrough_processing`).
  - The live snapshot (for public pages, next slice) contains `gallery`, `floor_plans`, `hero.image` and `walkthrough.{landscape|portrait}.{count, large|small: {pattern, width, height}}`, where `pattern` has `{n}` to replace with the 4-digit frame number (`0001`…).

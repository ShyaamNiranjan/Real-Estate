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
  - The live snapshot contains `gallery`, `floor_plans`, `hero.image` and `walkthrough.{landscape|portrait}.{count, large|small: {pattern, width, height}}`, where `pattern` has `{n}` to replace with the 4-digit frame number (`0001`…).
- Site publishing (Studio): `PATCH /api/v1/workspace/profile` now also takes `tagline` and `bio` (About page); `PUT /api/v1/workspace/site/featured {listing_ids}` (up to 8, in order); `POST /api/v1/workspace/site/publish {acknowledge_compliance}` and `/site/unpublish`. The workspace returns `site_state` (draft, live, offline), `site_has_unpublished_changes` and `site_blockers`. Like listings, the public site is a snapshot: edits show only after the next site Publish.
- Draft preview (owner only, `noindex`, not shareable): `GET /api/v1/listings/{id}/preview` → `{id, status, noindex, content}`. `content` has the same shape as a public listing, except walkthrough frame sets carry signed `urls` (one per frame) instead of a `pattern`. Render `/preview/<id>` from this.
- Public pages (server-render these in Next.js; no session, no CSRF): all under `/api/v1/public`, all `GET`.
  - `/sites/{username}` → `state: "live"` (`site`, `featured` cards, `listing_count`) or `"holding"` (`holding: {display_name, brokerage_name, style_preset, contact}`, `noindex: true`). 404 unknown, 503 offline.
  - `/sites/{username}/listings?status=&min_price=&max_price=&min_beds=&location=` → cards for `/username/properties` (404 while the site isn't live).
  - `/sites/{username}/listings/{slug}` → `{redirect_to}` (send a **301** to it) or `{page}`. `page.content` is the listing; use `page.contact` (the site's contact when the site is live, else the listing's own); when `page.site_live` is false show no links to the realtor site, only the agent's name and contact. Sold pages have `status: "sold"` and up to 4 `other_homes`. 404 = not found; **503 = temporarily unavailable** (expired trial or offline): return HTTP 503 from Next.js too so search engines keep the page.
  - Sitemaps: `/sitemaps` (realtors with anything public, `last_modified`) and `/sitemaps/{username}` (`path`, `last_modified`). Build `sitemap.xml` / `robots.txt` from these.
  - Hero image fallback when `content.hero.image` is null: a gallery photo, else the walkthrough's last frame. Cards already include an `image` chosen this way.
  - `canonical` = `https://scrollwalk.com` + `path`; use `last_modified` for structured data and sitemaps.
- Enquiry form (listing pages and the site's Contact page):
  - `POST /api/v1/public/enquiries {username, listing_slug (omit on the Contact page), name, email, phone?, message?, consent: true, form_token, website: "", turnstile_token?}` → always `202 {status: "sent"}` once validation passes.
  - `form_token` comes from the page response (`page.form_token` / `site.form_token`); put it in a hidden input. Also render a visually hidden `website` input (off-screen, `tabindex="-1"`, `autocomplete="off"`, `aria-hidden`) and send whatever it contains; people leave it empty.
  - Consent line under the form: "By sending this, you agree to be contacted by {page.content.agent.name} about this property." (Contact page: "…contacted by {site.display_name}."). The checkbox sends `consent: true`.
  - Turnstile: when the site key is configured (later), render the widget and send its token; `422 verification_failed` means show the check again. `429` = too many messages, try later.
- Studio inbox (`enquiries.view_own` / `view_all`): `GET /api/v1/enquiries?status=&listing_id=&q=&before=` → `{items, next_before, counts}` (50 per page; pass `next_before` as `before`), `GET /api/v1/enquiries/{id}`, `PATCH /api/v1/enquiries/{id} {status: new|contacted|closed}`, `GET /api/v1/enquiries/export` (CSV download, needs `enquiries.export`). Agents only ever receive their own listings' enquiries; the API and database filter it.
- Site publish: trial workspaces get the `trial_no_site` blocker (trials are listings only).
- Analytics beacons (public pages only; never in the Studio or previews):
  - `POST /api/v1/public/events {username, listing_slug?, path, referrer: document.referrer, view_id, webdriver: navigator.webdriver, events: [{event, value?}]}` → always 204. `view_id` = `crypto.randomUUID()` once per page load, kept in memory only (no cookies, no storage).
  - Send `pageview` on load; `walk_depth` (value 0–1, furthest point reached) every 15 s while the tab is visible and on `pagehide`/`visibilitychange` together with `leave`; clicks: `gallery_open`, `floor_plan_view`, `enquiry_click`, `phone_tap`, `whatsapp_tap`, `booking_click`. Batch up to 20 events per call. Use `navigator.sendBeacon` with a JSON `Blob` on leave, `fetch(..., {keepalive: true})` otherwise.
- Studio analytics: `GET /api/v1/analytics/summary?days=7|30|90&listing_id=` → totals, daily `series` (views, visitors, enquiries), `sources` (`link` = "Through a link", `search` = "Found on Google"), devices, top countries and cities, clicks, top `listings` (workspace view) or `walkthrough` (starts, average depth, completion, `drop_off` per caption; listing view). Agents with "own" analytics automatically get only their listings.
- Seller reports (`analytics.seller_reports`): `POST /api/v1/analytics/reports {listing_id}` → `url` (shown once; offer Copy), `GET /api/v1/analytics/reports?listing_id=` (active links), `DELETE /api/v1/analytics/reports/{id}` (revoke). Public page `/username/slug/report?t=…` renders `GET /api/v1/public/reports/{t}` (noindex, print-friendly for "Save as PDF").
- `GET /api/v1/analytics/weekly-preview` → `{subject, text}` of the weekly email.

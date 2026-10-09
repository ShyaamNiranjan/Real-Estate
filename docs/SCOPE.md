# Scrollwalk — Build Scope

**Version 1.0 · written Oct 10, 2026**

This document is the single source of truth for the Scrollwalk build. Every decision in it was locked with the founder during the discussion phase (Oct 1–10). If something here conflicts with older notes, chat history or the prototype, **this document wins**. If something is missing or ambiguous, ask the founder; never guess on product behaviour.

---

## 0. How to use this document

**Builders**
- **Backend** (FastAPI, Postgres, auth, email, AI, storage, billing events, jobs, Super-Admin data, tests, deployment): the Cursor agent.
- **Frontend** (Studio, public realtor sites and listing pages, walkthrough player, editors, Super-Admin screens, marketing site, polish and motion): Claude.
- **Both:** cross-review the critical paths (section 14).

**The contract sits between the two builders**
1. The **data model** (section 6) and the **API contract** (section 7) are written first, before feature code.
2. The backend publishes an OpenAPI schema. The frontend uses a **typed client generated from it**. Changing an endpoint breaks the frontend build instead of production.
3. **Tests decide "done"**, not either builder's confidence. Nothing merges with a failing test.

**Continuity**
- The repository carries the memory: this file, the OpenAPI schema, the tests, and `docs/PROGRESS.md`. Both builders update `PROGRESS.md` at the end of every working session: what was done, what's next, what's blocked.
- The prototype on branch `ye-prototype` is the **visual and behavioural reference**. Screens approved there should be matched, not reinterpreted. Its data layer (direct browser-to-Supabase calls, localStorage stand-ins, Vite middleware) is **not** carried over.

**Hard rules that apply everywhere**
- Production `realestate.yniidi.com` (YNIIDI Estates) stays untouched.
- No secrets in the frontend, ever. No secrets in git, ever.
- Only text is ever sent to an AI provider. Never images, never personal or contact data.
- Nothing auto-publishes. Ever.
- No cookies except the essential session cookie. Analytics are cookieless.

---

## 1. Product summary

**Scrollwalk** is a multi-tenant SaaS for realtors. Each realtor (or team) gets:
- A premium agency website at `scrollwalk.com/username`.
- Property pages at `scrollwalk.com/username/listing-slug`, each opening with an optional hero banner and a scroll-driven walkthrough of the home.
- A Studio to build listings (AI-assisted), manage the site, see enquiries and analytics, and run a team.

**Tagline (working):** "Homes you can walk through. Just scroll." The first-frame line is "Scroll to walk in." Refinement is deferred until after launch.

**Who buys:** solo agents and small teams first (content-first agents who sell through Instagram), luxury agents and brokerages second. Available worldwide; marketing focuses on the US first.

**Design principles (locked)**
1. *Structured creative freedom, not an empty canvas.* Agents choose from designed options; they can never make their site look bad.
2. *Scrollwalk controls the system, the realtor controls the brand.* Paid sites show the realtor's brand, not ours.
3. *Leads belong to the realtor.* A realtor's pages only ever show that realtor's homes. Scrollwalk owns the subscription relationship, never the buyer relationship.

---

## 2. Timeline and milestones

| Dates | Phase |
|---|---|
| Oct 10–11 | Contract first: data model, migrations, OpenAPI skeleton, typed client, CI with tests. **Waitlist page live.** |
| Oct 10–18 | Build (backend and frontend in parallel) |
| Oct 18–23 | Testing, fixes, security review, AI prompt tested on the production model, staging deploy |
| Oct 23–30 | Invite-only pre-launch trials with real agents |
| Oct 31 | Launch |

**Milestone A — must work for the Oct 23 trials**
- Waitlist page and confirmation email (needed first, ideally live by Oct 12).
- Sign-up and sign-in (Google, email and password, 6-digit codes), sessions, security baseline (section 9), leak tests in CI.
- Usernames, workspaces, compliance profiles.
- Listing creation: details, AI-generated sections, on-page editing, media (gallery, floor plans, hero banner), walkthrough upload with background processing, landscape and portrait slots.
- Publishing a listing, public listing page with walkthrough, hero banner, enquiry form, SEO basics.
- Enquiries delivered to the realtor by email and shown in the Studio.
- Listing analytics (views, visitors, sources, walkthrough completion, clicks).
- Trial invites (personal links and campaign codes), trial rules (3 listings, 60 days live each).
- Super-Admin: sign-in with 2FA, customers list, trial invite creation, audit log.
- Legal pages live (Terms, Privacy, Refund, Acceptable use, DPA, subprocessors, DMCA, accessibility statement).

**Milestone B — must work by Oct 31**
- Billing through the merchant of record, plans, checkout, subscription lifecycle (grace, offline, deletion).
- Realtor website (home, properties page, holding page, style presets), setup guide and dashboard checklist.
- Teams: invites, custom roles, permissions, approval flow.
- Full analytics (seller report, weekly email, room-by-room drop-off).
- Full Super-Admin panel (section 12).
- Data export ("Download everything") and deletion flows.

**If the build runs late:** features move out of Milestone B into "after launch", never into the testing window. The founder decides what moves.

---

## 3. Decisions superseded during the discussion

Older notes contain these earlier versions. Use the new rule.

| Topic | Old rule (do not build) | Locked rule |
|---|---|---|
| Domain | `ye.yniidi.com/...` | `scrollwalk.com/username/listing-slug` |
| Roles | Fixed Owner and Agent roles | Admin (plan buyer) plus custom roles built from permissions (section 10) |
| Trial listings | Live forever | Each trial listing live for 60 days after publishing, then preview-only until subscribing |
| Lapsed accounts | Frozen immediately on lapse, username released at day 30 | 30-day grace (listings live, no new listings), then offline, data deleted after 6 months (section 11) |
| Lead sources | Per-channel share links (Instagram, WhatsApp…) | Two sources only: "Through a link" and "Found on Google" |
| Production AI | Unspecified / Gemini | GPT-6 Luna in production; Gemini free tier for development with sample data only |
| Backend | Supabase plus serverless functions | FastAPI backend, provider-agnostic Postgres |

---

## 4. Architecture

```
Browser ──► Frontend (Studio SPA + server-rendered public pages)
                │  typed client, session cookie only
                ▼
           FastAPI backend ──► Postgres (RLS)          [provider TBD by Oct 18]
                │          ──► Cloudflare R2 (media)   [served only via Cloudflare CDN]
                │          ──► Job queue + ffmpeg worker
                │          ──► Resend (email)
                │          ──► AI provider (text only)
                │          ──► Merchant of record (billing webhooks)
```

**Locked**
- **Backend:** FastAPI (Python), SQLAlchemy, Alembic migrations, Pydantic schemas.
- **Database:** Postgres 16 or 17, provider-agnostic. Development on local Postgres in Docker. Provider chosen by **Oct 18** (EU region preference noted for European customers). Portability rules:
  - Sign-in, roles and permissions live in FastAPI, never in provider features (no Supabase Auth, no provider RLS tooling).
  - Files never live in the database provider's storage.
  - Only extensions available everywhere: `pgcrypto`, `citext`, `pg_trgm`.
  - Jobs, emails and schedules run in our backend, never in provider functions.
  - Config through `DATABASE_URL`; moving providers is `pg_dump`/`pg_restore` plus one setting.
- **Media:** Cloudflare R2, **only ever served through Cloudflare's cache** on a custom domain (e.g. `media.scrollwalk.com`). Media never passes through the app server.
- **Uploads:** browser → short-lived presigned upload URL from the backend → R2 directly.
- **Video processing:** background job queue plus a separate ffmpeg worker. Where the worker runs is decided with hosting.
- **Email:** Resend, sending from `mail.scrollwalk.com` with SPF, DKIM and DMARC. `no-reply@` sends; replies go to `hello@` or `support@`. Set up as soon as possible to build sending reputation. YNIIDI mail stays separate.
- **AI:** one OpenAI-compatible client, switchable by settings (base URL, model, key). Production: **GPT-6 Luna**. Development: **Gemini free tier with sample data only**. Switch to Luna and run the full prompt test set by **Oct 19–20**.
- **Billing:** a merchant of record (Paddle, Lemon Squeezy, Dodo Payments or similar). **Essential**, because we sell globally as an individual and the MoR handles tax in every country and blocks sanctioned countries. Provider chosen during the build days; must accept an individual seller based in India.

**Open — must be decided on day 1 (Oct 10)**
- **How public pages are server-rendered.** Public realtor sites and listing pages must arrive from the server with title, description, preview image, structured data and main content in the HTML (link previews on WhatsApp, iMessage, Instagram and Facebook read only raw HTML). The Studio can stay a client-side app.
  - **Recommendation:** Next.js for the frontend (server-rendered public pages, client-rendered Studio), calling FastAPI. The prototype's React components carry over.
  - Alternative: keep the Vite SPA and have a server inject meta tags per URL. Weaker for SEO content.
- **Hosting** for the frontend and the FastAPI backend (Vercel for the frontend is the default assumption). Parked for the build days, but staging must exist by Oct 18.

---

## 5. Domains and URLs

- **Domain:** `scrollwalk.com` (owned).
- **Realtor site:** `scrollwalk.com/username`
- **Listing:** `scrollwalk.com/username/listing-slug`
- **Other realtor pages live in sections:** `/username/properties`, `/username/about`, `/username/contact`; later `/username/neighbourhoods/name`, `/username/journal/article`. These section words are reserved as listing slugs.
- **Studio:** `scrollwalk.com/studio`
- **Super-Admin:** separate path and sign-in (e.g. `scrollwalk.com/hq`), not linked from anywhere public.
- **Free preview listing:** `scrollwalk.com/preview/<random-id>`, owner-only, `noindex`, no link preview, not shareable.
- **Seller report:** `scrollwalk.com/username/listing-slug/report` (unguessable token required; see section 8.8).
- **Custom domains:** after launch; the architecture must allow them (canonical URL moves to the custom domain).

**Usernames**
- Unique, first come first served, **permanent** (never changed by the user).
- Lowercase letters, numbers and hyphens, 3–30 characters.
- Reserved words blocked: all system paths (`studio`, `hq`, `preview`, `signup`, `login`, `pricing`, `api`, `media`, …) and big brand names (`compass`, `kw`, `exp`, `remax`, `zillow`, …). Support handles disputes.
- Taken names get three live suggestions (`shyaam345`, `shyaamrealty`, `shyaam.homes` style).
- A "This will be your link forever" confirmation before saving.
- Claimed only by paid users and invited trial users, in the "About you" setup tile. It's the only mandatory setup step; if skipped, they're asked again on next sign-in.
- **Display name** is separate: shown on the site, can repeat across accounts, editable any time.
- Teams use the team or brokerage name.

**Listing slugs**
- Generated from the title; duplicates get `-2`, `-3`.
- Renaming a slug sends a **301 redirect** from the old address (keep a slug history table).
- Sold or removed listings show a "Sold" page linking to the realtor's other homes, never a 404. Sold listings stay indexed.

---

## 6. Data model

All IDs are random UUIDs (`gen_random_uuid()`), never sequential. Every table holding customer data has `workspace_id` and is covered by row-level security (section 9.1). Timestamps are `timestamptz`. Usernames and emails use `citext`.

The builder may refine columns, but the ownership rules, constraints and RLS coverage below are mandatory.

**Identity and access**
- `users` — id, email (citext, unique), email_verified_at, password_hash (Argon2id, nullable for Google-only), google_sub (unique, nullable), display_name, avatar_url, created_at, last_login_at, deleted_at.
- `sessions` — id (opaque random token stored hashed), user_id, created_at, expires_at, last_seen_at, ip_hash, user_agent, revoked_at.
- `email_codes` — id, user_id or email, purpose (verify, reset, email_change), code_hash, expires_at (10 min), attempts (max 5), consumed_at, created_at.
- `workspaces` — id, username (citext, unique), display_name, kind (solo, team), country_code, compliance_profile, currency_default, area_unit (sqft, sqm), timezone, plan_key, subscription_state, site_published_at, created_at, deleted_at.
- `memberships` — id, workspace_id, user_id, role_id (null = Admin), is_admin, invited_by, joined_at, removed_at. Exactly one `is_admin` member per workspace.
- `roles` — id, workspace_id, name, description, created_at.
- `role_permissions` — role_id, permission_key. Permission keys come from a fixed catalogue in code (section 10).
- `invitations` — id, workspace_id, email, role_id, token_hash, expires_at, accepted_at, invited_by.
- `username_history` / `reserved_usernames` — reserved list, released names with cooldown_until.

**Site and listings**
- `site_settings` — workspace_id (PK), brand fields, logo, photo, about, tagline, style_preset (Noir, Coastal, Terracotta, Evergreen), colours, contact methods (email, phone, WhatsApp, booking link), licence and registration fields per compliance profile, home sections content.
- `listings` — id, workspace_id, agent_member_id (the "listing agent", must have a licence number where the profile requires one), slug, title, subtitle (tagline), summary, location, price_amount, price_currency, price_label, bedrooms, bathrooms, area, area_unit, property_type, status (draft, pending_approval, published, sold, expired, offline), experience_type (photo, immersive), mobile_mode (rotate, fit, fill), is_trial, published_at, trial_expires_at, cover_media_id, compliance fields (e.g. energy rating, permit number), seo_title, seo_description, created_at, updated_at, deleted_at.
- `listing_slug_history` — listing_id, old_slug, changed_at (for 301s).
- `listing_sections` — id, listing_id, workspace_id, type (story, at_a_glance, spaces, location, faq, quote, cta, gallery, floor_plans, …), layout_variant, content (jsonb, validated per type), sort_order, is_visible.
- `listing_hero` — listing_id (PK), workspace_id, enabled, image_media_id (null = fallback), show_facts, show_price.
- `walkthrough_beats` — id, listing_id, workspace_id, at (0–1 progress), label, text.
- `media` — id, workspace_id, listing_id, kind (video_source, frame_sequence, gallery, floor_plan, hero, logo, photo), aspect (landscape, portrait), r2_key (random), status (uploading, processing, ready, failed), visibility (private, public), bytes, width, height, frame_count, frame_pattern, label, sort_order, created_at.
- `processing_jobs` — id, workspace_id, media_id, kind, status, attempts, error, started_at, finished_at, worker_minutes.

**AI**
- `ai_generations` — id, workspace_id, listing_id, kind (full, rewrite_section), provider, model, prompt_version, input_tokens, output_tokens, cost_usd, status, created_at. Used for rate limits (about 10 full regenerations per listing per day) and cost metering.

**Enquiries and analytics**
- `enquiries` — id, workspace_id, listing_id, name, email, phone, message, consent_text_version, status (new, contacted, closed), created_at. Buyer personal data: visible only to permitted members.
- `analytics_events` — id, workspace_id, listing_id (nullable for site pages), day, visitor_hash (daily-salted, no raw IP stored), source (link, search, internal), device, country, city, event (pageview, leave, walk_depth, gallery_open, floor_plan_view, enquiry_click, phone_tap, whatsapp_tap, booking_click), value, created_at. Partition or roll up daily.
- `analytics_daily` — rollups per workspace, listing, day.

**Billing and trials**
- `plans` — key, name, seats, listing_limit, features (jsonb), prices. **Editable from Super-Admin without code.**
- `subscriptions` — id, workspace_id, provider, provider_subscription_id, plan_key, status, current_period_end, cancel_at_period_end, lapsed_at, grace_ends_at, offline_at, delete_after.
- `billing_events` — id, provider_event_id (unique, for idempotency), type, payload, processed_at.
- `trial_invites` — id, type (personal, campaign), email (personal only), code (campaign only), token_hash (personal), listings_allowed (default 3), max_uses, uses, expires_at, note, created_by_staff_id, created_at.
- `trial_redemptions` — invite_id, workspace_id, redeemed_at, converted_at.
- `waitlist` — id, name, email, instagram_handle, market, created_at, invited_at.

**Legal**
- `legal_documents` — id, kind (terms, privacy, refund, aup, dpa), version, published_at, body.
- `legal_acceptances` — user_id, document_id, accepted_at, ip_hash.
- `compliance_acknowledgements` — workspace_id, user_id, accepted_at (first-publish notice).

**Platform (Super-Admin)**
- `staff_users` — id, email, password_hash, totp_secret (encrypted), staff_role_id (null = Super-Admin), created_at, disabled_at. **Separate from customer users.**
- `staff_roles`, `staff_role_permissions` — same pattern as workspace roles, over the Super-Admin permission catalogue.
- `staff_sessions` — separate cookie and table from customer sessions.
- `audit_log` — id, actor (staff or user), action, target_type, target_id, workspace_id, reason, metadata, created_at. **Append-only**: the app role can insert but never update or delete.
- `cost_entries` — month, category (hosting, database, R2, AI, email, worker, domain, other), amount, currency, source (metered, manual, invoice).
- `announcements`, `content_reports` (from "Report this listing"), `data_requests` (export, deletion).

---

## 7. API contract (outline)

FastAPI generates the OpenAPI schema; this section fixes the shape and permissions. Every endpoint lists its permission. Every response model is an explicit allow-list of fields.

**Conventions**
- JSON over HTTPS. Base path `/api/v1`.
- Auth by `HttpOnly; Secure; SameSite=Lax` session cookie, plus a CSRF token header on every state-changing request.
- Another workspace's record returns **404**, never 403.
- Errors: `{ "error": { "code": "...", "message": "..." } }`.
- Pagination: cursor-based.

**Groups**
- `/auth` — sign up, sign in, Google OAuth start/callback (state + PKCE), verify code, resend code, forgot/reset password, change email, sign out, sign out everywhere, me.
- `/workspaces` — current workspace, update settings, claim username (availability check + suggestions), compliance profile fields.
- `/listings` — CRUD, publish, unpublish, mark sold, submit for approval, approve; sections CRUD and reorder; hero settings; beats.
- `/listings/{id}/ai` — generate (streamed), rewrite section (streamed). Text-only payloads.
- `/media` — request presigned upload, confirm upload, list, update label/order, delete, processing status.
- `/enquiries` — public create (rate-limited, bot-protected), list, update status, export.
- `/analytics` — public event ingest (cookieless), summaries per listing and workspace, seller report data, weekly email preview.
- `/team` — members, invitations, roles, permissions catalogue.
- `/billing` — plans, checkout session, customer portal link, MoR webhooks (signature-verified, idempotent).
- `/trial` — redeem invite link or campaign code.
- `/export` — "Download everything" (async job, emailed link).
- `/public` — read-only, published content only: site by username, listing by username/slug, sitemap data. Served by the restricted public database role (section 9.1).
- `/hq` — Super-Admin endpoints, separate auth, staff permissions on every route.
- `/waitlist` — public create.
- `/report` — public "Report this listing".

---

## 8. Product features

### 8.1 Sign-up, sign-in and verification
- "Continue with Google" is the main button; name, email and password is the alternative.
- Email and password sign-ups verify with a **6-digit code** before payment or the free listing. Google sign-ups and invited team members skip it (already verified).
- Codes: valid 10 minutes, resend after 30 seconds, 5 attempts per code, rate-limited per email and per device, keyboard auto-fill (`autocomplete="one-time-code"`), "Wrong email? Change it".
- The same code flow handles forgot password and email changes.
- Signup includes agreeing to the Terms and Privacy Policy; the accepted version is recorded.

### 8.2 Entry paths and onboarding
- **Landing page** shows two buttons: "Get started" (plans) and "Try it free".
- **Path 1, Try it free:** sign up → verify → one tile to create a listing → private preview at `/preview/<id>`. No username. Brand and style come after subscribing.
- **Path 2, Get started:** choose plan → account → payment → "Your account is ready" → setup guide.
- **Trial invite:** personal link or campaign code → sign up with the trial applied → setup guide limited to what trials get (listings only, no site).
- Abandoned checkout: next sign-in returns them to the plan page.
- **Setup guide** (one big tile at a time, Continue and Skip, saves on Continue, resumes after closing the tab):
  1. **About you** — display name and photo (pre-filled from Google), brokerage, country, licence fields per compliance profile, **username (mandatory)**.
  2. **How buyers reach you** — email, phone, WhatsApp, booking link; one required to publish.
  3. **Your style** — choose a preset with a live mini preview.
  4. **Invite your team** — team plans only.
- After the guide: dashboard with the site as **Draft** and a big button: "Create your first listing", or for upgraded free users "Your first listing is ready" (Preview, one-click Publish). The free listing gets its real address when the username is set; it stays private until published.
- **Dashboard checklist:** skipped steps stay visible until done. Skipped steps show defaults in the preview only. Publishing with a default turns the step into a suggestion ("Make it yours: choose a style"). "Set up" progress and "Draft/Live" status are always shown separately. The checklist only shows launch features. "Hide setup guide" once publish requirements are met.

### 8.3 Publishing
- **Nothing auto-publishes.** Site, listings and later changes go live only when the user clicks Publish.
- **Publish requirements:** display name, one contact method, the fields the workspace's compliance profile marks as required, and finished walkthrough processing if the listing uses one.
- **First publish of anything** shows the compliance notice with an "I understand" tick (recorded).
- **Site and listings publish independently.**
  - A listing published while the site is offline lives at its URL with no links to the realtor site; its header and footer show the agent's name and contact options only.
  - `scrollwalk.com/username` shows a branded holding page (name, contact, no listings), `noindex`, until the site is live.
  - The site can go live with zero listings; the collection shows a designed empty state ("New residences coming soon").
  - When the site goes live, every published listing appears in its collection.
  - Unpublishing the site takes the site down; unpublishing a listing affects only that listing.
- A role without publish permission submits for approval (section 10).
- After publishing: "You're live" with the link(s), Copy and Share, and tips (Instagram bio, the "View property" button on an existing website).

### 8.4 Listing creation and AI content
1. **Details tab:** beds, baths, area, price and currency, location, property type, compliance fields.
2. **Sections tab, first visit:** one large "Tell us about this home" box with guidance hints and a minimum of about 40 words.
3. **"See preview"** plays: streamed "Writing your content…" (real streamed text), "Building your sections…", a green tick, then the preview.
4. **Customise** switches into on-page editing.

- **Sent to the AI:** the summary plus the structured listing details. **Never** images, contact data or personal data.
- **Output:** structured JSON in our section format: hero line, Story, At a glance, Spaces, Location, FAQ, walkthrough captions, SEO title, meta description, image alt text.
- **Guardrails:** use only the given facts (missing info becomes placeholders for the agent); fair-housing banned-phrase list applied in the prompt and checked on output; tone presets (Luxury, Modern, Warm, Minimal) for variety.
- **Failure:** one automatic retry, then a template fallback built from the details and summary ("We've started your page; you can refine it below").
- **Regenerate from summary** warns before replacing edits. Per-section **Rewrite** (shorter, more luxurious, more factual) inside Customise.
- **Limits:** about 10 full regenerations per listing per day.
- **The prompt** is a versioned file in the backend, tested against a fixed set of sample listings (fact accuracy, fair-housing filter, section format, tones), on Gemini in development and on Luna before trials.
- AI-drafted text is labelled for the realtor to review (Terms make them responsible).

### 8.5 Sections and the on-page editor
- The real listing page is the editor: click text to edit, click images to replace.
- Sections come from a library built in code by us, each with a few pre-designed layout variants, **each with a designed phone version**. Agents edit text only; no freeform positioning.
- New listings start with a default, pre-filled set of sections.
- Empty fields are hidden on the live site; in the editor they show as faint placeholders.
- "At a glance" defaults to Bedrooms, Bathrooms, Area and Experience, auto-filled from details; rename, edit, up to 6 boxes.
- "Add section" inserts one fixed high-quality template (which one is decided later).
- Reorder by dragging whole sections; hide or delete.
- Phone/desktop preview toggle.
- The editor shows a **still frame** instead of the running walkthrough (saves bandwidth and R2 load). Walkthrough captions are placed with a frame slider ("Add caption here").
- Public sections animate in on scroll (reveal), as in the prototype.

### 8.6 Media, gallery and floor plans
- **Media tab:** gallery photos, floor plans, hero image.
- **Gallery:** shown on the page as a horizontal scrolling strip with a very thin, theme-coloured scrollbar.
- **Floor plans:** upload one or more images, each with a label ("Ground floor", "First floor"…). A Floor plan section appears on the page once a plan exists; with several, buyers switch with labelled buttons. PDF conversion is an open item (section 15).

### 8.7 Walkthrough
**Uploads**
- The Walkthrough tab has **two slots**: landscape and portrait.
  - Portrait is used on phones; landscape on tablets and larger screens.
  - Landscape only: phones show the rotated player (current behaviour), with a "Turn your phone sideways" cue, or fit/fill per the listing's mobile mode.
  - Portrait only: desktop uses the **side layout** (sticky portrait stage with the story beside it).
  - 4K landscape uploads can auto-generate the portrait version (centred crop, optional left/right nudge). 1080p landscape on phones shows a deliberate cinematic band, never stretched.
  - **AI outpainting is never used** on property footage.
- **Filming guide** in the upload screen: horizontal, 4K, 1× zoom, gimbal or stabilised mode, slow constant pace, locked exposure.
- **Upload quality check:** warns if too shaky, short or dark, and states which layout case applies.
- **Processing** (ffmpeg worker): stabilisation, evening out walking speed, dropping duplicate frames, WebP frames in phone and desktop sizes, more frames on phones than the prototype's 120. The original video is kept as the source for re-processing and is never served to buyers. Publish waits for processing; a progress bar shows; the agent can leave and gets an email when ready.

**Player standard (pass/fail)**
- Canvas rendering, no React re-renders while scrolling.
- Smoothed scrolling (the camera glides, never jumps) and blending between neighbouring frames.
- Steady 60fps, 120fps on high-refresh screens.
- Only frames near the current position kept decoded (phone memory).
- First frame appears almost instantly; scrubbable before fully loaded (coarse-to-fine loading); everything from the Cloudflare cache.
- No "first few scrolls do nothing" hold.
- Rotation mid-walkthrough keeps the visitor's place.
- **Device test before launch:** a recent iPhone and a mid-range Android (e.g. Samsung A-series), Safari and Chrome, must pass.

### 8.8 Hero banner and first frame
- **Hero tab** in the listing editor (immersive listings): on/off, image upload (downscaled to about 2400px), text pulled from Details (location, title, tagline, beds/baths/area, price) with switches to hide facts or price, live preview with Desktop and Phone frames, "Play the transition".
- Default image when none is uploaded: a photo that isn't the walkthrough's first frame, else the walkthrough's closing frame, else the cover.
- **Public page:** full-screen banner in front of the walkthrough. The first scroll (wheel, touch, keys, or tapping "Scroll to step inside") plays a **1.8s cinematic cut**: text lifts away, the camera pushes in, shutters close to a gold seam of light, then open on the first frame as it pulls into focus. It lands exactly on the frame the player shows. Scrolling up at the start of the walkthrough plays it back (1.5s). Dragging the scrollbar or jumping to an anchor skips the banner. Reduced motion gets a short fade.
- With a hero, the first frame shows no title; instead it shows **"SCROLL TO WALK IN."** ("Scroll" and "walk" emphasised, gold dot), which animates in when the cut lands and fades with the first step. Hidden in rotate mode.
- Reference implementation: `src/public/ListingHero.tsx`, `src/styles/hero.css`, `src/admin/HeroTab.tsx` on `ye-prototype`.

### 8.9 Realtor website
- Based on the current YNIIDI Estates site: one refined structure plus **4 style presets** (Noir, Coastal, Terracotta, Evergreen).
- Home page shows 4–8 featured homes chosen by the realtor; `/properties` lists all homes with simple filters (price, beds, location, status).
- No visible Scrollwalk branding on paid sites. ("Made with Scrollwalk" on trial and free listings is an open item.)
- Neighbourhood pages and the journal come after launch (URL space reserved).

### 8.10 Enquiries and contact
- Contact channels: enquiry form (emailed to the agent and stored), booking link, WhatsApp, tap-to-call, tap-to-text.
- Consent line under the form: "By sending this, you agree to be contacted by [agent] about this property."
- Enquiries route to the listing's agent and to members with "view the whole team's enquiries".
- Bot protection and rate limiting on the public form.
- Enquiry alerts beyond email (WhatsApp) are an open item.

### 8.11 Analytics (realtor-facing, fully built at launch)
- **Cookieless.** No cookies, no raw IPs stored; a daily-salted visitor hash; bots (including headless browsers) and the realtor's own visits filtered.
- **Metrics:** views and unique visitors per listing and site over time; enquiries and enquiry rate; devices; country and city; **two sources only — "Through a link" and "Found on Google"** (search engines); walkthrough starts, average depth, completion, and drop-off by beat; clicks (gallery opens, floor plan views, enquiry clicks, phone, WhatsApp, booking).
- Walkthrough depth is reported on leave and by a 15-second heartbeat while visible (the leave beacon is unreliable on navigation).
- **Seller report:** a clean one-page report per listing, shareable by unguessable link and printable to PDF.
- **Weekly email summary** through Resend.
- The Studio dashboard design follows the approved prototype redesign: count-up numbers, sparklines, rings, skeleton loaders, staggered entrance animations, the sliding nav indicator, reduced-motion support. Numbers use the body sans font with lining tabular figures.

### 8.12 SEO and indexing
- Live sitemaps from the database: one index plus one per realtor, updated on publish, edit, sell and unpublish. `robots.txt` points to the index.
- One-time Google Search Console and Bing Webmaster verification.
- **IndexNow** pinged on every publish and update.
- `noindex`, no sitemap entry and no link preview for free previews, drafts, holding pages and unpublished sites.
- Sold listings stay indexed with "Sold" status. Expired and offline pages return **HTTP 503** ("temporarily unavailable") so search engines keep them.
- schema.org structured data for the agent and each listing; canonical URL on every public page; accurate last-modified dates.
- Link preview (Open Graph) image per listing; site-wide default preview image is a brand item.

### 8.13 Global readiness and compliance profiles
- Currency per listing, sq ft or sq m per workspace, international phone numbers, time zones.
- **Compliance profiles at launch:** US, UK, UAE, India, Canada, Australia, EU; "Another country" fallback with a free-text disclosure field.
  - **US:** licence number, brokerage, Equal Housing Opportunity logo automatic.
  - **UK:** redress scheme membership; material information fields (tenure, council tax band, price).
  - **UAE (Dubai):** broker registration number; advertising permit number per listing (QR where required).
  - **India:** RERA registration number.
  - **Canada, Australia:** licence details with local labels.
  - **EU:** energy rating (EPC / energy label) **required to publish**; optional agent registration number; defaults to EUR and m².
- Publishing is blocked until the profile's required fields are filled.
- Studio and templates are English at launch; realtors write content in any language.

---

## 9. Security (hard requirements)

The design goal: leaking one customer's data to another must require **two independent failures**, and automated tests try to cause a leak on every change.

### 9.1 Tenant isolation in two layers
- **Layer 1, the backend:** every request resolves the user, their workspace and their permissions. "Own listings only" and similar role rules are enforced here.
- **Layer 2, Postgres row-level security:** every table with customer data has `workspace_id`, `ENABLE` and `FORCE ROW LEVEL SECURITY`, and policies comparing it to `current_setting('app.workspace_id')`, set with `SET LOCAL` inside each request's transaction.
- **Database roles:** `app_owner` (migrations only, never used by the running app), `app_rw` (the API; not the table owner, no `BYPASSRLS`), `app_public` (read-only, policies allow only published sites and listings; drafts, enquiries and analytics invisible), `app_hq` (Super-Admin, cross-workspace reads, every access audited).
- No raw SQL string building; parameterised queries only.

### 9.2 Sign-in and sessions
- Passwords hashed with **Argon2id**.
- Sessions: opaque random tokens stored hashed, in an `HttpOnly; Secure; SameSite=Lax` cookie; never in localStorage. CSRF token on state-changing requests. Session rotation on sign-in and privilege change. "Log out everywhere".
- Email codes stored hashed, 10-minute expiry, 5 attempts.
- Rate limits on sign-in, code requests, password reset, enquiry form and public ingest.
- Google OAuth with `state` and PKCE.

### 9.3 Secrets
- The browser holds **only** the session cookie. No database, storage, email, AI or billing keys in the frontend.
- Secrets live only in server environment settings or a secret manager; separate keys for development, staging and production; rotatable.
- Secret scanning in CI blocks any commit containing a key. `.env*` files are gitignored.

### 9.4 Files
- Presigned upload URLs: short-lived, single-use, locked to the workspace's prefix, size and type checked.
- Object keys are random.
- Draft media private, shown in the Studio through expiring signed URLs. Media becomes public only when its listing is published.

### 9.5 API hygiene
- Random UUIDs; cross-workspace access returns 404.
- Response models are explicit allow-lists (password hashes, other users' emails and internal fields can't leak).
- Input validation with Pydantic; strict CORS allow-list; HTTPS with HSTS; CSP and standard security headers.
- Webhooks signature-verified and idempotent.

### 9.6 Staff access
- Staff sign in separately with **mandatory TOTP two-factor**.
- Viewing or acting inside a customer workspace ("log in as them") requires a typed reason and is written to the append-only audit log.

### 9.7 Proof
- **Cross-tenant leak tests** for every endpoint: workspace A tries to read, edit and delete workspace B's data; all must fail with 404. Also tested at the database layer with RLS (queries without `app.workspace_id` return nothing).
- Permission tests for every permission key.
- Tests for sign-in, codes, trials, lapse timelines and billing events.
- Dependency vulnerability scanning in CI.
- Encrypted backups with a tested restore.
- A **dedicated security review of the whole backend before Oct 23**.
- A written **72-hour breach notification plan**.

---

## 10. Teams, roles and permissions

- **Admin:** the person who buys the plan. Every permission, can't be removed. (A nicer name comes later.) **Admin-only, never grantable:** billing, changing the plan, deleting the workspace, transferring Admin.
- **Custom roles:** on the Team page, **Create role** asks for a name, a description, and on/off permissions. **No pre-built roles**; the screen offers suggestions ("Agent", "Marketing", "Coordinator") that pre-fill a name and suggested ticks the Admin can change.
- **Permissions are simple on/off switches.** Ownership is expressed as separate switches: the base switch covers the member's own items, a "whole team" switch (off by default) covers everyone's.

**Permission catalogue (v1)**
- Listings: create listings · edit own listings · edit the whole team's listings · publish own listings · publish the whole team's listings (includes approving) · delete own listings · delete the whole team's listings · appear as the listing agent (requires a licence number where the profile needs one).
- Enquiries: see own listings' enquiries · see the whole team's enquiries · export enquiries.
- Analytics: see own listings' analytics · see the whole team's analytics · create seller reports.
- Website: edit pages and sections · edit brand and style · edit contact details · publish the site.
- Team: invite and remove members · create and edit roles.

**Rules**
- A member can never grant permissions they don't have themselves.
- A role that can edit but not publish sends listings to **Waiting for approval**; anyone with the matching publish permission approves.
- Each member has exactly one role. Editing a role applies immediately. A role can't be deleted until its members are moved.
- When a member leaves, their listings stay with the workspace and are reassigned.
- Teams exist only on Team and Brokerage plans; each member uses a seat.
- Every permission is checked in FastAPI on every request; hiding buttons is presentation only.

---

## 11. Plans, trials and account lifecycle

**Plans** (prices parked; limits are placeholders, editable in Super-Admin)
- Agent: 1 user, up to 15 active listings.
- Team: up to 10 users, up to 50 active listings, roles.
- Brokerage: up to 50 users, unlimited listings, custom domain (after launch), dedicated onboarding. Sales-led.
- A possible cheap "Keep live" plan is parked for the pricing discussion.

**Free preview (Try it free):** one private listing, owner-only, not shareable, not indexed, no link preview.

**Trial invites (created in Super-Admin)**
- **Personal invite link** (default): tied to one email, single use, unguessable.
- **Campaign code** (e.g. `REZA30`): usage cap and expiry date.
- Each records listings allowed (default 3), invite expiry, a note, redemption and conversion.
- **Trial rules:** listings only, no website. **3 listings ever created** (deleting doesn't free a slot). A size cap on trial walkthroughs (exact limit set in Super-Admin). Studio access to edit and see enquiries and analytics.
- **Each trial listing is live for 60 days after it's published**, then preview-only. Reminder emails 7 days and 1 day before; countdown in the Studio. Expired pages show the 503 "temporarily unavailable" page. Subscribing brings every expired listing back live immediately at the same address.

**Subscription lapse timeline**
- **Day 0 (subscription ends):** 30-day grace. Site and listings stay live, enquiries keep arriving, **no new listings can be created**, existing listings can still be edited (price, Sold). Reminder emails at the start, 7 days left, 1 day left.
- **Day 30:** site and listings show the 503 "temporarily unavailable" page; the Studio becomes read-only.
- **Throughout:** "Download everything" (original videos, photos, floor plans, text) stays available.
- **6 months after expiry:** permanent deletion, with warning emails 30 days and 7 days before.
- **Resubscribing any time before deletion** restores everything exactly as it was, at the same addresses.
- **Username:** held until deletion at 6 months, then a 60-day cooldown during which nobody else can claim it (old links show a neutral "no longer available" page) and only the original owner can reclaim it.

**Billing rules**
- Refunds: **none**. Cancel anytime; access continues to the end of the paid period. Stated clearly at checkout. Policy says "except where required by law".
- Auto-renewal terms shown at checkout; one-click cancellation in the Studio; reminder email before annual renewals.
- Business customers only (stated in the Terms).

---

## 12. Super-Admin panel

A separate application area for the founder and staff. Never visible to customers.

**Dashboard**
- Customers: every customer, signup date, plan; most popular plan.
- Growth: signups over time and their source (link, Google, referral, invite); funnel (signed up → finished setup → first listing published → paid); trial conversion and time to convert; waitlist size.
- Revenue: total revenue, MRR and its monthly movements (new, expansion, contraction, churned, reactivation), ARR, churn by customers and by revenue, ARPU, LTV, failed payments, refunds, upcoming renewals, MoR fees and tax, net revenue.
- Profit: revenue minus costs, overall and **per customer**.
- Usage: listings, walkthrough views and enquiries across the platform, AI requests and cost, storage and database size, video processing minutes, emails sent, customers near plan limits.
- Costs: total and breakdown (hosting, database, R2, AI, email, worker, domain, other). Metered automatically where we can (AI tokens × price from `ai_generations`, R2 and Resend usage); fixed bills entered monthly; monthly reconciliation against invoices; one display currency.
- Health: uptime, errors, slow pages, failed processing jobs, bounced emails, stuck jobs, failed logins and suspicious activity.

**Actions**
- Find a customer; open their workspace read-only; "log in as them" with a typed reason, audited.
- Extend a trial, give a free plan, change a plan, freeze or unfreeze, refund (through the MoR).
- Reset a customer's sign-in or two-factor.
- Data export and deletion requests.
- Moderation: reports from "Report this listing", take down listings, ban accounts.
- Plan limits and pricing as settings (no code changes).
- Trial invites: create personal links and campaign codes, track use and conversion.
- Announcements: Studio banner or email to all customers.
- Append-only audit log of all staff actions.

**Staff roles**
- Same role builder as workspaces, over the Super-Admin permission catalogue (view customers, log in as customer, refunds, see revenue, moderate content, create trial invites, edit pricing, …).
- Super-Admin only: managing staff and staff roles, payout and billing settings, deleting the Super-Admin account.
- TOTP two-factor required for every staff member. Sensitive actions (log in as customer, refunds, data deletion) require a typed reason and are logged.

---

## 13. Legal and compliance

**Seller entity:** the founder as an individual sole proprietor, "[Full name], trading as Scrollwalk", [city], India. Governing law India; disputes by online arbitration. A company will be registered once revenue is steady (find-and-replace plus notice to users). Needs a contact email and a postal address (city-level business address or PO box).

**Scrollwalk's pages (drafted by the Cursor agent from this document, then reviewed by a lawyer experienced in international SaaS and GDPR before Oct 23)**
- **Terms of Service:** content ownership (realtor owns, grants us a hosting and display licence), content rights (videos, photos, permission to market the property), AI text responsibility and fair-housing wording, 18+ and business use only, trial terms, lapse timeline, no refunds, liability capped at fees paid in the last 12 months, 30 days' notice of material changes, acceptable use (no fake listings, no discriminatory wording, no others' content).
- **Privacy Policy:** what we collect from realtors and why, retention periods (section 11), cookieless analytics and the single essential cookie (no cookie banner), text-only AI processing on paid API tiers (no training on customer data), subprocessors, international transfers (standard contractual clauses), rights requests, breach notification.
- **Refund and cancellation policy.**
- **Data processing agreement** (realtor is controller for buyer enquiries, we are processor) and a **subprocessor list** (hosting, database, R2, Resend, AI provider, MoR).
- **Copyright takedown (DMCA) policy** and a designated agent registered with the US Copyright Office.
- **Accessibility statement.**
- **Grievance officer** contact (India IT Rules) — the founder.
- **EU and UK representatives** appointed (GDPR Article 27).

**Every realtor site gets automatically**
- A generated privacy notice naming the realtor as responsible, linked in the footer.
- The enquiry consent line.
- The compliance profile's disclosures (licence, brokerage, EHO logo, energy rating, permits).
- "Report this listing" on every listing page (covers DMCA, the EU Digital Services Act and India's IT rules).

**Agreement tracking:** accepted document versions recorded per user; material changes require re-acceptance.

**Other global rules**
- Merchant of record for tax worldwide and sanctions blocking.
- WCAG 2.1 AA accessibility across public pages and the Studio.
- Marketing emails strictly opt-in with unsubscribe (CASL-level); transactional emails exempt.
- Breach notification within 72 hours.

---

## 14. Quality gates and cross-review

**CI must pass before merge**
- Type checks and lint (frontend and backend).
- Backend unit and integration tests, including **all cross-tenant leak tests** and permission tests.
- Generated typed client is up to date with the OpenAPI schema.
- Secret scanning and dependency scanning.

**Cross-review (required before Milestone A and again before launch)**
- Claude reviews the backend's security-critical code: sign-in and sessions, RLS policies and database roles, permission checks, billing webhooks, presigned uploads and media visibility, Super-Admin access and audit logging.
- The Cursor agent reviews the frontend's session handling, CSRF use, form handling and anything that renders user content (XSS).

**Before trials (Oct 18–23)**
- Full security review of the backend.
- AI prompt test set passing on GPT-6 Luna.
- Walkthrough device test passing.
- Staging deploy with production-like configuration; backup restore tested.
- Legal pages live after lawyer review.

---

## 15. Open items

**Decide on day 1**
1. Server rendering approach for public pages (recommendation: Next.js frontend).

**Decide by Oct 18**
2. Database provider (any Postgres 16/17; consider EU region).
3. Hosting for frontend, backend and the ffmpeg worker; staging live.

**Decide during the build days**
4. Pricing, the "Keep live" plan, which plans get which analytics.
5. Billing provider (must accept an Indian individual seller).
6. Exact trial walkthrough size cap.
7. "Made with Scrollwalk" credit (trial, free, paid; can agents turn it off).
8. Featured homes on the Scrollwalk landing page (agent opt-in tiles).
9. The founder's contact-channel idea.
10. Higher-quality walkthrough frame options.
11. PDF floor plans (convert automatically or images only).
12. How much of the Studio works on phones at launch.
13. Enquiry alerts beyond email (WhatsApp).
14. The future of the YNIIDI Estates site (stay separate or become customer #1).
15. Brand basics: trademark search (India, US, EU), social handles, favicon, default link preview image.
16. The fixed template behind "Add section".
17. Tagline refinement (after the product is built).

**After launch**
- Custom domains, neighbourhood pages and journal, translated templates and right-to-left languages, local pricing, EU-only data storage, advanced search and map view, MLS/IDX feeds, team directory pages, voice-note listing summaries, Apple sign-in.

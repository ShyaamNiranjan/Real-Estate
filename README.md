# AURELIA by YNIIDI — Real-estate marketplace + Studio CMS

A brand-led property marketplace with immersive scroll walkthroughs, photo listings, and an admin studio for managing everything without code.

- **Live:** https://realestate.yniidi.com
- **Stack:** Vite · React 19 · TypeScript · React Router 7 · Supabase (Postgres, Auth, Storage) · Vercel

## Routes

| Route | What it is |
| --- | --- |
| `/` | Marketplace: full-bleed brand hero, the collection, enquiries |
| `/listing/:slug` | Listing page. `immersive` listings play a canvas frame-sequence walkthrough; `photo` listings get a full-bleed cover and gallery. Sections render from `page_sections`. |
| `/admin/login` | Studio sign-in (Supabase email + password) |
| `/admin` | Listings dashboard (filter by draft / preview / published, search) |
| `/admin/listings/new` | Create a draft with starter sections |
| `/admin/listings/:id/{details,media,sections,experience}` | Listing editor |
| `/admin/enquiries` | Enquiry inbox |
| `/admin/settings` | Brand name, home hero, colours, contact |

Drafts and previews are only readable by admins (enforced by Postgres RLS). Signed-in admins can open `/listing/:slug` for any status to preview; a bar marks the page as not public.

## Local development

```bash
cp .env.example .env.local   # fill in VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY
npm install
npm run dev
```

Keyboard: `N` new listing and `/` search on the dashboard; `Ctrl/⌘ S` saves any editor.

## Environment variables

| Variable | Where | Purpose |
| --- | --- | --- |
| `VITE_SUPABASE_URL` | client build | Supabase project URL |
| `VITE_SUPABASE_ANON_KEY` | client build | Public anon key (safe to expose; RLS protects data) |
| `SUPABASE_SERVICE_ROLE_KEY` | local tooling only | Admin bootstrap script. **Never** expose or prefix with `VITE_`. |
| `SUPABASE_DB_PASSWORD` | local tooling only | `supabase db push` |
| `SUPABASE_PROJECT_REF` | local tooling only | Linking the Supabase CLI |

Only `VITE_*` variables are bundled into the browser. No secrets are hard-coded.

## Self-hosting (one-time licence)

1. **Create a Supabase project** (any region). Note the URL, anon key, service role key and DB password.
2. **Apply the schema** from `supabase/migrations/` in order:
   ```bash
   npx supabase link --project-ref YOUR_REF
   npx supabase db push --password "$SUPABASE_DB_PASSWORD"
   ```
   This creates tables, RLS policies, storage buckets (`listing-images`, `listing-videos`, `listing-frames`) and seeds two demo listings.
3. **Create the first admin.** New sign-ups are always `member`; admin must be granted explicitly:
   ```bash
   node scripts/bootstrap-admin.mjs you@yourdomain.com
   ```
   The generated password is appended to `.env.local` as `ADMIN_BOOTSTRAP_PASSWORD`. Sign in at `/admin/login` and change it from the Supabase dashboard if you like.
   To promote an existing user instead, run in SQL: `update public.profiles set role = 'admin' where email = '…';`
4. **Recommended:** in Supabase → Authentication → Providers, disable public email sign-ups. The app never offers sign-up, and RLS already blocks non-admins, but closing it removes noise.
5. **Deploy the SPA** anywhere that serves static files with a fallback to `index.html`:
   - **Vercel:** import the repo, set `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY`, deploy. `vercel.json` already handles rewrites and caching.
   - **Netlify / Cloudflare Pages / Nginx:** build with `npm run build`, publish `dist/`, and add a catch-all rewrite to `/index.html`.
6. **Brand it** in `/admin/settings` (name, hero, colours, contact).

## Immersive walkthroughs

A listing with `experience_type = immersive` and at least one `frame_sequence` media row renders the fixed-stage canvas walkthrough (`src/components/ScrollExperience.tsx`). Each sequence row stores:

- `public_url` — folder URL (e.g. `/media/sequence` or a Supabase Storage public folder)
- `frame_pattern` — file name with a `{###}` placeholder, e.g. `frame-{###}.jpg` → `frame-001.jpg`
- `frame_count` — any number of frames; scroll distance stays constant
- `aspect` — `landscape` (desktop) and optionally `portrait` (phones)

In the Studio → Walkthrough tab you can point at existing folders or upload a set of frames straight to the `listing-frames` bucket. Automatic video → frames extraction is not in v1; the tab shows the FFmpeg commands to export frames locally.

## Project layout

```
src/
  components/ScrollExperience.tsx   canvas walkthrough engine (fixed stage, no pinning)
  public/                           marketplace, listing page, section renderer, enquiry form
  admin/                            Studio CMS (lazy-loaded)
  lib/                              supabase client, auth + site settings context, data access
  types/                            DB row types and JSON content shapes
supabase/migrations/                schema, RLS, storage, seed
scripts/bootstrap-admin.mjs         first-admin helper (service role, local only)
```

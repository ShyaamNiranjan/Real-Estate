-- YNIIDI Estates: rebrand, footer details, CMS-managed home page sections

-- ---------------------------------------------------------------------------
-- Site settings: office details, RERA, demo note; brand becomes YNIIDI Estates
-- ---------------------------------------------------------------------------
alter table public.site_settings
  add column if not exists address text,
  add column if not exists rera_number text,
  add column if not exists demo_note text;

alter table public.site_settings alter column brand_name set default 'YNIIDI Estates';

update public.site_settings set
  brand_name = 'YNIIDI Estates',
  tagline = 'Private residences in Chennai',
  hero_body = case
    when hero_body is null
      or hero_body = 'A private collection of modern residences, each presented as a place to move through, not a page to skim.'
    then 'A private collection of modern residences across Chennai, each presented as a place to move through, not a page to skim.'
    else hero_body
  end,
  footer_note = case
    when footer_note is null or footer_note ilike '%aurelia%' then 'Viewings by appointment, Monday to Saturday.'
    else footer_note
  end,
  contact_phone = coalesce(contact_phone, '+91 44 4567 8900'),
  address = coalesce(address, 'Level 3, 18 Boat Club Avenue, R.A. Puram, Chennai 600 028'),
  rera_number = coalesce(rera_number, 'TN/RERA/DEMO/2026'),
  demo_note = coalesce(demo_note, 'Demo site · Sample listings and content'),
  socials = case
    when socials = '{}'::jsonb then '{
      "instagram": "https://www.instagram.com/yniidi",
      "linkedin": "https://www.linkedin.com/company/yniidi",
      "youtube": "https://www.youtube.com/@yniidi"
    }'::jsonb
    else socials
  end;

-- ---------------------------------------------------------------------------
-- Home sections (marketplace home page, between the hero and the footer)
-- ---------------------------------------------------------------------------
create table if not exists public.home_sections (
  id uuid primary key default gen_random_uuid(),
  preset text not null
    check (preset in (
      'collection', 'walkthrough', 'stats', 'services',
      'approach', 'neighbourhoods', 'testimonials', 'contact'
    )),
  sort_order integer not null default 0,
  is_visible boolean not null default true,
  title text,
  body text,
  content jsonb not null default '{}'::jsonb,
  style jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists home_sections_sort_idx on public.home_sections (sort_order);

drop trigger if exists home_sections_set_updated_at on public.home_sections;
create trigger home_sections_set_updated_at
before update on public.home_sections
for each row execute function public.set_updated_at();

alter table public.home_sections enable row level security;

drop policy if exists "Public can read visible home sections" on public.home_sections;
create policy "Public can read visible home sections"
  on public.home_sections for select
  using (is_visible = true or public.is_admin());

drop policy if exists "Admins manage home sections" on public.home_sections;
create policy "Admins manage home sections"
  on public.home_sections for all
  using (public.is_admin())
  with check (public.is_admin());

-- ---------------------------------------------------------------------------
-- Demo content (sample copy; no real firms or people)
-- ---------------------------------------------------------------------------
insert into public.home_sections (preset, sort_order, title, body, content, style)
select v.preset, v.sort_order, v.title, v.body, v.content::jsonb, v.style::jsonb
from (
  values
    (
      'collection', 0,
      'The collection',
      null,
      '{}',
      '{}'
    ),
    (
      'approach', 1,
      null,
      'In sequence, in daylight, at the pace of walking through it. Arrive at the door, cross the threshold, find the light at the back of the house. Then decide whether to visit.',
      '{"eyebrow":"How we present a home"}',
      '{}'
    ),
    (
      'walkthrough', 2,
      'Walk before you visit.',
      E'Every residence we represent is filmed room by room and presented as a walkthrough you control with a scroll. Arrive at the gate, cross the threshold and find the light at the back of the house before you book a single visit.\n\nFewer wasted Saturdays. Far more certain decisions.',
      '{
        "eyebrow": "The difference",
        "ctaLabel": "Walk through AURELIA",
        "href": "/listing/aurelia",
        "visual": "loop",
        "caption": "AURELIA · Immersive walkthrough",
        "image": "/media/sequence/frame-001.jpg",
        "frames": {"baseUrl": "/media/sequence", "pattern": "frame-{###}.jpg", "count": 240, "listing": "aurelia"}
      }',
      '{"tone":"dark"}'
    ),
    (
      'stats', 3,
      null,
      null,
      '{
        "items": [
          {"value": "14", "label": "Years in Chennai"},
          {"value": "320+", "label": "Residences placed"},
          {"value": "11", "label": "Neighbourhoods"},
          {"value": "38", "label": "Average days to close"}
        ]
      }',
      '{"tone":"dark"}'
    ),
    (
      'services', 4,
      'What we do',
      'Four ways we work with families and companies across Chennai.',
      '{
        "eyebrow": "Services",
        "items": [
          {"title": "Buy", "body": "A short list of residences that fit, walked through on screen before you visit in person."},
          {"title": "Sell", "body": "Discreet marketing, filmed walkthroughs, and viewings only with qualified buyers."},
          {"title": "Lease", "body": "Furnished and unfurnished homes for families and companies, managed end to end."},
          {"title": "Private viewings", "body": "One party at a time, on your schedule, with the drawings and documents on the table."}
        ]
      }',
      '{"tone":"light"}'
    ),
    (
      'neighbourhoods', 5,
      'Neighbourhoods',
      'We know these streets house by house. Most of our residences sit within a few kilometres of the sea.',
      '{
        "eyebrow": "Where we work",
        "items": [
          {"title": "Adyar", "meta": "600 020", "body": "Tree-lined streets between the river and the sea, with the city''s best schools close by."},
          {"title": "Boat Club", "meta": "600 028", "body": "Quiet avenues, generous plots and old gardens. Chennai''s most private address."},
          {"title": "ECR", "meta": "600 115", "body": "Beach houses and weekend villas along the coast road, twenty minutes past the city."},
          {"title": "OMR", "meta": "600 097", "body": "New towers and gated communities along the IT corridor, with room to grow."},
          {"title": "Anna Nagar", "meta": "600 040", "body": "Wide, planned roads, established parks and a settled family neighbourhood."},
          {"title": "Besant Nagar", "meta": "600 090", "body": "Bungalows on shaded lanes, a short walk from Elliot''s Beach."}
        ]
      }',
      '{"tone":"dark"}'
    ),
    (
      'testimonials', 6,
      'In their words',
      null,
      '{
        "eyebrow": "Clients",
        "items": [
          {"quote": "We walked through the house four times on a laptop before we flew in from Singapore. The visit only confirmed what we already knew.", "name": "Priya R.", "context": "Adyar · Bought in 2025"},
          {"quote": "They sold our home without a single open house. Every viewing was someone who was already serious.", "name": "Karthik & Meera S.", "context": "Boat Club · Sold in 2024"},
          {"quote": "Clear numbers, no pressure, and the paperwork was finished before we expected it.", "name": "Arjun V.", "context": "OMR · Leased in 2025"}
        ]
      }',
      '{"tone":"stone"}'
    ),
    (
      'contact', 7,
      'Tell us what you are looking for.',
      'Viewings are arranged one at a time. Off-market residences are shared on request.',
      '{"eyebrow":"Private enquiries"}',
      '{}'
    )
) as v(preset, sort_order, title, body, content, style)
where not exists (select 1 from public.home_sections);

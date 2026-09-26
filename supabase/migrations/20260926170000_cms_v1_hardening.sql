-- CMS v1 hardening: safe signups, experience config, marketplace hero, demo data fixes

-- ---------------------------------------------------------------------------
-- Signups must never grant admin. New auth users get role 'member';
-- admins are promoted explicitly (service role / SQL).
-- ---------------------------------------------------------------------------
alter table public.profiles drop constraint if exists profiles_role_check;
alter table public.profiles
  add constraint profiles_role_check check (role in ('admin', 'member'));
alter table public.profiles alter column role set default 'member';

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.profiles (id, email, full_name, role)
  values (
    new.id,
    new.email,
    coalesce(new.raw_user_meta_data->>'full_name', split_part(new.email, '@', 1)),
    'member'
  )
  on conflict (id) do nothing;
  return new;
end;
$$;

-- Enquiries: public inserts are always 'new'
drop policy if exists "Anyone can create enquiries" on public.enquiries;
create policy "Anyone can create enquiries"
  on public.enquiries for insert
  with check (status = 'new');

-- ---------------------------------------------------------------------------
-- Listings: immersive experience copy (hero + scroll beats) lives with the listing
-- ---------------------------------------------------------------------------
alter table public.listings
  add column if not exists experience jsonb not null default '{}'::jsonb;

-- ---------------------------------------------------------------------------
-- Site settings: marketplace hero
-- ---------------------------------------------------------------------------
alter table public.site_settings
  add column if not exists hero_headline text,
  add column if not exists hero_body text,
  add column if not exists hero_image_url text,
  add column if not exists hero_cta_label text,
  add column if not exists footer_note text;

update public.site_settings set
  brand_name = 'AURELIA',
  tagline = 'Private residences by YNIIDI',
  hero_headline = coalesce(hero_headline, 'Homes you can walk before you visit'),
  hero_body = coalesce(hero_body, 'A private collection of modern residences, each presented as a place to move through, not a page to skim.'),
  hero_image_url = coalesce(hero_image_url, '/media/sequence/frame-001.jpg'),
  hero_cta_label = coalesce(hero_cta_label, 'View the collection'),
  footer_note = coalesce(footer_note, 'AURELIA by YNIIDI. Viewings by appointment.');

-- ---------------------------------------------------------------------------
-- Demo data fixes: frame patterns match files on disk (frame-001.jpg)
-- ---------------------------------------------------------------------------
update public.listings set
  cover_image_url = '/media/sequence/frame-001.jpg',
  experience = '{
    "hero": {
      "brand": "AURELIA",
      "line": "Light, held in place",
      "support": "A modern villa built around air, water, and quiet.",
      "scrollHint": "Scroll to enter"
    },
    "beats": [
      {"id": "facade", "side": "left", "at": 0.05, "label": "Arrival", "text": "Pale stone, clean shadow. The house waits without announcing itself."},
      {"id": "threshold", "side": "right", "at": 0.15, "label": "Threshold", "text": "One step in, the ceiling lifts and the noise drops."},
      {"id": "living", "side": "left", "at": 0.29, "label": "The Core", "text": "Marble, blackened wood, daylight. Cooking and gathering share one room."},
      {"id": "dining", "side": "right", "at": 0.46, "label": "Open Edge", "text": "Walls slide away. The floor keeps going, out to the water."},
      {"id": "oasis", "side": "left", "at": 0.64, "label": "Water & Shade", "text": "Terraced pools, low fountains, palms. Afternoons take their time here."}
    ]
  }'::jsonb
where slug = 'aurelia';

update public.listing_media set
  frame_pattern = 'frame-{###}.jpg'
where kind = 'frame_sequence'
  and listing_id = (select id from public.listings where slug = 'aurelia');

update public.listing_media set
  public_url = '/media/sequence-portrait-lite',
  frame_count = 120,
  label = 'Portrait sequence (lite)'
where kind = 'frame_sequence'
  and aspect = 'portrait'
  and listing_id = (select id from public.listings where slug = 'aurelia');

-- Richer AURELIA sections
update public.page_sections set
  title = 'A house planned around the middle of the day.',
  body = 'AURELIA is built in three materials and one idea: let the light through. Rooms run long and uninterrupted, from the entry to the glass wall at the back, then out to water and deck.',
  preset = 'text',
  layout = 'default',
  style = '{"tone":"light"}'::jsonb
where preset = 'hero'
  and listing_id = (select id from public.listings where slug = 'aurelia');

update public.page_sections set
  title = 'Come and stand in it.',
  body = 'Viewings are arranged one at a time, with the architect''s drawings on the table.',
  content = '{"ctaLabel":"Request a private viewing","ctaAction":"enquiry"}'::jsonb
where preset = 'cta'
  and listing_id = (select id from public.listings where slug = 'aurelia');

-- ---------------------------------------------------------------------------
-- Second demo listing: photo experience
-- ---------------------------------------------------------------------------
with listing as (
  insert into public.listings (
    slug, title, subtitle, summary, status, experience_type, cover_image_url,
    price_label, location, bedrooms, bathrooms, area_sqft, sort_order, published_at
  )
  values (
    'the-garden-house',
    'The Garden House',
    'Timber, glass, and a lawn that runs to the door',
    'A two-storey family home wrapped in warm cedar, with a double-height stair hall and a pool garden on the south side.',
    'published',
    'photo',
    '/frames/frame-01.jpg',
    'From $4.9M',
    'Garden district',
    3,
    3.5,
    3280,
    2,
    now()
  )
  on conflict (slug) do nothing
  returning id
),
media as (
  insert into public.listing_media (listing_id, kind, public_url, label, aspect, sort_order)
  select listing.id, 'gallery', '/frames/frame-' || lpad(n::text, 2, '0') || '.jpg', null, 'landscape', n
  from listing, generate_series(1, 10) as n
  returning listing_id
)
insert into public.page_sections (listing_id, preset, title, body, layout, content, style, sort_order)
select (select id from listing), v.preset, v.title, v.body, v.layout, v.content::jsonb, v.style::jsonb, v.sort_order
from (
  values
    ('text', 'Warm on the outside, bright on the inside.', 'Cedar cladding and white render outside; inside, a stair of floating treads rises through a two-storey glass hall. The living room opens straight onto the garden.', 'default', '{}', '{"tone":"light"}', 0),
    ('specs', 'At a glance', null, 'tiles', '{"items":[{"label":"Bedrooms","value":"3"},{"label":"Bathrooms","value":"3.5"},{"label":"Interior","value":"3,280 sqft"},{"label":"Levels","value":"Two"}]}', '{}', 1),
    ('gallery', 'Inside', null, 'full', '{}', '{}', 2),
    ('tiles', 'The rooms that matter', null, 'tiles', '{"items":[{"title":"Stair hall","body":"Double height, with daylight from three sides."},{"title":"Kitchen","body":"Waterfall marble island, dark joinery kept calm."},{"title":"Pool garden","body":"Twelve metres of water beside a shaded cabana."}]}', '{}', 3),
    ('cta', 'See it on a weekday morning.', 'That is when the light is best. We arrange one viewing at a time.', 'default', '{"ctaLabel":"Arrange a viewing","ctaAction":"enquiry"}', '{}', 4)
) as v(preset, title, body, layout, content, style, sort_order)
where exists (select 1 from listing);

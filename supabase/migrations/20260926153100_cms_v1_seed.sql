-- Seed: brand settings + AURELIA demo listing (published immersive)

insert into public.site_settings (
  brand_name,
  tagline,
  primary_color,
  accent_color,
  background_color,
  contact_email
)
select
  'AURELIA',
  'Immersive property experiences',
  '#c4a574',
  '#0c0e0d',
  '#f5f0e8',
  'hello@yniidi.com'
where not exists (select 1 from public.site_settings);

with listing as (
  insert into public.listings (
    slug,
    title,
    subtitle,
    summary,
    status,
    experience_type,
    cover_image_url,
    price_label,
    location,
    bedrooms,
    bathrooms,
    area_sqft,
    sort_order,
    published_at
  )
  values (
    'aurelia',
    'AURELIA',
    'A modern villa, felt before you arrive',
    'Bright open-plan living, chef kitchen, and a pool terrace — walk the home through a scroll-led experience.',
    'published',
    'immersive',
    '/media/sequence/frame_0001.jpg',
    'By appointment',
    'Private estate',
    4,
    4,
    5200,
    1,
    now()
  )
  on conflict (slug) do update set
    title = excluded.title,
    subtitle = excluded.subtitle,
    summary = excluded.summary,
    status = excluded.status,
    experience_type = excluded.experience_type,
    updated_at = now()
  returning id
),
media as (
  insert into public.listing_media (
    listing_id, kind, public_url, aspect, frame_count, frame_pattern, sort_order, label
  )
  select
    listing.id,
    'frame_sequence',
    '/media/sequence',
    'landscape',
    240,
    'frame_{####}.jpg',
    0,
    'Landscape sequence'
  from listing
  union all
  select
    listing.id,
    'frame_sequence',
    '/media/sequence-portrait',
    'portrait',
    120,
    'frame_{####}.jpg',
    1,
    'Portrait sequence'
  from listing
  returning listing_id
)
insert into public.page_sections (
  listing_id, preset, title, body, layout, content, style, sort_order, is_visible
)
select
  (select id from listing),
  v.preset,
  v.title,
  v.body,
  v.layout,
  v.content::jsonb,
  v.style::jsonb,
  v.sort_order,
  true
from (
  values
    (
      'hero',
      'Arrive differently',
      'Scroll through the home before you visit.',
      'full',
      '{}',
      '{"tone":"dark"}',
      0
    ),
    (
      'specs',
      'At a glance',
      null,
      'tiles',
      '{"items":[{"label":"Bedrooms","value":"4"},{"label":"Bathrooms","value":"4"},{"label":"Area","value":"5,200 sqft"},{"label":"Experience","value":"Immersive"}]}',
      '{}',
      1
    ),
    (
      'tiles',
      'Spaces',
      'Facade, living, kitchen, pool — each beat of the walkthrough.',
      'tiles',
      '{"items":[{"title":"Facade","body":"White masonry, warm wood, black-framed glass"},{"title":"Living","body":"Open plan with high-gloss floors"},{"title":"Pool","body":"Terrace light at the end of the path"}]}',
      '{}',
      2
    ),
    (
      'cta',
      'Ready to see it in person?',
      'Request a private viewing.',
      'default',
      '{"ctaLabel":"Enquire","ctaAction":"enquiry"}',
      '{}',
      3
    )
) as v(preset, title, body, layout, content, style, sort_order)
where not exists (
  select 1 from public.page_sections ps
  where ps.listing_id = (select id from listing)
);

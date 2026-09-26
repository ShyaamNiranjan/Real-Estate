-- AURELIA / YNIIDI Real Estate CMS v1
-- Admin-only CMS, listings, sections, media, enquiries

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------------
-- Helpers
-- ---------------------------------------------------------------------------
create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

-- ---------------------------------------------------------------------------
-- Profiles (Admin)
-- ---------------------------------------------------------------------------
create table public.profiles (
  id uuid primary key references auth.users (id) on delete cascade,
  email text,
  full_name text,
  role text not null default 'admin' check (role in ('admin')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create trigger profiles_set_updated_at
before update on public.profiles
for each row execute function public.set_updated_at();

create or replace function public.is_admin()
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1
    from public.profiles p
    where p.id = auth.uid()
      and p.role = 'admin'
  );
$$;

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
    'admin'
  )
  on conflict (id) do nothing;
  return new;
end;
$$;

create trigger on_auth_user_created
after insert on auth.users
for each row execute function public.handle_new_user();

-- ---------------------------------------------------------------------------
-- Site settings (brand / theme)
-- ---------------------------------------------------------------------------
create table public.site_settings (
  id uuid primary key default gen_random_uuid(),
  brand_name text not null default 'AURELIA',
  tagline text,
  logo_url text,
  primary_color text not null default '#c4a574',
  accent_color text not null default '#0c0e0d',
  background_color text not null default '#f5f0e8',
  contact_email text,
  contact_phone text,
  socials jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

create trigger site_settings_set_updated_at
before update on public.site_settings
for each row execute function public.set_updated_at();

-- ---------------------------------------------------------------------------
-- Listings
-- ---------------------------------------------------------------------------
create table public.listings (
  id uuid primary key default gen_random_uuid(),
  slug text not null unique,
  title text not null,
  subtitle text,
  summary text,
  status text not null default 'draft'
    check (status in ('draft', 'preview', 'published')),
  experience_type text not null default 'photo'
    check (experience_type in ('immersive', 'photo')),
  cover_image_url text,
  price_label text,
  location text,
  bedrooms numeric(4,1),
  bathrooms numeric(4,1),
  area_sqft integer,
  sort_order integer not null default 0,
  published_at timestamptz,
  created_by uuid references public.profiles (id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index listings_status_idx on public.listings (status);
create index listings_sort_idx on public.listings (sort_order, created_at desc);

create trigger listings_set_updated_at
before update on public.listings
for each row execute function public.set_updated_at();

-- ---------------------------------------------------------------------------
-- Listing media (images, video source, frame sequences)
-- ---------------------------------------------------------------------------
create table public.listing_media (
  id uuid primary key default gen_random_uuid(),
  listing_id uuid not null references public.listings (id) on delete cascade,
  kind text not null
    check (kind in ('cover', 'gallery', 'video', 'frame_sequence')),
  storage_path text,
  public_url text,
  label text,
  aspect text check (aspect in ('landscape', 'portrait', 'square')),
  frame_count integer,
  frame_pattern text,
  sort_order integer not null default 0,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index listing_media_listing_idx on public.listing_media (listing_id, sort_order);

-- ---------------------------------------------------------------------------
-- Page sections (controlled builder presets)
-- ---------------------------------------------------------------------------
create table public.page_sections (
  id uuid primary key default gen_random_uuid(),
  listing_id uuid not null references public.listings (id) on delete cascade,
  preset text not null
    check (preset in ('hero', 'tiles', 'text', 'gallery', 'specs', 'cta', 'custom')),
  title text,
  body text,
  layout text not null default 'default'
    check (layout in ('default', 'tiles', 'split', 'full')),
  style jsonb not null default '{}'::jsonb,
  content jsonb not null default '{}'::jsonb,
  sort_order integer not null default 0,
  is_visible boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index page_sections_listing_idx on public.page_sections (listing_id, sort_order);

create trigger page_sections_set_updated_at
before update on public.page_sections
for each row execute function public.set_updated_at();

-- ---------------------------------------------------------------------------
-- Enquiries
-- ---------------------------------------------------------------------------
create table public.enquiries (
  id uuid primary key default gen_random_uuid(),
  listing_id uuid references public.listings (id) on delete set null,
  name text not null,
  email text not null,
  phone text,
  message text,
  status text not null default 'new'
    check (status in ('new', 'read', 'closed')),
  created_at timestamptz not null default now()
);

create index enquiries_status_idx on public.enquiries (status, created_at desc);

-- ---------------------------------------------------------------------------
-- Row Level Security
-- ---------------------------------------------------------------------------
alter table public.profiles enable row level security;
alter table public.site_settings enable row level security;
alter table public.listings enable row level security;
alter table public.listing_media enable row level security;
alter table public.page_sections enable row level security;
alter table public.enquiries enable row level security;

-- Profiles
create policy "Admins can read all profiles"
  on public.profiles for select
  using (public.is_admin());

create policy "Users can read own profile"
  on public.profiles for select
  using (auth.uid() = id);

create policy "Admins can update profiles"
  on public.profiles for update
  using (public.is_admin());

-- Site settings: public read, admin write
create policy "Public can read site settings"
  on public.site_settings for select
  using (true);

create policy "Admins manage site settings"
  on public.site_settings for all
  using (public.is_admin())
  with check (public.is_admin());

-- Listings: public sees published; admin all
create policy "Public can read published listings"
  on public.listings for select
  using (status = 'published' or public.is_admin());

create policy "Admins manage listings"
  on public.listings for all
  using (public.is_admin())
  with check (public.is_admin());

-- Media follows listing visibility
create policy "Public can read media for published listings"
  on public.listing_media for select
  using (
    public.is_admin()
    or exists (
      select 1 from public.listings l
      where l.id = listing_id and l.status = 'published'
    )
  );

create policy "Admins manage listing media"
  on public.listing_media for all
  using (public.is_admin())
  with check (public.is_admin());

-- Sections
create policy "Public can read visible sections of published listings"
  on public.page_sections for select
  using (
    public.is_admin()
    or (
      is_visible = true
      and exists (
        select 1 from public.listings l
        where l.id = listing_id and l.status = 'published'
      )
    )
  );

create policy "Admins manage page sections"
  on public.page_sections for all
  using (public.is_admin())
  with check (public.is_admin());

-- Enquiries: anyone can submit; admin manages
create policy "Anyone can create enquiries"
  on public.enquiries for insert
  with check (true);

create policy "Admins manage enquiries"
  on public.enquiries for all
  using (public.is_admin())
  with check (public.is_admin());

-- ---------------------------------------------------------------------------
-- Storage buckets
-- ---------------------------------------------------------------------------
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values
  (
    'listing-images',
    'listing-images',
    true,
    20971520,
    array['image/jpeg', 'image/png', 'image/webp', 'image/avif']
  ),
  (
    'listing-videos',
    'listing-videos',
    false,
    524288000,
    array['video/mp4', 'video/quicktime', 'video/webm']
  ),
  (
    'listing-frames',
    'listing-frames',
    true,
    5242880,
    array['image/jpeg', 'image/png', 'image/webp']
  )
on conflict (id) do nothing;

-- Public read for public buckets
create policy "Public read listing images"
  on storage.objects for select
  using (bucket_id = 'listing-images');

create policy "Public read listing frames"
  on storage.objects for select
  using (bucket_id = 'listing-frames');

create policy "Admins read listing videos"
  on storage.objects for select
  using (bucket_id = 'listing-videos' and public.is_admin());

create policy "Admins upload listing media"
  on storage.objects for insert
  with check (
    public.is_admin()
    and bucket_id in ('listing-images', 'listing-videos', 'listing-frames')
  );

create policy "Admins update listing media"
  on storage.objects for update
  using (
    public.is_admin()
    and bucket_id in ('listing-images', 'listing-videos', 'listing-frames')
  );

create policy "Admins delete listing media"
  on storage.objects for delete
  using (
    public.is_admin()
    and bucket_id in ('listing-images', 'listing-videos', 'listing-frames')
  );

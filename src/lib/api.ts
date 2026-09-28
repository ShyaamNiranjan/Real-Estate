import { supabase } from './supabase'
import type { HomeSectionRow, ListingRow, SiteSettingsRow } from '../types/database'
import type { ListingWithRelations } from '../types/content'

export type ListingCard = Pick<
  ListingRow,
  | 'id'
  | 'slug'
  | 'title'
  | 'subtitle'
  | 'status'
  | 'experience_type'
  | 'cover_image_url'
  | 'price_label'
  | 'location'
  | 'bedrooms'
  | 'bathrooms'
  | 'area_sqft'
>

const CARD_COLUMNS =
  'id, slug, title, subtitle, status, experience_type, cover_image_url, price_label, location, bedrooms, bathrooms, area_sqft'

export async function fetchSiteSettings(): Promise<SiteSettingsRow | null> {
  const { data, error } = await supabase.from('site_settings').select('*').limit(1).maybeSingle()
  if (error) throw error
  return data
}

/**
 * Last successful home payloads. Returning to `/` renders these immediately (then refreshes),
 * so the page has its full height and scroll restoration lands where the visitor left.
 */
export const homeCache: { listings: ListingCard[] | null; sections: HomeSectionRow[] | null } = {
  listings: null,
  sections: null,
}

export async function fetchPublishedListings(): Promise<ListingCard[]> {
  const { data, error } = await supabase
    .from('listings')
    .select(CARD_COLUMNS)
    .eq('status', 'published')
    .order('sort_order', { ascending: true })
    .order('created_at', { ascending: false })
  if (error) throw error
  homeCache.listings = data ?? []
  return homeCache.listings
}

/** Visible home sections in order. Admins can read hidden rows too, so filter explicitly. */
export async function fetchHomeSections(): Promise<HomeSectionRow[]> {
  const { data, error } = await supabase
    .from('home_sections')
    .select('*')
    .eq('is_visible', true)
    .order('sort_order', { ascending: true })
  if (error) throw error
  homeCache.sections = data ?? []
  return homeCache.sections
}

/** RLS returns drafts/previews only to signed-in admins, which is what powers preview. */
export async function fetchListingBySlug(slug: string): Promise<ListingWithRelations | null> {
  const { data, error } = await supabase
    .from('listings')
    .select('*, listing_media(*), page_sections(*)')
    .eq('slug', slug)
    .maybeSingle()
  if (error) throw error
  if (!data) return null
  const listing = data as unknown as ListingWithRelations
  listing.listing_media = [...(listing.listing_media ?? [])].sort((a, b) => a.sort_order - b.sort_order)
  listing.page_sections = [...(listing.page_sections ?? [])]
    .filter((s) => s.is_visible)
    .sort((a, b) => a.sort_order - b.sort_order)
  return listing
}

export async function submitEnquiry(input: {
  listing_id: string | null
  name: string
  email: string
  phone?: string
  message?: string
}) {
  const { error } = await supabase.from('enquiries').insert({
    listing_id: input.listing_id,
    name: input.name.trim(),
    email: input.email.trim(),
    phone: input.phone?.trim() || null,
    message: input.message?.trim() || null,
    status: 'new',
  })
  if (error) throw error
}

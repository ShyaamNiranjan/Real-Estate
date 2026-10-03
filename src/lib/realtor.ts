import { slugify } from './format'
import { useSite } from './site'

/** Top-level words a realtor slug can never take, because YE's own pages live there. */
export const RESERVED_SLUGS = new Set([
  'about',
  'admin',
  'api',
  'assets',
  'blog',
  'features',
  'help',
  'legal',
  'listing',
  'login',
  'media',
  'pricing',
  'privacy',
  'signup',
  'studio',
  'terms',
])

/** Words a property slug can never take inside a realtor's site. */
export const RESERVED_PROPERTY_SLUGS = new Set(['about', 'contact', 'journal', 'neighbourhoods', 'properties'])

export function realtorSlug(brand: string) {
  return slugify(brand) || 'realtor'
}

export function useRealtor() {
  const { settings, ready } = useSite()
  const slug = realtorSlug(settings.brand_name)
  const base = `/${slug}`
  return {
    slug,
    base,
    ready,
    properties: `${base}/properties`,
    listing: (listingSlug: string) => `${base}/${listingSlug}`,
  }
}

/** Maps legacy single-site links (`/`, `/#id`, `/listing/x`) stored in content onto the realtor's paths. */
export function realtorHref(href: string, base: string) {
  if (href === '/') return base
  if (href.startsWith('/#')) return `${base}${href.slice(1)}`
  if (href.startsWith('/listing/')) return `${base}/${href.slice('/listing/'.length)}`
  return href
}

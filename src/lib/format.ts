import type { ListingRow } from '../types/database'

export function formatNumber(value: number | null | undefined) {
  if (value === null || value === undefined) return null
  return new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 }).format(value)
}

export function listingFacts(listing: Pick<ListingRow, 'bedrooms' | 'bathrooms' | 'area_sqft'>) {
  const facts: string[] = []
  if (listing.bedrooms) facts.push(`${formatNumber(listing.bedrooms)} bed`)
  if (listing.bathrooms) facts.push(`${formatNumber(listing.bathrooms)} bath`)
  if (listing.area_sqft) facts.push(`${formatNumber(listing.area_sqft)} sq ft`)
  return facts
}

export function slugify(input: string) {
  return input
    .toLowerCase()
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 80)
}

export function formatDate(iso: string | null | undefined) {
  if (!iso) return '—'
  return new Intl.DateTimeFormat('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  }).format(new Date(iso))
}

export function formatDateTime(iso: string | null | undefined) {
  if (!iso) return '—'
  return new Intl.DateTimeFormat('en-GB', {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(iso))
}

/** Expands a frame pattern like `frame-{###}.jpg` for a 1-based frame number. */
export function expandFramePattern(pattern: string, frameNumber: number) {
  return pattern.replace(/\{(#+)\}/, (_, hashes: string) =>
    String(frameNumber).padStart(hashes.length, '0'),
  )
}

export function joinUrl(base: string, file: string) {
  return `${base.replace(/\/+$/, '')}/${file.replace(/^\/+/, '')}`
}

/** Shapes and labels for the analytics summary served by /api/a/summary. */

export type Totals = { views: number; visitors: number; enquiries: number; enquiryRate: number; avgTimeMs: number }
export type Count = { name: string; count: number }
export type EventKey = 'gallery_open' | 'floorplan_view' | 'enquiry_click' | 'enquiry' | 'phone_click' | 'whatsapp_click' | 'email_click'

export type Summary = {
  range: { from: number; to: number }
  totals: Totals
  previous: Totals
  days: { day: string; views: number; visitors: number; enquiries: number }[]
  sources: Count[]
  referrers: Count[]
  devices: Count[]
  countries: Count[]
  cities: Count[]
  walkthrough: {
    views: number
    started: number
    finished: number
    startRate: number
    finishRate: number
    avgDepth: number
    curve: number[]
    marks: { at: number; reach: number }[]
  }
  events: Record<EventKey, { count: number; visits: number }>
  listings: (Totals & { id: string; finishRate: number; avgDepth: number; hasWalk: boolean })[]
  siteViews: number
  sample: boolean
}

export async function fetchSummary(params: { realtor: string; days: number; listing?: string | null; marks?: number[] }): Promise<Summary> {
  const q = new URLSearchParams({ realtor: params.realtor, days: String(params.days) })
  if (params.listing) q.set('listing', params.listing)
  if (params.marks?.length) q.set('marks', params.marks.map((m) => m.toFixed(4)).join(','))
  const res = await fetch(`/api/a/summary?${q}`)
  if (!res.ok) throw new Error('Analytics are unavailable. Is the dev server running?')
  return (await res.json()) as Summary
}

export const SOURCE_LABEL: Record<string, string> = {
  instagram: 'Instagram',
  whatsapp: 'WhatsApp',
  facebook: 'Facebook',
  google: 'Google',
  bing: 'Bing',
  duckduckgo: 'DuckDuckGo',
  direct: 'Direct & messaging apps',
  qr: 'QR code / print',
  email: 'Email',
  linkedin: 'LinkedIn',
  x: 'X',
  tiktok: 'TikTok',
  youtube: 'YouTube',
  other: 'Other websites',
}

export const sourceLabel = (key: string) => SOURCE_LABEL[key] ?? key.charAt(0).toUpperCase() + key.slice(1)

export const EVENT_LABEL: Record<Exclude<EventKey, 'enquiry'>, string> = {
  gallery_open: 'Opened the gallery',
  floorplan_view: 'Viewed the floor plan',
  enquiry_click: 'Clicked Enquire',
  whatsapp_click: 'Tapped WhatsApp',
  phone_click: 'Tapped to call',
  email_click: 'Tapped email',
}

export const DEVICE_LABEL: Record<string, string> = { phone: 'Phone', tablet: 'Tablet', desktop: 'Desktop' }

const regionNames = typeof Intl !== 'undefined' && 'DisplayNames' in Intl ? new Intl.DisplayNames(['en'], { type: 'region' }) : null

export function countryName(code: string) {
  try {
    return regionNames?.of(code) ?? code
  } catch {
    return code
  }
}

export const fmtInt = (n: number) => Math.round(n).toLocaleString('en-US')
export const fmtPct = (n: number, digits = 0) => `${(n * 100).toFixed(digits)}%`

export function fmtDuration(ms: number) {
  const s = Math.round(ms / 1000)
  if (s < 60) return `${s}s`
  return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, '0')}s`
}

/** Change vs the previous period of equal length; null when there is nothing to compare against. */
export function delta(now: number, before: number) {
  if (!before) return null
  return (now - before) / before
}

/** Funnel rows: room by room when the listing's walkthrough has markers, otherwise quarter steps. */
export function walkStages(w: Summary['walkthrough'], beats: { label?: string; text: string }[]) {
  if (w.marks.length && beats.length)
    return [
      { label: 'Started the walkthrough', reach: 1 },
      ...w.marks.map((m, i) => ({ label: beats[i]?.label || beats[i]?.text.slice(0, 32) || `Point ${i + 1}`, reach: m.reach })),
      { label: 'Reached the end', reach: w.finishRate },
    ]
  return [0, 5, 10, 15, 20].map((i) => ({
    label: i === 0 ? 'Started' : i === 20 ? 'Reached the end' : `${i * 5}% of the way`,
    reach: i === 20 ? w.finishRate : w.curve[i],
  }))
}

/** "September 9, 2026" from a summary day key, without shifting it through the local time zone. */
export function fmtDay(day: string) {
  return new Date(`${day}T12:00:00Z`).toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric', timeZone: 'UTC' })
}

export const SHARE_CHANNELS = [
  { key: 'instagram', label: 'Instagram' },
  { key: 'whatsapp', label: 'WhatsApp' },
  { key: 'facebook', label: 'Facebook' },
  { key: 'linkedin', label: 'LinkedIn' },
  { key: 'email', label: 'Email' },
  { key: 'qr', label: 'QR code / print' },
] as const

export function shareUrl(path: string, channel: string) {
  return `${window.location.origin}${path}?src=${channel}`
}

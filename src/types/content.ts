import type { Json, ListingMediaRow, ListingRow, PageSectionRow } from './database'

export type SectionTone = 'light' | 'stone' | 'dark'

export type SectionStyle = {
  tone?: SectionTone
  background?: string
  text?: string
  accent?: string
}

export type TileItem = { title?: string; body?: string; image?: string }
export type SpecItem = { label?: string; value?: string }

export type SectionContent = {
  eyebrow?: string
  image?: string
  caption?: string
  items?: (TileItem & SpecItem)[]
  images?: string[]
  ctaLabel?: string
  ctaAction?: 'enquiry' | 'link'
  href?: string
}

export type ScrollBeat = {
  id: string
  side: 'left' | 'right'
  at: number
  /** Where the caption leaves (0–1). Unset = stays until the next beat starts. */
  until?: number | null
  label: string
  text: string
}

export const BEATS_END = 0.95

/** Beats must be sorted by `at`. */
export function beatEnd(beats: ScrollBeat[], i: number): number {
  const b = beats[i]
  const auto = beats[i + 1]?.at ?? BEATS_END
  return typeof b.until === 'number' && b.until > b.at ? Math.min(BEATS_END, b.until) : auto
}

export type ExperienceHero = {
  brand?: string
  line?: string
  support?: string
  scrollHint?: string
}

/** How a landscape-only walkthrough is presented on a portrait phone. */
export type MobileMode = 'rotate' | 'fit' | 'fill'

export const MOBILE_MODES: readonly MobileMode[] = ['rotate', 'fit', 'fill']

export function asMobileMode(value: unknown): MobileMode {
  return MOBILE_MODES.includes(value as MobileMode) ? (value as MobileMode) : 'rotate'
}

export type ExperienceConfig = {
  hero?: ExperienceHero
  beats?: ScrollBeat[]
  mobile_mode?: MobileMode
}

export type FrameSequence = {
  baseUrl: string
  frameCount: number
  pattern: string
  pxPerFrame?: number
}

export type ListingWithRelations = ListingRow & {
  listing_media: ListingMediaRow[]
  page_sections: PageSectionRow[]
}

function isObject(value: Json | undefined): value is { [key: string]: Json | undefined } {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/** jsonb columns arrive untyped; these narrow them to the shapes the UI expects. */
export function asObject<T extends object>(value: Json | undefined): T {
  return (isObject(value) ? value : {}) as T
}

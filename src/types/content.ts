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
  label: string
  text: string
}

export type ExperienceHero = {
  brand?: string
  line?: string
  support?: string
  scrollHint?: string
}

export type ExperienceConfig = {
  hero?: ExperienceHero
  beats?: ScrollBeat[]
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

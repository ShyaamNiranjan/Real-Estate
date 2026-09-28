import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { fetchSiteSettings } from './api'
import { isSupabaseConfigured } from './supabase'
import { asObject, SOCIAL_KEYS, type Socials } from '../types/content'
import type { SiteSettingsRow } from '../types/database'

export type SiteSettings = Omit<SiteSettingsRow, 'id' | 'updated_at' | 'socials'> & { id: string | null; socials: Socials }

export const DEFAULT_BRAND = 'YNIIDI Estates'

export const DEFAULT_SETTINGS: SiteSettings = {
  id: null,
  brand_name: DEFAULT_BRAND,
  tagline: 'Private residences in Chennai',
  logo_url: null,
  primary_color: '#c4a574',
  accent_color: '#0c0e0d',
  background_color: '#f5f0e8',
  contact_email: 'hello@yniidi.com',
  contact_phone: null,
  socials: {},
  hero_headline: 'Homes you can walk before you visit',
  hero_body:
    'A private collection of modern residences across Chennai, each presented as a place to move through, not a page to skim.',
  hero_image_url: '/media/sequence/frame-001.jpg',
  hero_cta_label: 'View the collection',
  footer_note: 'Viewings by appointment, Monday to Saturday.',
  address: null,
  rera_number: null,
  demo_note: null,
}

/** "YNIIDI Estates" → wordmark "YNIIDI" with the tracked sub-label "Estates". */
export function brandParts(brand: string) {
  const [name, ...rest] = brand.trim().split(/\s+/)
  return { name: name || DEFAULT_BRAND, sub: rest.join(' ') }
}

function cleanSocials(value: SiteSettingsRow['socials']): Socials {
  const raw = asObject<Record<string, unknown>>(value)
  const out: Socials = {}
  for (const key of SOCIAL_KEYS) {
    const url = raw[key]
    if (typeof url === 'string' && /^https?:\/\//i.test(url.trim())) out[key] = url.trim()
  }
  return out
}

type SiteContextValue = {
  settings: SiteSettings
  ready: boolean
  reload: () => Promise<void>
}

const SiteContext = createContext<SiteContextValue>({
  settings: DEFAULT_SETTINGS,
  ready: false,
  reload: async () => {},
})

const HEX = /^#[0-9a-f]{6}$/i

function applyTheme(s: SiteSettings) {
  const root = document.documentElement.style
  if (HEX.test(s.primary_color)) root.setProperty('--gold', s.primary_color)
  if (HEX.test(s.accent_color)) root.setProperty('--charcoal', s.accent_color)
  if (HEX.test(s.background_color)) root.setProperty('--paper', s.background_color)
}

function merge(row: SiteSettingsRow | null): SiteSettings {
  if (!row) return DEFAULT_SETTINGS
  const merged = { ...DEFAULT_SETTINGS }
  for (const key of Object.keys(DEFAULT_SETTINGS) as (keyof SiteSettings)[]) {
    if (key === 'socials') continue
    const value = row[key as keyof SiteSettingsRow]
    if (value !== null && value !== undefined && value !== '') {
      ;(merged as Record<string, unknown>)[key] = value
    }
  }
  merged.socials = cleanSocials(row.socials)
  return merged
}

export function SiteProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<SiteSettings>(DEFAULT_SETTINGS)
  const [ready, setReady] = useState(false)

  const reload = useCallback(async () => {
    if (!isSupabaseConfigured) {
      setReady(true)
      return
    }
    try {
      const next = merge(await fetchSiteSettings())
      setSettings(next)
      applyTheme(next)
    } catch (err) {
      console.error('Failed to load site settings', err)
    } finally {
      setReady(true)
    }
  }, [])

  useEffect(() => {
    void reload()
  }, [reload])

  const value = useMemo(() => ({ settings, ready, reload }), [settings, ready, reload])
  return <SiteContext.Provider value={value}>{children}</SiteContext.Provider>
}

export function useSite() {
  return useContext(SiteContext)
}

export function useDocumentTitle(title: string | null | undefined) {
  const { settings } = useSite()
  useEffect(() => {
    const brand = settings.brand_name
    document.title = title ? `${title} · ${brand}` : `${brand} · ${settings.tagline ?? 'Private residences in Chennai'}`
  }, [title, settings.brand_name, settings.tagline])
}

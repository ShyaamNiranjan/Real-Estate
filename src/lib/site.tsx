import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { fetchSiteSettings } from './api'
import { isSupabaseConfigured } from './supabase'
import type { SiteSettingsRow } from '../types/database'

export type SiteSettings = Omit<SiteSettingsRow, 'id' | 'updated_at' | 'socials'> & { id: string | null }

export const DEFAULT_SETTINGS: SiteSettings = {
  id: null,
  brand_name: 'AURELIA',
  tagline: 'Private residences by YNIIDI',
  logo_url: null,
  primary_color: '#c4a574',
  accent_color: '#0c0e0d',
  background_color: '#f5f0e8',
  contact_email: 'hello@yniidi.com',
  contact_phone: null,
  hero_headline: 'Homes you can walk before you visit',
  hero_body:
    'A private collection of modern residences, each presented as a place to move through, not a page to skim.',
  hero_image_url: '/media/sequence/frame-001.jpg',
  hero_cta_label: 'View the collection',
  footer_note: 'AURELIA by YNIIDI. Viewings by appointment.',
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
    const value = row[key as keyof SiteSettingsRow]
    if (value !== null && value !== undefined && value !== '') {
      ;(merged as Record<string, unknown>)[key] = value
    }
  }
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
    document.title = title ? `${title} · ${brand}` : `${brand} · ${settings.tagline ?? 'Private residences'}`
  }, [title, settings.brand_name, settings.tagline])
}

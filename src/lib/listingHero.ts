import { useEffect, useState } from 'react'

/** Prototype-only: the hero banner lives in this browser until the real schema exists. */
export type HeroSettings = {
  enabled: boolean
  /** Uploaded banner as a data URL; null falls back to the listing's cover photo. */
  image: string | null
  showFacts: boolean
  showPrice: boolean
}

const MAX_EDGE = 2400
const key = (listingId: string) => `ye:hero:${listingId}`
const EVENT = 'ye:hero'

export const HERO_DEFAULTS: HeroSettings = { enabled: true, image: null, showFacts: true, showPrice: true }

export function loadHero(listingId: string): HeroSettings {
  try {
    const raw = localStorage.getItem(key(listingId))
    if (!raw) return HERO_DEFAULTS
    const saved = JSON.parse(raw) as Partial<HeroSettings>
    return {
      enabled: saved.enabled !== false,
      image: typeof saved.image === 'string' ? saved.image : null,
      showFacts: saved.showFacts !== false,
      showPrice: saved.showPrice !== false,
    }
  } catch {
    return HERO_DEFAULTS
  }
}

/** Throws when the browser's storage is full. */
export function saveHero(listingId: string, settings: HeroSettings) {
  localStorage.setItem(key(listingId), JSON.stringify(settings))
  window.dispatchEvent(new CustomEvent(EVENT, { detail: listingId }))
}

export function useListingHero(listingId: string | undefined) {
  const [hero, setHero] = useState(() => (listingId ? loadHero(listingId) : HERO_DEFAULTS))
  useEffect(() => {
    if (!listingId) return
    const sync = () => setHero(loadHero(listingId))
    sync()
    window.addEventListener('storage', sync)
    window.addEventListener(EVENT, sync)
    return () => {
      window.removeEventListener('storage', sync)
      window.removeEventListener(EVENT, sync)
    }
  }, [listingId])
  return hero
}

/**
 * Until the realtor uploads one: a photo that is not the walkthrough's opening frame (so the cut
 * visibly lands somewhere new), else the walkthrough's closing frame, else the cover.
 */
export function fallbackHeroImage(opts: { cover: string | null; gallery: string[]; firstFrame: string | null; lastFrame: string | null }) {
  const distinct = [opts.cover, ...opts.gallery].find((src) => src && src !== opts.firstFrame)
  return { src: distinct ?? opts.lastFrame ?? opts.cover, label: distinct ? 'Cover photo' : opts.lastFrame ? 'Walkthrough closing frame' : 'Cover photo' }
}

/** Downscales to a 2400px long edge: sharp on a large screen, small enough for local storage. */
export async function heroImageFromFile(file: File): Promise<string> {
  const bitmap = await createImageBitmap(file)
  const scale = Math.min(1, MAX_EDGE / Math.max(bitmap.width, bitmap.height))
  const canvas = document.createElement('canvas')
  canvas.width = Math.round(bitmap.width * scale)
  canvas.height = Math.round(bitmap.height * scale)
  const ctx = canvas.getContext('2d')!
  ctx.imageSmoothingQuality = 'high'
  ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height)
  bitmap.close()
  return canvas.toDataURL('image/webp', 0.86)
}

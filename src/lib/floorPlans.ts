import { useEffect, useState } from 'react'

/** Prototype-only: floor plans live in this browser until the real schema exists. */
export type FloorPlan = { id: string; label: string; src: string; width: number; height: number }

const MAX_EDGE = 2000
const key = (listingId: string) => `ye:floor-plans:${listingId}`
const EVENT = 'ye:floor-plans'

export function loadFloorPlans(listingId: string): FloorPlan[] {
  try {
    const raw = localStorage.getItem(key(listingId))
    const list = raw ? (JSON.parse(raw) as FloorPlan[]) : []
    return Array.isArray(list) ? list.filter((p) => p && typeof p.src === 'string') : []
  } catch {
    return []
  }
}

/** Throws when the browser's storage is full. */
export function saveFloorPlans(listingId: string, plans: FloorPlan[]) {
  if (plans.length) localStorage.setItem(key(listingId), JSON.stringify(plans))
  else localStorage.removeItem(key(listingId))
  window.dispatchEvent(new CustomEvent(EVENT, { detail: listingId }))
}

export function useFloorPlans(listingId: string) {
  const [plans, setPlans] = useState(() => loadFloorPlans(listingId))
  useEffect(() => {
    const sync = () => setPlans(loadFloorPlans(listingId))
    sync()
    window.addEventListener('storage', sync)
    window.addEventListener(EVENT, sync)
    return () => {
      window.removeEventListener('storage', sync)
      window.removeEventListener(EVENT, sync)
    }
  }, [listingId])
  return plans
}

/** Downscales to a crisp 2000px long edge on white, so line drawings stay sharp but small. */
export async function floorPlanFromFile(file: File, label: string): Promise<FloorPlan> {
  const bitmap = await createImageBitmap(file)
  const scale = Math.min(1, MAX_EDGE / Math.max(bitmap.width, bitmap.height))
  const width = Math.round(bitmap.width * scale)
  const height = Math.round(bitmap.height * scale)
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const ctx = canvas.getContext('2d')!
  ctx.fillStyle = '#fff'
  ctx.fillRect(0, 0, width, height)
  ctx.imageSmoothingQuality = 'high'
  ctx.drawImage(bitmap, 0, 0, width, height)
  bitmap.close()
  return { id: crypto.randomUUID(), label, src: canvas.toDataURL('image/webp', 0.88), width, height }
}

const LEVEL_NAMES = ['Ground floor', 'First floor', 'Second floor', 'Third floor', 'Fourth floor']

export function suggestedLabel(index: number) {
  return LEVEL_NAMES[index] ?? `Level ${index + 1}`
}

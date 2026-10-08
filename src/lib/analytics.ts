import { useEffect } from 'react'
import { useAuth } from './auth'

/**
 * Cookieless, first-party listing analytics. Nothing is stored on the visitor's device; the
 * server derives a daily-rotating visitor hash, so no consent banner is needed.
 */

const ENDPOINT = '/api/a/collect'
/** StrictMode and fast redirects mount pages twice; only a page that stays this long counts. */
const SETTLE_MS = 300
const FINISHED_AT = 0.98
/** Browsers drop the exit beacon on some cross-page navigations, so time and depth are also reported periodically. */
const HEARTBEAT_MS = 15_000
export const TEST_FLAG = 'ye:analytics-test'

export type TrackedEvent = 'gallery_open' | 'floorplan_view' | 'enquiry_click' | 'enquiry' | 'phone_click' | 'whatsapp_click' | 'email_click'

type Visit = {
  id: string
  ready: Promise<void>
  depth: number
  finishedSent: boolean
  activeMs: number
  visibleSince: number | null
  once: Set<TrackedEvent>
}

let current: Visit | null = null
let entryUsed = false
let listening = false

function post(payload: Record<string, unknown>, beacon = false) {
  const body = JSON.stringify(payload)
  if (beacon && navigator.sendBeacon?.(ENDPOINT, new Blob([body], { type: 'text/plain' }))) return Promise.resolve()
  return fetch(ENDPOINT, { method: 'POST', body, keepalive: true, headers: { 'content-type': 'text/plain' } }).then(
    () => undefined,
    () => undefined,
  )
}

function device() {
  const coarse = window.matchMedia('(pointer: coarse)').matches
  const short = Math.min(window.screen.width, window.screen.height)
  return coarse ? (short < 600 ? 'phone' : 'tablet') : 'desktop'
}

function allowed() {
  if (!navigator.webdriver) return true
  try {
    return localStorage.getItem(TEST_FLAG) === '1'
  } catch {
    return false
  }
}

function settleActive(v: Visit) {
  if (v.visibleSince !== null) {
    v.activeMs += performance.now() - v.visibleSince
    v.visibleSince = document.visibilityState === 'visible' ? performance.now() : null
  }
}

function sendLeave(v: Visit, beacon: boolean) {
  settleActive(v)
  const payload = { k: 'lv', id: v.id, dep: v.depth, ms: Math.round(v.activeMs) }
  if (beacon) post(payload, true)
  else void v.ready.then(() => post(payload))
}

function listen() {
  if (listening) return
  listening = true
  document.addEventListener('visibilitychange', () => {
    const v = current
    if (!v) return
    if (document.visibilityState === 'hidden') sendLeave(v, true)
    else v.visibleSince = performance.now()
  })
  window.addEventListener('pagehide', () => current && sendLeave(current, true))
  document.addEventListener(
    'click',
    (e) => {
      const a = (e.target as Element | null)?.closest?.('a[href]')
      const href = a?.getAttribute('href') ?? ''
      if (href.startsWith('tel:')) track('phone_click')
      else if (/^https?:\/\/(wa\.me|api\.whatsapp\.com|web\.whatsapp\.com)\//i.test(href) || href.startsWith('whatsapp:')) track('whatsapp_click')
      else if (href.startsWith('mailto:')) track('email_click')
    },
    { capture: true },
  )
}

type PageviewInput = { realtor: string; listingId?: string | null; walk?: boolean }

function start({ realtor, listingId = null, walk = false }: PageviewInput) {
  listen()
  const params = new URLSearchParams(window.location.search)
  const entry = !entryUsed
  entryUsed = true
  const id = crypto.randomUUID()
  const ready = post({
    k: 'pv',
    id,
    r: realtor,
    l: listingId,
    p: window.location.pathname,
    d: device(),
    tz: Intl.DateTimeFormat().resolvedOptions().timeZone ?? null,
    ref: entry ? document.referrer : '',
    tag: entry ? params.get('src') ?? params.get('utm_source') : null,
    entry,
    walk,
  })
  const visit: Visit = {
    id,
    ready,
    depth: 0,
    finishedSent: false,
    activeMs: 0,
    visibleSince: document.visibilityState === 'visible' ? performance.now() : null,
    once: new Set(),
  }
  current = visit
  const heartbeat = window.setInterval(() => {
    if (document.visibilityState === 'visible') sendLeave(visit, false)
  }, HEARTBEAT_MS)
  return () => {
    window.clearInterval(heartbeat)
    sendLeave(visit, false)
    if (current === visit) current = null
  }
}

/** Records one view of the current page. Skips signed-in agents, editor previews and automated browsers. */
export function usePageview(input: PageviewInput | null) {
  const { session, loading } = useAuth()
  const key = input ? `${input.realtor}|${input.listingId ?? ''}|${input.walk ? 1 : 0}|${window.location.pathname}` : null
  const signedIn = Boolean(session)
  useEffect(() => {
    if (!key || !input || loading || signedIn || !allowed()) return
    if (new URLSearchParams(window.location.search).has('draft')) return
    let stop: (() => void) | null = null
    const timer = window.setTimeout(() => {
      stop = start(input)
    }, SETTLE_MS)
    return () => {
      window.clearTimeout(timer)
      stop?.()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `key` captures everything in `input`
  }, [key, loading, signedIn])
}

/** Furthest point (0–1) the visitor has scrolled the walkthrough to. */
export function reportDepth(progress: number) {
  const v = current
  if (!v || progress <= v.depth) return
  v.depth = progress
  if (progress >= FINISHED_AT && !v.finishedSent) {
    v.finishedSent = true
    sendLeave(v, false)
  }
}

export function track(event: TrackedEvent, { oncePerView = false } = {}) {
  const v = current
  if (!v) return
  if (oncePerView) {
    if (v.once.has(event)) return
    v.once.add(event)
  }
  void v.ready.then(() => post({ k: 'ev', id: v.id, e: event }))
}

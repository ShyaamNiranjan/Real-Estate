import { createHash, randomBytes, randomUUID } from 'node:crypto'
import { appendFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import type { IncomingMessage, ServerResponse } from 'node:http'
import { resolve } from 'node:path'
import type { Plugin } from 'vite'

/**
 * Prototype analytics store: cookieless events appended to .data/analytics.jsonl.
 * The production build swaps this file for a database table behind the same endpoints.
 */

const DIR = resolve(process.cwd(), '.data')
const FILE = resolve(DIR, 'analytics.jsonl')
const SALT_FILE = resolve(DIR, 'salt.json')
const MAX_BODY = 4096
/** Depth (0–1) a visitor must pass to count as having started, and to count as finished. */
export const STARTED_AT = 0.03
export const FINISHED_AT = 0.98
const MAX_ACTIVE_MS = 30 * 60_000
const BOT_UA = /bot|crawl|spider|slurp|headless|lighthouse|pagespeed|preview|facebookexternalhit|embedly|monitor|curl|wget|python|node-fetch/i

export type Device = 'phone' | 'tablet' | 'desktop'
export const EVENT_TYPES = ['gallery_open', 'floorplan_view', 'enquiry_click', 'enquiry', 'phone_click', 'whatsapp_click', 'email_click'] as const
type EventType = (typeof EVENT_TYPES)[number]

type PageviewRow = {
  k: 'pv'
  id: string
  ts: number
  r: string
  l: string | null
  p: string
  v: string
  d: Device
  c: string | null
  ci: string | null
  src: string
  ref: string | null
  entry: boolean
  walk: boolean
  s?: true
}
type LeaveRow = { k: 'lv'; id: string; ts: number; dep: number; ms: number; s?: true }
type EventRow = { k: 'ev'; id: string; ts: number; e: EventType; s?: true }
type Row = PageviewRow | LeaveRow | EventRow

type Visit = PageviewRow & { dep: number; ms: number; events: EventType[] }

const visits = new Map<string, Visit>()
let loaded = false

function load() {
  if (loaded) return
  loaded = true
  if (!existsSync(FILE)) return
  for (const line of readFileSync(FILE, 'utf8').split('\n')) {
    if (!line.trim()) continue
    try {
      apply(JSON.parse(line) as Row)
    } catch {
      /* skip a torn line */
    }
  }
}

function apply(row: Row) {
  if (row.k === 'pv') {
    if (!visits.has(row.id)) visits.set(row.id, { ...row, dep: 0, ms: 0, events: [] })
    return
  }
  const visit = visits.get(row.id)
  if (!visit) return
  if (row.k === 'lv') {
    visit.dep = Math.max(visit.dep, row.dep)
    visit.ms = Math.max(visit.ms, row.ms)
  } else visit.events.push(row.e)
}

function persist(rows: Row[]) {
  if (!rows.length) return
  mkdirSync(DIR, { recursive: true })
  appendFileSync(FILE, rows.map((r) => JSON.stringify(r)).join('\n') + '\n')
  rows.forEach(apply)
}

function dailySalt(day: string) {
  let salts: Record<string, string> = {}
  try {
    salts = JSON.parse(readFileSync(SALT_FILE, 'utf8')) as Record<string, string>
  } catch {
    /* first run */
  }
  if (!salts[day]) {
    // Only today's salt is kept, so yesterday's visitor hashes can never be recomputed.
    salts = { [day]: randomBytes(16).toString('hex') }
    mkdirSync(DIR, { recursive: true })
    writeFileSync(SALT_FILE, JSON.stringify(salts))
  }
  return salts[day]
}

const dayOf = (ts: number) => new Date(ts).toISOString().slice(0, 10)

function visitorId(req: IncomingMessage, realtor: string, ts: number) {
  const fwd = String(req.headers['x-forwarded-for'] ?? '').split(',')[0].trim()
  const ip = fwd || req.socket.remoteAddress || ''
  const ua = String(req.headers['user-agent'] ?? '')
  return createHash('sha256').update(`${dailySalt(dayOf(ts))}|${ip}|${ua}|${realtor}`).digest('hex').slice(0, 16)
}

const SOURCE_ALIASES: Record<string, string> = {
  ig: 'instagram',
  instagram: 'instagram',
  fb: 'facebook',
  facebook: 'facebook',
  wa: 'whatsapp',
  whatsapp: 'whatsapp',
  linkedin: 'linkedin',
  li: 'linkedin',
  x: 'x',
  twitter: 'x',
  email: 'email',
  newsletter: 'email',
  mail: 'email',
  qr: 'qr',
  print: 'qr',
  google: 'google',
  bing: 'bing',
  tiktok: 'tiktok',
  youtube: 'youtube',
}

const REFERRER_SOURCES: [RegExp, string][] = [
  [/(^|\.)instagram\.com$/, 'instagram'],
  [/(^|\.)(facebook\.com|fb\.me|fb\.com)$/, 'facebook'],
  [/(^|\.)(whatsapp\.com|wa\.me)$/, 'whatsapp'],
  [/(^|\.)(t\.co|x\.com|twitter\.com)$/, 'x'],
  [/(^|\.)(linkedin\.com|lnkd\.in)$/, 'linkedin'],
  [/(^|\.)(tiktok\.com)$/, 'tiktok'],
  [/(^|\.)(youtube\.com|youtu\.be)$/, 'youtube'],
  [/(^|\.)(mail\.google\.com|outlook\.live\.com|outlook\.office\.com|mail\.yahoo\.com)$/, 'email'],
  [/(^|\.)google\.[a-z.]+$/, 'google'],
  [/(^|\.)bing\.com$/, 'bing'],
  [/(^|\.)duckduckgo\.com$/, 'duckduckgo'],
]

function classify(tag: string | null, referrer: string | null, host: string): { src: string; ref: string | null } {
  const t = tag?.toLowerCase().trim()
  if (t) return { src: SOURCE_ALIASES[t] ?? (t.replace(/[^a-z0-9-]/g, '').slice(0, 24) || 'other'), ref: null }
  if (!referrer) return { src: 'direct', ref: null }
  let refHost = ''
  try {
    refHost = new URL(referrer).hostname.replace(/^www\./, '')
  } catch {
    return { src: 'direct', ref: null }
  }
  if (!refHost || refHost === host.replace(/^www\./, '').split(':')[0]) return { src: 'internal', ref: null }
  const hit = REFERRER_SOURCES.find(([re]) => re.test(refHost))
  return hit ? { src: hit[1], ref: refHost } : { src: 'other', ref: refHost }
}

const TZ_COUNTRY: Record<string, string> = {
  'America/New_York': 'US', 'America/Chicago': 'US', 'America/Denver': 'US', 'America/Los_Angeles': 'US', 'America/Phoenix': 'US',
  'America/Toronto': 'CA', 'America/Vancouver': 'CA', 'America/Mexico_City': 'MX', 'America/Sao_Paulo': 'BR',
  'Europe/London': 'GB', 'Europe/Dublin': 'IE', 'Europe/Paris': 'FR', 'Europe/Berlin': 'DE', 'Europe/Madrid': 'ES', 'Europe/Rome': 'IT',
  'Europe/Amsterdam': 'NL', 'Europe/Lisbon': 'PT', 'Europe/Zurich': 'CH', 'Europe/Stockholm': 'SE', 'Europe/Istanbul': 'TR',
  'Asia/Dubai': 'AE', 'Asia/Kolkata': 'IN', 'Asia/Calcutta': 'IN', 'Asia/Singapore': 'SG', 'Asia/Hong_Kong': 'HK', 'Asia/Tokyo': 'JP',
  'Asia/Shanghai': 'CN', 'Asia/Riyadh': 'SA', 'Asia/Qatar': 'QA', 'Australia/Sydney': 'AU', 'Australia/Melbourne': 'AU',
  'Pacific/Auckland': 'NZ', 'Africa/Johannesburg': 'ZA', 'Africa/Lagos': 'NG',
}

/** Hosting geo headers when deployed; the visitor's time zone as a fallback (city level, no IP lookup). */
function geo(req: IncomingMessage, tz: string | null) {
  const h = req.headers
  const country = String(h['x-vercel-ip-country'] ?? h['cf-ipcountry'] ?? '') || null
  const cityRaw = String(h['x-vercel-ip-city'] ?? '')
  const city = cityRaw ? decodeURIComponent(cityRaw) : null
  if (country) return { c: country, ci: city }
  if (tz && /^[A-Za-z_]+\/[A-Za-z_]+$/.test(tz)) return { c: TZ_COUNTRY[tz] ?? null, ci: tz.split('/')[1].replace(/_/g, ' ') }
  return { c: null, ci: null }
}

const clean = (v: unknown, max = 120) => (typeof v === 'string' ? v.slice(0, max) : null)
const isId = (v: unknown): v is string => typeof v === 'string' && /^[a-zA-Z0-9-]{8,64}$/.test(v)

function collect(req: IncomingMessage, body: Record<string, unknown>): Row | null {
  if (BOT_UA.test(String(req.headers['user-agent'] ?? ''))) return null
  const ts = Date.now()
  const id = body.id
  if (!isId(id)) return null
  if (body.k === 'pv') {
    const realtor = clean(body.r, 60)
    if (!realtor || visits.has(id)) return null
    const device: Device = body.d === 'phone' || body.d === 'tablet' ? body.d : 'desktop'
    const host = String(req.headers.host ?? '')
    const { src, ref } = classify(clean(body.tag, 40), clean(body.ref, 500), host)
    return {
      k: 'pv',
      id,
      ts,
      r: realtor,
      l: isId(body.l) ? body.l : null,
      p: clean(body.p, 300) ?? '/',
      v: visitorId(req, realtor, ts),
      d: device,
      ...geo(req, clean(body.tz, 60)),
      src: body.entry ? src : 'internal',
      ref,
      entry: Boolean(body.entry),
      walk: Boolean(body.walk),
    }
  }
  if (!visits.has(id)) return null
  if (body.k === 'lv') {
    const dep = Math.min(1, Math.max(0, Number(body.dep) || 0))
    const ms = Math.min(MAX_ACTIVE_MS, Math.max(0, Math.round(Number(body.ms) || 0)))
    return { k: 'lv', id, ts, dep, ms }
  }
  if (body.k === 'ev' && EVENT_TYPES.includes(body.e as EventType)) return { k: 'ev', id, ts, e: body.e as EventType }
  return null
}

// ---------------------------------------------------------------------------------------------
// Summary

type Query = { realtor: string; listing: string | null; from: number; to: number; marks: number[] }

function inRange(v: Visit, q: Query, from = q.from, to = q.to) {
  return v.r === q.realtor && v.ts >= from && v.ts < to && (!q.listing || v.l === q.listing)
}

function totals(list: Visit[]) {
  const visitors = new Set(list.map((v) => `${dayOf(v.ts)}|${v.v}`)).size
  const enquiries = list.reduce((n, v) => n + v.events.filter((e) => e === 'enquiry').length, 0)
  const timed = list.filter((v) => v.ms > 0)
  return {
    views: list.length,
    visitors,
    enquiries,
    enquiryRate: visitors ? enquiries / visitors : 0,
    avgTimeMs: timed.length ? Math.round(timed.reduce((n, v) => n + v.ms, 0) / timed.length) : 0,
  }
}

function walkthrough(list: Visit[], marks: number[]) {
  const withWalk = list.filter((v) => v.walk)
  const started = withWalk.filter((v) => v.dep >= STARTED_AT)
  const finished = started.filter((v) => v.dep >= FINISHED_AT)
  const reach = (at: number) => (started.length ? started.filter((v) => v.dep >= at).length / started.length : 0)
  return {
    views: withWalk.length,
    started: started.length,
    finished: finished.length,
    startRate: withWalk.length ? started.length / withWalk.length : 0,
    finishRate: started.length ? finished.length / started.length : 0,
    avgDepth: started.length ? started.reduce((n, v) => n + v.dep, 0) / started.length : 0,
    curve: Array.from({ length: 21 }, (_, i) => reach(i / 20)),
    marks: marks.map((at) => ({ at, reach: reach(at) })),
  }
}

function countBy<T extends string>(list: Visit[], key: (v: Visit) => T | null) {
  const out = new Map<T, number>()
  for (const v of list) {
    const k = key(v)
    if (k) out.set(k, (out.get(k) ?? 0) + 1)
  }
  return [...out.entries()].map(([name, count]) => ({ name, count })).sort((a, b) => b.count - a.count)
}

function summary(q: Query) {
  load()
  const all = [...visits.values()]
  const list = all.filter((v) => inRange(v, q))
  const span = q.to - q.from
  const prev = all.filter((v) => inRange(v, q, q.from - span, q.from))

  const days: { day: string; views: number; visitors: number; enquiries: number }[] = []
  for (let t = q.from; t < q.to; t += 86_400_000) {
    const day = dayOf(t)
    const of = list.filter((v) => dayOf(v.ts) === day)
    days.push({ day, ...pick(totals(of), ['views', 'visitors', 'enquiries']) })
  }

  const events = Object.fromEntries(
    EVENT_TYPES.map((e) => {
      const hits = list.filter((v) => v.events.includes(e))
      return [e, { count: list.reduce((n, v) => n + v.events.filter((x) => x === e).length, 0), visits: hits.length }]
    }),
  )

  const byListing = new Map<string, Visit[]>()
  for (const v of list) if (v.l) byListing.set(v.l, [...(byListing.get(v.l) ?? []), v])
  const listings = [...byListing.entries()]
    .map(([id, vs]) => {
      const w = walkthrough(vs, [])
      return { id, ...totals(vs), finishRate: w.finishRate, avgDepth: w.avgDepth, hasWalk: w.views > 0 }
    })
    .sort((a, b) => b.views - a.views)

  const entries = list.filter((v) => v.entry)
  return {
    range: { from: q.from, to: q.to },
    totals: totals(list),
    previous: totals(prev),
    days,
    sources: countBy(entries, (v) => v.src),
    referrers: countBy(entries, (v) => v.ref),
    devices: countBy(list, (v) => v.d),
    countries: countBy(list, (v) => v.c),
    cities: countBy(list, (v) => (v.ci ? `${v.ci}${v.c ? `|${v.c}` : ''}` : null)),
    walkthrough: walkthrough(list, q.marks),
    events,
    listings,
    siteViews: list.filter((v) => !v.l).length,
    sample: list.some((v) => v.s),
  }
}

function pick<T extends object, K extends keyof T>(o: T, keys: K[]) {
  return Object.fromEntries(keys.map((k) => [k, o[k]])) as Pick<T, K>
}

// ---------------------------------------------------------------------------------------------
// Sample traffic (prototype only, flagged and removable)

type SampleListing = { id: string; path: string; walk: boolean }

function rand(seed: number) {
  let s = seed >>> 0
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0
    return s / 4294967296
  }
}

function weighted<T>(r: () => number, items: [T, number][]) {
  const total = items.reduce((n, [, w]) => n + w, 0)
  let x = r() * total
  for (const [item, w] of items) if ((x -= w) <= 0) return item
  return items[items.length - 1][0]
}

const SAMPLE_CITIES: [[string, string], number][] = [
  [['New York', 'US'], 18], [['Los Angeles', 'US'], 12], [['Miami', 'US'], 10], [['San Francisco', 'US'], 6], [['Chicago', 'US'], 5],
  [['Austin', 'US'], 4], [['Boston', 'US'], 4], [['London', 'GB'], 7], [['Toronto', 'CA'], 5], [['Dubai', 'AE'], 4],
  [['Mumbai', 'IN'], 3], [['Paris', 'FR'], 2], [['Sydney', 'AU'], 2],
]
const SAMPLE_SOURCES: [[string, string | null], number][] = [
  [['instagram', 'l.instagram.com'], 32], [['whatsapp', null], 17], [['google', 'google.com'], 15], [['direct', null], 14],
  [['facebook', 'm.facebook.com'], 8], [['qr', null], 5], [['email', null], 4], [['linkedin', 'linkedin.com'], 2], [['other', 'zillow.com'], 3],
]

function sample(realtor: string, listings: SampleListing[]) {
  const r = rand(Date.now())
  const rows: Row[] = []
  const now = Date.now()
  const DAYS = 60
  for (let d = DAYS; d >= 0; d--) {
    const dayStart = now - d * 86_400_000
    const weekday = new Date(dayStart).getDay()
    const weekly = weekday === 0 || weekday === 6 ? 1.35 : 1
    const growth = 0.55 + 0.45 * (1 - d / DAYS)
    const site = listings.length ? listings : []
    const today: { v: string; d: Device; c: string; ci: string }[] = []
    for (const [i, listing] of [{ id: '', path: `/${realtor}`, walk: false }, ...site].entries()) {
      const base = i === 0 ? 9 : 16 + ((i * 37) % 30)
      const n = Math.round(base * weekly * growth * (0.75 + r() * 0.5))
      for (let k = 0; k < n; k++) {
        const ts = Math.min(now - 60_000, dayStart - 86_400_000 + r() * 86_400_000)
        const id = randomUUID()
        const returning = today.length > 3 && r() < 0.28
        let who = today[Math.floor(r() * today.length)]
        if (!returning) {
          const [ci, c] = weighted(r, SAMPLE_CITIES)
          who = { v: randomBytes(8).toString('hex'), d: weighted(r, [['phone', 68], ['desktop', 25], ['tablet', 7]]), c, ci }
          today.push(who)
        }
        const [src, ref] = returning ? ['internal', null] : weighted(r, SAMPLE_SOURCES)
        rows.push({
          k: 'pv', id, ts, r: realtor, l: listing.id || null, p: listing.path, v: who.v, d: who.d, c: who.c, ci: who.ci,
          src, ref, entry: !returning, walk: listing.walk, s: true,
        })
        const started = listing.walk && r() < 0.88
        const dep = !listing.walk ? 0 : started ? Math.min(1, r() < 0.47 ? 1 : Math.pow(r(), 0.8) * 0.97 + 0.03) : r() * 0.02
        rows.push({ k: 'lv', id, ts: ts + 1000, dep, ms: Math.round(15_000 + Math.pow(r(), 1.6) * 260_000 * (dep || 0.4)), s: true })
        const events: [EventType, number][] = [
          ['gallery_open', 0.24], ['floorplan_view', 0.16], ['enquiry_click', 0.07], ['whatsapp_click', 0.03], ['phone_click', 0.02], ['email_click', 0.01],
        ]
        for (const [e, p] of events) if (listing.id && r() < p) rows.push({ k: 'ev', id, ts: ts + 2000, e, s: true })
        if (listing.id && r() < 0.013 + dep * 0.012) rows.push({ k: 'ev', id, ts: ts + 3000, e: 'enquiry', s: true })
      }
    }
  }
  persist(rows)
  return rows.filter((x) => x.k === 'pv').length
}

function removeSample() {
  load()
  const keep = [...visits.values()].filter((v) => !v.s)
  visits.clear()
  const rows: Row[] = []
  for (const v of keep) {
    const { dep, ms, events, ...pv } = v
    rows.push(pv)
    if (dep || ms) rows.push({ k: 'lv', id: v.id, ts: v.ts, dep, ms })
    for (const e of events) rows.push({ k: 'ev', id: v.id, ts: v.ts, e })
  }
  mkdirSync(DIR, { recursive: true })
  writeFileSync(FILE, rows.map((x) => JSON.stringify(x)).join('\n') + (rows.length ? '\n' : ''))
  rows.forEach(apply)
}

// ---------------------------------------------------------------------------------------------
// HTTP

function readBody(req: IncomingMessage): Promise<string> {
  return new Promise((ok, fail) => {
    let size = 0
    const chunks: Buffer[] = []
    req.on('data', (c: Buffer) => {
      size += c.length
      if (size > MAX_BODY * 64) req.destroy()
      else chunks.push(c)
    })
    req.on('end', () => ok(Buffer.concat(chunks).toString('utf8')))
    req.on('error', fail)
  })
}

function json(res: ServerResponse, status: number, data: unknown) {
  res.statusCode = status
  res.setHeader('content-type', 'application/json')
  res.setHeader('cache-control', 'no-store')
  res.end(JSON.stringify(data))
}

async function handle(req: IncomingMessage, res: ServerResponse) {
  load()
  const url = new URL(req.url ?? '/', 'http://local')
  const route = url.pathname.replace(/\/+$/, '')

  if (route === '/collect' && req.method === 'POST') {
    const raw = await readBody(req)
    if (raw.length > MAX_BODY) return json(res, 413, { ok: false })
    let body: Record<string, unknown>
    try {
      body = JSON.parse(raw) as Record<string, unknown>
    } catch {
      return json(res, 400, { ok: false })
    }
    const row = collect(req, body)
    if (row) persist([row])
    res.statusCode = 204
    return res.end()
  }

  if (route === '/summary' && req.method === 'GET') {
    const realtor = url.searchParams.get('realtor')
    if (!realtor) return json(res, 400, { error: 'realtor required' })
    const to = Number(url.searchParams.get('to')) || Date.now()
    const days = Math.min(3650, Math.max(1, Number(url.searchParams.get('days')) || 30))
    const marks = (url.searchParams.get('marks') ?? '')
      .split(',')
      .map(Number)
      .filter((n) => n > 0 && n < 1)
      .slice(0, 24)
    return json(res, 200, summary({ realtor, listing: url.searchParams.get('listing'), from: to - days * 86_400_000, to, marks }))
  }

  if (route === '/sample' && req.method === 'POST') {
    const body = JSON.parse(await readBody(req)) as { realtor?: string; listings?: SampleListing[] }
    if (!body.realtor) return json(res, 400, { error: 'realtor required' })
    const listings = (body.listings ?? []).filter((l) => isId(l.id)).slice(0, 50)
    return json(res, 200, { added: sample(body.realtor, listings) })
  }

  if (route === '/sample' && req.method === 'DELETE') {
    removeSample()
    return json(res, 200, { ok: true })
  }

  json(res, 404, { error: 'not found' })
}

export function analyticsPlugin(): Plugin {
  return {
    name: 'ye-analytics',
    configureServer(server) {
      server.middlewares.use('/api/a', (req, res) => {
        handle(req, res).catch((err: Error) => {
          console.error('[analytics]', err)
          if (!res.headersSent) json(res, 500, { error: 'analytics failed' })
          else res.end()
        })
      })
    },
  }
}

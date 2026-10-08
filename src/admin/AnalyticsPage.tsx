import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { TrendChart } from '../components/TrendChart'
import {
  DEVICE_LABEL,
  EVENT_LABEL,
  countryName,
  delta,
  fetchSummary,
  fmtDuration,
  fmtInt,
  fmtPct,
  walkStages,
  sourceLabel,
  type Count,
  type Summary,
} from '../lib/analyticsData'
import { useAuth } from '../lib/auth'
import { useProto } from '../lib/prototype'
import { useRealtor } from '../lib/realtor'
import { useDocumentTitle, useSite } from '../lib/site'
import { weeklyEmailHtml } from '../lib/weeklyEmail'
import { asObject, type ExperienceConfig } from '../types/content'
import type { ListingRow } from '../types/database'
import { listListings } from './api'
import { EmptyState, Spinner, errorMessage, useToast } from './ui'

const RANGES = [
  { days: 7, label: '7 days' },
  { days: 30, label: '30 days' },
  { days: 90, label: '90 days' },
  { days: 365, label: '12 months' },
]
const WEEKLY_KEY = 'ye:weekly-email'

export function AnalyticsPage() {
  useDocumentTitle('Analytics')
  const toast = useToast()
  const { slug: realtor, listing: listingPath } = useRealtor()
  const [params, setParams] = useSearchParams()
  const days = Number(params.get('days')) || 30
  const listingId = params.get('listing')
  const [listings, setListings] = useState<ListingRow[] | null>(null)
  const [data, setData] = useState<Summary | null>(null)
  const [failed, setFailed] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [nonce, setNonce] = useState(0)

  useEffect(() => {
    listListings()
      .then(setListings)
      .catch(() => setListings([]))
  }, [])

  const listing = listings?.find((l) => l.id === listingId) ?? null
  const beats = useMemo(
    () =>
      [...(asObject<ExperienceConfig>(listing?.experience).beats ?? [])]
        .filter((b) => b && b.text)
        .sort((a, b) => a.at - b.at),
    [listing],
  )

  useEffect(() => {
    let live = true
    setLoading(true)
    fetchSummary({ realtor, days, listing: listingId, marks: beats.map((b) => b.at) })
      .then((s) => live && (setData(s), setFailed(null)))
      .catch((err) => live && setFailed(errorMessage(err)))
      .finally(() => live && setLoading(false))
    return () => {
      live = false
    }
  }, [realtor, days, listingId, beats, nonce])

  const refresh = useCallback(() => setNonce((n) => n + 1), [])
  const setParam = (key: string, value: string | null) => {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    setParams(next, { replace: true })
  }

  const titles = useMemo(() => Object.fromEntries((listings ?? []).map((l) => [l.id, l.title])), [listings])

  const loadSample = async () => {
    const published = (listings ?? []).filter((l) => l.status === 'published')
    const res = await fetch('/api/a/sample', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        realtor,
        listings: published.map((l) => ({ id: l.id, path: listingPath(l.slug), walk: l.experience_type === 'immersive' })),
      }),
    })
    if (!res.ok) return toast('Could not add sample traffic', 'error')
    toast('Sample traffic added')
    refresh()
  }

  const removeSample = async () => {
    await fetch('/api/a/sample', { method: 'DELETE' })
    toast('Sample traffic removed')
    refresh()
  }

  if (failed && !data)
    return (
      <div className="a-page">
        <h1 className="a-title">Analytics</h1>
        <p className="a-note a-note--warn">{failed}</p>
      </div>
    )

  const empty = data && data.totals.views === 0

  return (
    <div className="a-page an-page">
      <header className="a-page__head">
        <div className="a-page__head-main">
          <h1 className="a-title">Analytics</h1>
          <p className="a-page__sub">Every visit to your site and listings, recorded without cookies.</p>
        </div>
        <div className="an-controls">
          <select className="a-input" value={listingId ?? ''} onChange={(e) => setParam('listing', e.target.value || null)} aria-label="Listing">
            <option value="">All listings and site</option>
            {(listings ?? []).map((l) => (
              <option key={l.id} value={l.id}>
                {l.title}
              </option>
            ))}
          </select>
          <div className="ai-seg" role="group" aria-label="Date range">
            {RANGES.map((r) => (
              <button key={r.days} type="button" className={days === r.days ? 'is-on' : ''} onClick={() => setParam('days', String(r.days))}>
                {r.label}
              </button>
            ))}
          </div>
          <button type="button" className="a-btn a-btn--ghost" onClick={refresh} aria-label="Refresh">
            ↻
          </button>
        </div>
      </header>

      {!data ? (
        <Spinner />
      ) : (
        <div className={`an-body${loading ? ' is-loading' : ''}`}>
          {data.sample && (
            <p className="a-note an-sample">
              This includes <strong>sample traffic</strong> so you can see the dashboard filled in. Real visits are recorded alongside it.
              <button type="button" className="a-link" onClick={() => void removeSample()}>
                Remove sample traffic
              </button>
            </p>
          )}

          {empty && (
            <EmptyState title="No visits in this period yet">
              <p>
                Visits appear here a few seconds after they happen. Your own visits are not counted while you are signed in, so open your site in a
                private window to see one arrive.
              </p>
              <button type="button" className="a-btn a-btn--ghost" onClick={() => void loadSample()}>
                Load sample traffic (prototype)
              </button>
            </EmptyState>
          )}

          {!empty && (
            <>
              {listing && <ListingActions listing={listing} path={listingPath(listing.slug)} />}
              <Kpis data={data} />

              <section className="a-card">
                <h2 className="a-card__title">Visits over time</h2>
                <TrendChart days={data.days} />
              </section>

              <div className="an-grid">
                <Walkthrough data={data} beats={beats} listingSelected={Boolean(listing)} />
                <Engagement data={data} />
              </div>

              <div className="an-grid an-grid--3">
                <section className="a-card">
                  <h2 className="a-card__title">Where visitors came from</h2>
                  <BarList items={data.sources} label={sourceLabel} />
                  <p className="an-foot">
                    A link covers anything shared, messaged, posted or typed in. Google includes other search engines like Bing.
                  </p>
                </section>
                <section className="a-card">
                  <h2 className="a-card__title">Devices</h2>
                  <BarList items={data.devices} label={(k) => DEVICE_LABEL[k] ?? k} />
                </section>
                <section className="a-card">
                  <h2 className="a-card__title">Locations</h2>
                  <BarList
                    items={data.cities.slice(0, 8)}
                    label={(k) => {
                      const [city, country] = k.split('|')
                      return `${city}${country ? `, ${countryName(country)}` : ''}`
                    }}
                  />
                  {data.countries.length > 0 && (
                    <p className="an-foot">
                      {data.countries.length} {data.countries.length === 1 ? 'country' : 'countries'}:{' '}
                      {data.countries
                        .slice(0, 5)
                        .map((c) => countryName(c.name))
                        .join(', ')}
                    </p>
                  )}
                </section>
              </div>

              {!listing && <ListingsTable data={data} titles={titles} onPick={(id) => setParam('listing', id)} />}
            </>
          )}

          <WeeklyEmail realtor={realtor} titles={titles} />
        </div>
      )}
    </div>
  )
}

function Delta({ now, before }: { now: number; before: number }) {
  const d = delta(now, before)
  if (d === null) return <small className="an-delta">No earlier data</small>
  const pct = Math.round(d * 100)
  return (
    <small className={`an-delta ${pct > 0 ? 'is-up' : pct < 0 ? 'is-down' : ''}`}>
      {pct > 0 ? '▲' : pct < 0 ? '▼' : '•'} {Math.abs(pct)}% vs previous period
    </small>
  )
}

function Kpis({ data }: { data: Summary }) {
  const t = data.totals
  const p = data.previous
  return (
    <div className="an-kpis">
      <div className="an-kpi">
        <span>Views</span>
        <strong>{fmtInt(t.views)}</strong>
        <Delta now={t.views} before={p.views} />
      </div>
      <div className="an-kpi">
        <span>Unique visitors</span>
        <strong>{fmtInt(t.visitors)}</strong>
        <Delta now={t.visitors} before={p.visitors} />
      </div>
      <div className="an-kpi">
        <span>Enquiries</span>
        <strong>{fmtInt(t.enquiries)}</strong>
        <Delta now={t.enquiries} before={p.enquiries} />
      </div>
      <div className="an-kpi">
        <span>Enquiry rate</span>
        <strong>{fmtPct(t.enquiryRate, 1)}</strong>
        <small className="an-delta">Enquiries per visitor</small>
      </div>
      <div className="an-kpi">
        <span>Avg. time on page</span>
        <strong>{fmtDuration(t.avgTimeMs)}</strong>
        <Delta now={t.avgTimeMs} before={p.avgTimeMs} />
      </div>
    </div>
  )
}

function BarList({ items, label }: { items: Count[]; label: (key: string) => string }) {
  const total = items.reduce((n, i) => n + i.count, 0)
  if (!items.length) return <p className="a-muted">No data yet.</p>
  return (
    <ul className="an-bars">
      {items.map((i) => (
        <li key={i.name}>
          <span className="an-bars__fill" style={{ width: `${(i.count / items[0].count) * 100}%` }} />
          <span className="an-bars__label">{label(i.name)}</span>
          <span className="an-bars__value">
            {fmtInt(i.count)} <em>{fmtPct(i.count / total)}</em>
          </span>
        </li>
      ))}
    </ul>
  )
}

function Walkthrough({ data, beats, listingSelected }: { data: Summary; beats: { id: string; label: string; text: string; at: number }[]; listingSelected: boolean }) {
  const w = data.walkthrough
  if (!w.views)
    return (
      <section className="a-card">
        <h2 className="a-card__title">Walkthrough</h2>
        <p className="a-muted">No walkthrough views in this period.</p>
      </section>
    )
  const stages = walkStages(w, listingSelected ? beats : [])
  return (
    <section className="a-card">
      <h2 className="a-card__title">Walkthrough</h2>
      <div className="an-walk">
        <div>
          <strong>{fmtPct(w.startRate)}</strong>
          <span>started it</span>
        </div>
        <div>
          <strong>{fmtPct(w.avgDepth)}</strong>
          <span>average distance watched</span>
        </div>
        <div>
          <strong>{fmtPct(w.finishRate)}</strong>
          <span>watched to the end</span>
        </div>
      </div>
      <p className="an-sub">{listingSelected && w.marks.length ? 'How far visitors got, room by room' : 'How far visitors got'}</p>
      <ol className="an-funnel">
        {stages.map((s) => (
          <li key={s.label}>
            <span className="an-funnel__label">{s.label}</span>
            <span className="an-funnel__track">
              <span style={{ width: `${s.reach * 100}%` }} />
            </span>
            <span className="an-funnel__value">{fmtPct(s.reach)}</span>
          </li>
        ))}
      </ol>
      <p className="an-foot">Of {fmtInt(w.started)} visitors who started the walkthrough.</p>
    </section>
  )
}

function Engagement({ data }: { data: Summary }) {
  const views = data.totals.views || 1
  return (
    <section className="a-card">
      <h2 className="a-card__title">What visitors did</h2>
      <ul className="an-actions">
        {(Object.keys(EVENT_LABEL) as (keyof typeof EVENT_LABEL)[]).map((k) => (
          <li key={k}>
            <span>{EVENT_LABEL[k]}</span>
            <strong>{fmtInt(data.events[k]?.count ?? 0)}</strong>
            <em>{fmtPct((data.events[k]?.visits ?? 0) / views)} of visits</em>
          </li>
        ))}
        <li className="is-key">
          <span>Sent an enquiry</span>
          <strong>{fmtInt(data.totals.enquiries)}</strong>
          <em>{fmtPct((data.events.enquiry?.visits ?? 0) / views, 1)} of visits</em>
        </li>
      </ul>
    </section>
  )
}

function ListingsTable({ data, titles, onPick }: { data: Summary; titles: Record<string, string>; onPick: (id: string) => void }) {
  return (
    <section className="a-card">
      <h2 className="a-card__title">By listing</h2>
      <div className="an-table-wrap">
        <table className="an-table">
          <thead>
            <tr>
              <th>Listing</th>
              <th>Views</th>
              <th>Visitors</th>
              <th>Enquiries</th>
              <th>Enquiry rate</th>
              <th>Watched to end</th>
              <th>Avg. time</th>
            </tr>
          </thead>
          <tbody>
            {data.listings.map((l) => (
              <tr key={l.id} onClick={() => onPick(l.id)}>
                <td>
                  <button type="button" className="a-link">
                    {titles[l.id] ?? 'Removed listing'}
                  </button>
                </td>
                <td>{fmtInt(l.views)}</td>
                <td>{fmtInt(l.visitors)}</td>
                <td>{fmtInt(l.enquiries)}</td>
                <td>{fmtPct(l.enquiryRate, 1)}</td>
                <td>{l.hasWalk ? fmtPct(l.finishRate) : '—'}</td>
                <td>{fmtDuration(l.avgTimeMs)}</td>
              </tr>
            ))}
            {data.siteViews > 0 && (
              <tr className="is-site">
                <td>Site pages (home, properties)</td>
                <td>{fmtInt(data.siteViews)}</td>
                <td colSpan={5} />
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function ListingActions({ listing, path }: { listing: ListingRow; path: string }) {
  const toast = useToast()
  const url = `${window.location.origin}${path}`
  const copy = async () => {
    await navigator.clipboard.writeText(url)
    toast('Link copied')
  }
  return (
    <section className="a-card an-share">
      <div>
        <h2 className="a-card__title">{listing.title}</h2>
        <div className="an-share__links">
          <code className="an-share__url">{url.replace(/^https?:\/\//, '')}</code>
          <button type="button" className="a-btn a-btn--ghost a-btn--sm" onClick={() => void copy()}>
            Copy link
          </button>
        </div>
      </div>
      <a className="a-btn a-btn--primary" href={`${path}/report`} target="_blank" rel="noreferrer">
        Seller report ↗
      </a>
    </section>
  )
}

function WeeklyEmail({ realtor, titles }: { realtor: string; titles: Record<string, string> }) {
  const proto = useProto()
  const { profile, session } = useAuth()
  const { settings } = useSite()
  const [on, setOn] = useState(() => localStorage.getItem(WEEKLY_KEY) !== 'off')
  const [html, setHtml] = useState<string | null>(null)

  const toggle = () => {
    const next = !on
    setOn(next)
    localStorage.setItem(WEEKLY_KEY, next ? 'on' : 'off')
  }

  const preview = async () => {
    const summary = await fetchSummary({ realtor, days: 7 })
    setHtml(
      weeklyEmailHtml({
        brand: settings.brand_name,
        firstName: (proto.ownerName || profile?.full_name || '').split(' ')[0],
        summary,
        titles,
        studioUrl: `${window.location.origin}/studio/analytics?days=7`,
      }),
    )
  }

  return (
    <section className="a-card an-email">
      <div className="an-email__head">
        <div>
          <h2 className="a-card__title">Weekly email</h2>
          <p className="a-muted">
            Every Monday morning: views, enquiries and your top listings, sent to {session?.user.email ?? 'your inbox'}.
          </p>
        </div>
        <label className="an-switch">
          <input type="checkbox" checked={on} onChange={toggle} />
          <span>{on ? 'On' : 'Off'}</span>
        </label>
      </div>
      <button type="button" className="a-btn a-btn--ghost a-btn--sm" onClick={() => void preview()}>
        Preview this week's email
      </button>
      {html && (
        <div className="an-email__preview">
          <iframe title="Weekly email preview" srcDoc={html} />
          <button type="button" className="a-link" onClick={() => setHtml(null)}>
            Close preview
          </button>
        </div>
      )}
    </section>
  )
}

import { useEffect, useMemo, useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { TrendChart } from '../components/TrendChart'
import { fetchListingBySlug } from '../lib/api'
import {
  DEVICE_LABEL,
  EVENT_LABEL,
  countryName,
  fetchSummary,
  fmtDay,
  fmtDuration,
  fmtInt,
  fmtPct,
  sourceLabel,
  walkStages,
  type Count,
  type Summary,
} from '../lib/analyticsData'
import { useRealtor } from '../lib/realtor'
import { useDocumentTitle, useSite } from '../lib/site'
import { asObject, type ExperienceConfig, type ListingWithRelations } from '../types/content'
import { NotFound } from './NotFound'

const PERIODS = [7, 30, 90]

/** One-page report an agent sends to the homeowner: share the link or save it as a PDF. */
export function SellerReport() {
  const { slug = '' } = useParams()
  const [params, setParams] = useSearchParams()
  const days = PERIODS.includes(Number(params.get('days'))) ? Number(params.get('days')) : 30
  const { slug: realtor, base } = useRealtor()
  const { settings } = useSite()
  const [listing, setListing] = useState<ListingWithRelations | null | undefined>(undefined)
  const [data, setData] = useState<Summary | null>(null)
  const [copied, setCopied] = useState(false)

  useDocumentTitle(listing ? `${listing.title} · Report` : 'Report')

  useEffect(() => {
    fetchListingBySlug(slug)
      .then(setListing)
      .catch(() => setListing(null))
  }, [slug])

  const beats = useMemo(
    () => [...(asObject<ExperienceConfig>(listing?.experience).beats ?? [])].filter((b) => b && b.text).sort((a, b) => a.at - b.at),
    [listing],
  )

  useEffect(() => {
    if (!listing) return
    fetchSummary({ realtor, days, listing: listing.id, marks: beats.map((b) => b.at) })
      .then(setData)
      .catch(() => setData(null))
  }, [listing, realtor, days, beats])

  if (listing === null) return <NotFound href={base} />
  if (!listing || !data) return <div className="page page--loading" aria-busy aria-label="Loading report" />

  const t = data.totals
  const w = data.walkthrough
  const views = t.views || 1
  const shareLink = `${window.location.origin}${window.location.pathname}?days=${days}`

  return (
    <div className="report">
      <div className="report__bar">
        <div className="report__periods" role="group" aria-label="Period">
          {PERIODS.map((p) => (
            <button key={p} type="button" className={p === days ? 'is-on' : ''} onClick={() => setParams({ days: String(p) }, { replace: true })}>
              Last {p} days
            </button>
          ))}
        </div>
        <div className="report__actions">
          <button
            type="button"
            onClick={() => {
              void navigator.clipboard.writeText(shareLink)
              setCopied(true)
              window.setTimeout(() => setCopied(false), 1800)
            }}
          >
            {copied ? 'Link copied' : 'Copy link'}
          </button>
          <button type="button" className="is-primary" onClick={() => window.print()}>
            Download PDF
          </button>
        </div>
      </div>

      <article className="report__sheet">
        <header className="report__head">
          <div>
            <p className="report__brand">{settings.brand_name}</p>
            <h1>{listing.title}</h1>
            <p className="report__period">
              Performance report · {fmtDay(data.days[0].day)} – {fmtDay(data.days[data.days.length - 1].day)}
            </p>
          </div>
          {listing.cover_image_url && <img src={listing.cover_image_url} alt="" />}
        </header>

        <section className="report__kpis">
          <div>
            <strong>{fmtInt(t.visitors)}</strong>
            <span>people visited</span>
          </div>
          <div>
            <strong>{fmtInt(t.views)}</strong>
            <span>page views</span>
          </div>
          <div>
            <strong>{fmtInt(t.enquiries)}</strong>
            <span>enquiries</span>
          </div>
          <div>
            <strong>{fmtDuration(t.avgTimeMs)}</strong>
            <span>average time on the listing</span>
          </div>
        </section>

        <section className="report__block">
          <h2>Visits over time</h2>
          <TrendChart days={data.days} className="trend--report" />
        </section>

        {w.views > 0 && (
          <section className="report__block">
            <h2>The walkthrough</h2>
            <p className="report__lead">
              <strong>{fmtPct(w.finishRate)}</strong> of visitors who started the walkthrough watched it to the end, and the average visitor saw{' '}
              <strong>{fmtPct(w.avgDepth)}</strong> of it.
            </p>
            <ol className="report__funnel">
              {walkStages(w, beats).map((s) => (
                <li key={s.label}>
                  <span>{s.label}</span>
                  <span className="report__track">
                    <span style={{ width: `${s.reach * 100}%` }} />
                  </span>
                  <span>{fmtPct(s.reach)}</span>
                </li>
              ))}
            </ol>
          </section>
        )}

        <div className="report__cols">
          <section className="report__block">
            <h2>Where they came from</h2>
            <ReportBars items={data.sources.slice(0, 6)} label={sourceLabel} />
          </section>
          <section className="report__block">
            <h2>Where they are</h2>
            <ReportBars
              items={data.cities.slice(0, 6)}
              label={(k) => {
                const [city, country] = k.split('|')
                return `${city}${country ? `, ${countryName(country)}` : ''}`
              }}
            />
          </section>
        </div>

        <div className="report__cols">
          <section className="report__block">
            <h2>Devices</h2>
            <ReportBars items={data.devices} label={(k) => DEVICE_LABEL[k] ?? k} />
          </section>
          <section className="report__block">
            <h2>What they did</h2>
            <ul className="report__did">
              {(['gallery_open', 'floorplan_view', 'enquiry_click'] as const).map((k) => (
                <li key={k}>
                  <span>{EVENT_LABEL[k]}</span>
                  <strong>{fmtPct((data.events[k]?.visits ?? 0) / views)}</strong>
                </li>
              ))}
              <li>
                <span>Sent an enquiry</span>
                <strong>{fmtInt(t.enquiries)}</strong>
              </li>
            </ul>
          </section>
        </div>

        <footer className="report__foot">
          <span>Prepared by {settings.brand_name}</span>
          <span>Visitor numbers are counted without cookies and exclude bots and the agent's own visits.</span>
        </footer>
      </article>
    </div>
  )
}

function ReportBars({ items, label }: { items: Count[]; label: (k: string) => string }) {
  const total = items.reduce((n, i) => n + i.count, 0)
  if (!items.length) return <p className="report__none">No data yet.</p>
  return (
    <ul className="report__bars">
      {items.map((i) => (
        <li key={i.name}>
          <span>{label(i.name)}</span>
          <span className="report__track">
            <span style={{ width: `${(i.count / items[0].count) * 100}%` }} />
          </span>
          <span>{fmtPct(i.count / total)}</span>
        </li>
      ))}
    </ul>
  )
}

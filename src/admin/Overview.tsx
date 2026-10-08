import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../lib/auth'
import { countryInfo, resumeStep, setProto, skipStep, useProto, type StepKey } from '../lib/prototype'
import { fetchSummary, fmtInt, fmtPct, type Summary } from '../lib/analyticsData'
import { useRealtor } from '../lib/realtor'
import { useDocumentTitle, useSite } from '../lib/site'
import type { ListingRow } from '../types/database'
import { countNewEnquiries, listListings } from './api'
import { useToast } from './ui'

type Step = {
  key: StepKey
  title: string
  body: string
  to: string
  cta: string
  required?: boolean
  teamOnly?: boolean
}

const STEPS: Step[] = [
  {
    key: 'details',
    title: 'Your details',
    body: 'Your name, logo and brokerage, plus a licence number if your country needs one. About a minute.',
    to: '/studio/settings',
    cta: 'Add details',
    required: true,
  },
  {
    key: 'property',
    title: 'Your first property',
    body: 'Upload a walkthrough video, or start with photos. This is what buyers will walk through.',
    to: '/studio/listings/new',
    cta: 'Create listing',
  },
  {
    key: 'contact',
    title: 'How buyers reach you',
    body: 'Email, phone, WhatsApp or your booking link. At least one is needed to publish.',
    to: '/studio/settings',
    cta: 'Add contact',
    required: true,
  },
  {
    key: 'style',
    title: 'Website style',
    body: 'Pick a style preset and colours. Skip it and your site uses Noir, which already looks finished.',
    to: '/studio/settings',
    cta: 'Choose a style',
  },
  {
    key: 'team',
    title: 'Invite your team',
    body: 'Add agents who publish listings under your brand.',
    to: '/studio/team',
    cta: 'Invite',
    teamOnly: true,
  },
]

function greeting() {
  const h = new Date().getHours()
  return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening'
}

const CHECK = (
  <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
    <path d="M5 12.5l4.5 4.5L19 7.5" />
  </svg>
)

export function Overview() {
  useDocumentTitle('Overview')
  const proto = useProto()
  const { settings } = useSite()
  const { profile } = useAuth()
  const { base, slug, listing: listingPath } = useRealtor()
  const toast = useToast()
  const [listings, setListings] = useState<ListingRow[] | null>(null)
  const [newEnquiries, setNewEnquiries] = useState(0)
  const [stats, setStats] = useState<Summary | null>(null)
  const [confirming, setConfirming] = useState(false)

  useEffect(() => {
    listListings()
      .then(setListings)
      .catch(() => setListings([]))
    countNewEnquiries()
      .then(setNewEnquiries)
      .catch(() => {})
  }, [])

  useEffect(() => {
    fetchSummary({ realtor: slug, days: 30 })
      .then(setStats)
      .catch(() => {})
  }, [slug])

  const free = proto.plan === 'free'
  const teamPlan = proto.plan === 'team' || proto.plan === 'brokerage'
  const name = (proto.ownerName || profile?.full_name || '').split(' ')[0]
  const isDone = (k: StepKey) => proto.done.includes(k)
  const canPublish = isDone('details') && isDone('contact')
  const styleIsSuggestion = proto.sitePublished && !isDone('style')

  const steps = useMemo(
    () => STEPS.filter((s) => (!s.teamOnly || teamPlan) && !(s.key === 'style' && styleIsSuggestion)),
    [teamPlan, styleIsSuggestion],
  )
  const doneCount = steps.filter((s) => proto.done.includes(s.key)).length
  const allDone = doneCount === steps.length
  const published = listings?.filter((l) => l.status === 'published').length ?? 0
  const firstListing = listings?.[0]
  const url = `${window.location.host}${base}`

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(`${window.location.origin}${base}`)
      toast('Link copied')
    } catch {
      toast('Could not copy the link', 'error')
    }
  }

  const publish = () => {
    if (!proto.complianceAck) return setConfirming(true)
    setProto({ sitePublished: true })
    toast('Your site is live')
  }

  return (
    <div className="a-page">
      <header className="a-page__head">
        <div>
          <p className="a-eyebrow">{settings.brand_name}</p>
          <h1 className="a-title">
            {greeting()}
            {name ? `, ${name}` : ''}.
          </h1>
        </div>
      </header>

      {free ? (
        <FreeOverview hasListing={Boolean(firstListing) || isDone('property')} previewHref={firstListing ? listingPath(firstListing.slug) : null} />
      ) : (
        <>
          <section className={`a-sitecard ${proto.sitePublished ? 'is-live' : ''}`}>
            <div className="a-sitecard__main">
              <span className={`a-sitecard__status ${proto.sitePublished ? 'is-live' : ''}`}>
                {proto.sitePublished ? 'Live' : 'Draft · only you can see it'}
              </span>
              <h2 className="a-sitecard__title">{proto.sitePublished ? 'Your website is live.' : 'Your website is ready to preview.'}</h2>
              <p className="a-sitecard__url">
                <code>{url}</code>
                <button type="button" className="a-link" onClick={() => void copy()}>
                  Copy link
                </button>
              </p>
              {!proto.sitePublished && !canPublish && (
                <p className="a-sitecard__need">
                  To publish, add {[!isDone('details') && 'your details', !isDone('contact') && 'one way for buyers to reach you'].filter(Boolean).join(' and ')}.
                </p>
              )}
            </div>
            <div className="a-sitecard__actions">
              <a href={base} target="_blank" rel="noreferrer" className="a-btn a-btn--ghost">
                {proto.sitePublished ? 'View site ↗' : 'Preview site ↗'}
              </a>
              {proto.sitePublished ? (
                <button type="button" className="a-btn a-btn--ghost" onClick={() => setProto({ sitePublished: false })}>
                  Unpublish
                </button>
              ) : (
                <button type="button" className="a-btn a-btn--primary" disabled={!canPublish} onClick={publish}>
                  Publish site
                </button>
              )}
            </div>
          </section>

          <div className="a-overview">
            <div className="a-overview__main">
              {proto.guideHidden ? (
                <button type="button" className="a-link" onClick={() => setProto({ guideHidden: false })}>
                  Show setup guide
                </button>
              ) : allDone ? (
                <section className="a-card a-setup a-setup--done">
                  <span className="a-setup__badge">{CHECK}</span>
                  <div>
                    <h2 className="a-card__title">Your workspace is fully set up.</h2>
                    <p className="a-muted">Add more listings any time. Every new home gets its own walkthrough page.</p>
                  </div>
                </section>
              ) : (
                <section className="a-card a-setup">
                  <div className="a-setup__head">
                    <div>
                      <p className="a-eyebrow">Getting started</p>
                      <h2 className="a-card__title">
                        {doneCount} of {steps.length} done
                      </h2>
                    </div>
                    {canPublish && (
                      <button type="button" className="a-link a-link--muted" onClick={() => setProto({ guideHidden: true })}>
                        Hide guide
                      </button>
                    )}
                  </div>
                  <div className="a-setup__bar" aria-hidden>
                    <span style={{ width: `${(doneCount / steps.length) * 100}%` }} />
                  </div>
                  <ol className="a-steps">
                    {steps.map((s, i) => {
                      const done = isDone(s.key)
                      const skipped = !done && proto.skipped.includes(s.key)
                      return (
                        <li key={s.key} className={`a-step ${done ? 'is-done' : ''} ${skipped ? 'is-skipped' : ''}`}>
                          <span className="a-step__mark">{done ? CHECK : String(i + 1).padStart(2, '0')}</span>
                          <div className="a-step__text">
                            <h3>
                              {s.title}
                              {s.required && !done && <span className="a-step__tag">Needed to publish</span>}
                              {skipped && <span className="a-step__tag a-step__tag--muted">Skipped</span>}
                            </h3>
                            <p>{s.body}</p>
                          </div>
                          {!done && (
                            <div className="a-step__actions">
                              <Link to={s.to} className="a-btn a-btn--primary a-btn--sm">
                                {s.cta}
                              </Link>
                              {skipped ? (
                                <button type="button" className="a-link a-link--muted" onClick={() => resumeStep(s.key)}>
                                  Undo skip
                                </button>
                              ) : (
                                <button type="button" className="a-link a-link--muted" onClick={() => skipStep(s.key)}>
                                  Skip
                                </button>
                              )}
                            </div>
                          )}
                        </li>
                      )
                    })}
                  </ol>
                </section>
              )}

              {styleIsSuggestion && (
                <section className="a-card a-suggest">
                  <p className="a-eyebrow">Suggestion</p>
                  <h2 className="a-card__title">Make it yours: choose a style.</h2>
                  <p className="a-muted">Your site is live with the default Noir style. Pick a preset that matches your brand.</p>
                  <Link to="/studio/settings" className="a-btn a-btn--ghost a-btn--sm">
                    Browse styles
                  </Link>
                </section>
              )}
            </div>

            <aside className="a-overview__side">
              <Link to="/studio/listings" className="a-stat">
                <span>Listings</span>
                <strong>{listings === null ? '—' : listings.length}</strong>
                <small>{published} published</small>
              </Link>
              <Link to="/studio/enquiries" className="a-stat">
                <span>New enquiries</span>
                <strong>{newEnquiries}</strong>
                <small>Every lead goes straight to you</small>
              </Link>
              <Link to="/studio/analytics" className="a-stat">
                <span>Visitors · 30 days</span>
                <strong>{stats ? fmtInt(stats.totals.visitors) : '—'}</strong>
                <small>{stats ? `${fmtInt(stats.totals.views)} views · ${fmtPct(stats.walkthrough.finishRate)} watched to the end` : 'Open analytics'}</small>
              </Link>
            </aside>
          </div>
        </>
      )}

      {confirming && (
        <ComplianceDialog
          country={countryInfo(proto.country).name}
          onCancel={() => setConfirming(false)}
          onConfirm={() => {
            setConfirming(false)
            setProto({ sitePublished: true, complianceAck: true })
            toast('Your site is live')
          }}
        />
      )}
    </div>
  )
}

function FreeOverview({ hasListing, previewHref }: { hasListing: boolean; previewHref: string | null }) {
  return (
    <>
      <section className="a-sitecard a-sitecard--free">
        <div className="a-sitecard__main">
          <span className="a-sitecard__status">Free preview</span>
          <h2 className="a-sitecard__title">See YE work on one of your own homes.</h2>
          <p className="a-muted">
            Build one listing with a walkthrough. Only you can see it. When you are happy, subscribe to publish it and set up your
            brand.
          </p>
        </div>
        <div className="a-sitecard__actions">
          {hasListing && previewHref ? (
            <a href={previewHref} target="_blank" rel="noreferrer" className="a-btn a-btn--ghost">
              Preview your listing ↗
            </a>
          ) : null}
          <Link to="/studio/plan" className="a-btn a-btn--primary">
            See plans
          </Link>
        </div>
      </section>

      <section className="a-card a-setup">
        <p className="a-eyebrow">Your free preview</p>
        <ol className="a-steps">
          <li className={`a-step ${hasListing ? 'is-done' : ''}`}>
            <span className="a-step__mark">{hasListing ? CHECK : '01'}</span>
            <div className="a-step__text">
              <h3>Create your listing</h3>
              <p>Add the basics and upload your walkthrough video. It is processed in the background.</p>
            </div>
            {!hasListing && (
              <div className="a-step__actions">
                <Link to="/studio/listings/new" className="a-btn a-btn--primary a-btn--sm">
                  Create listing
                </Link>
              </div>
            )}
          </li>
          <li className="a-step">
            <span className="a-step__mark">02</span>
            <div className="a-step__text">
              <h3>Walk through it yourself</h3>
              <p>Open the private preview on your phone and laptop. It is not shareable and not indexed by search engines.</p>
            </div>
          </li>
          <li className="a-step">
            <span className="a-step__mark">03</span>
            <div className="a-step__text">
              <h3>Subscribe to publish</h3>
              <p>Your listing carries over. Then set up your brand and your website.</p>
            </div>
            <div className="a-step__actions">
              <Link to="/studio/plan" className="a-btn a-btn--ghost a-btn--sm">
                See plans
              </Link>
            </div>
          </li>
        </ol>
      </section>
    </>
  )
}

function ComplianceDialog({ country, onCancel, onConfirm }: { country: string; onCancel: () => void; onConfirm: () => void }) {
  const [agreed, setAgreed] = useState(false)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onCancel()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onCancel])

  return (
    <div className="a-dialog" role="dialog" aria-modal="true" aria-labelledby="compliance-title" onClick={onCancel}>
      <div className="a-dialog__panel" onClick={(e) => e.stopPropagation()}>
        <p className="a-eyebrow">Before you go live</p>
        <h2 id="compliance-title" className="a-card__title">
          Make sure your site follows your local rules.
        </h2>
        <p className="a-muted">
          Real estate advertising rules differ by country and region ({country}). Some require a licence or registration number, your
          brokerage name, or a permit number on each listing. You are responsible for what your site shows.
        </p>
        <label className="a-check">
          <input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} />
          <span>I understand, and my site meets the rules that apply to me.</span>
        </label>
        <div className="a-form__actions">
          <button type="button" className="a-btn a-btn--primary" disabled={!agreed} onClick={onConfirm}>
            Publish site
          </button>
          <button type="button" className="a-btn a-btn--ghost" onClick={onCancel}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  )
}

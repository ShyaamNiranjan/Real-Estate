'use client'

import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import { useEffect, useState, type CSSProperties } from 'react'
import { CHECK, CountUp } from '@/components/studio/ui'
import { useWorkspace, type Workspace } from '@/lib/studio'
import { STEP_TITLES, SetupGuide, guideSteps, nextStep } from './SetupGuide'

const STEP_BODY = {
  about_you: 'Your name, brokerage, country details and your scrollwalk.com link.',
  contact: 'Email, phone, WhatsApp or a booking link. At least one is needed to publish.',
  style: 'Pick a style preset. Skipped, your site uses Noir.',
  team: 'Add agents who publish listings under your brand.',
} as const

const ASKED_KEY = 'sw_username_asked'

function greeting() {
  const h = new Date().getHours()
  return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening'
}

/** A skipped About-you tile with no username comes back once per sign-in session. */
function usernameReprompt(ws: Workspace) {
  if (!ws.can_claim_username || ws.username || ws.setup.about_you !== 'skipped') return false
  try {
    return sessionStorage.getItem(ASKED_KEY) !== ws.id
  } catch {
    return false
  }
}

export function StudioIndex() {
  const { workspace, teamPlan, can } = useWorkspace()
  const params = useSearchParams()
  const canSetup = can('site.edit_brand')
  const [reprompt] = useState(() => usernameReprompt(workspace))
  const wantsDashboard = params.get('dashboard') === '1'

  useEffect(() => {
    if (!reprompt) return
    try {
      sessionStorage.setItem(ASKED_KEY, workspace.id)
    } catch {}
  }, [reprompt, workspace.id])

  if (canSetup && !wantsDashboard && (nextStep(workspace, teamPlan) || reprompt))
    return <SetupGuide start={reprompt ? 'about_you' : null} />
  return <Dashboard />
}

function hideKey(ws: Workspace) {
  return `sw_hide_guide_${ws.id}`
}

function Dashboard() {
  const { workspace: ws, teamPlan, can, me } = useWorkspace()
  const canSetup = can('site.edit_brand')
  const steps = guideSteps(teamPlan)
  const done = steps.filter((s) => ws.setup[s] === 'done').length
  const canPublish = ws.publish_blockers.length === 0
  const [hidden, setHidden] = useState(() => {
    try {
      return localStorage.getItem(hideKey(ws)) === '1'
    } catch {
      return false
    }
  })
  const showGuide = canSetup && !(hidden && canPublish)
  const name = (me.user.display_name || ws.display_name).split(' ')[0]
  const live = ws.site_state === 'live'
  const today = new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })

  const setHide = (value: boolean) => {
    setHidden(value)
    try {
      if (value) localStorage.setItem(hideKey(ws), '1')
      else localStorage.removeItem(hideKey(ws))
    } catch {}
  }

  return (
    <div className="a-page">
      <header className="a-page__head a-hello">
        <div>
          <p className="a-eyebrow">
            {ws.display_name} · {today}
          </p>
          <h1 className="a-title">
            {greeting()}
            {name ? `, ${name}` : ''}.
          </h1>
        </div>
      </header>

      <section className={`a-sitecard ${live ? 'is-live' : ''}`} aria-labelledby="site-title">
        <div className="a-sitecard__main">
          <span className={`a-sitecard__status ${live ? 'is-live' : ''}`}>
            {live ? 'Live' : ws.site_state === 'offline' ? 'Offline' : 'Draft · only you can see it'}
          </span>
          <h2 id="site-title" className="a-sitecard__title">
            {live ? 'Your website is live.' : ws.site_state === 'offline' ? 'Your website is offline.' : 'Your website is a draft.'}
          </h2>
          {ws.username ? (
            <p className="a-sitecard__url">
              <code>scrollwalk.com/{ws.username}</code>
            </p>
          ) : (
            <p className="a-muted">Your scrollwalk.com link is set in About you.</p>
          )}
          {live && ws.site_has_unpublished_changes && <p className="a-sitecard__need">You have changes that aren’t live yet.</p>}
        </div>
        <div className="a-sitecard__actions">
          <Link href="/studio/listings" className="a-btn a-btn--primary">
            Create your first listing
          </Link>
        </div>
      </section>

      <div className="a-overview">
        <div className="a-overview__main">
          {canSetup && !showGuide && (
            <button type="button" className="a-link" onClick={() => setHide(false)}>
              Show setup guide
            </button>
          )}
          {showGuide && (
            <section className="a-card a-setup" aria-labelledby="setup-title">
              <div className="a-setup__head">
                <div>
                  <p className="a-eyebrow">Set up</p>
                  <h2 id="setup-title" className="a-card__title">
                    <CountUp value={done} /> of {steps.length} done
                  </h2>
                </div>
                {canPublish && (
                  <button type="button" className="a-link a-link--muted" onClick={() => setHide(true)}>
                    Hide setup guide
                  </button>
                )}
              </div>
              <div className="a-setup__bar" aria-hidden>
                <span style={{ width: `${(done / steps.length) * 100}%` }} />
              </div>
              <ol className="a-steps">
                {steps.map((s, i) => {
                  const state = ws.setup[s]
                  const isDone = state === 'done'
                  const usernameMissing = s === 'about_you' && ws.can_claim_username && !ws.username
                  return (
                    <li key={s} className={`a-step ${isDone && !usernameMissing ? 'is-done' : ''} ${state === 'skipped' ? 'is-skipped' : ''}`}>
                      <span className="a-step__mark">{isDone && !usernameMissing ? CHECK : String(i + 1).padStart(2, '0')}</span>
                      <div className="a-step__text">
                        <h3>
                          {STEP_TITLES[s]}
                          {usernameMissing && <span className="a-step__tag">Choose your link</span>}
                          {state === 'skipped' && <span className="a-step__tag a-step__tag--muted">Skipped</span>}
                          {isDone && <span className="visually-hidden"> (done)</span>}
                        </h3>
                        <p>{STEP_BODY[s]}</p>
                      </div>
                      <div className="a-step__actions">
                        <Link href={`/studio/setup?step=${s}`} className={`a-btn a-btn--sm ${isDone ? 'a-btn--ghost' : 'a-btn--primary'}`}>
                          {isDone ? 'Edit' : 'Set up'}
                          <span className="visually-hidden"> {STEP_TITLES[s]}</span>
                        </Link>
                      </div>
                    </li>
                  )
                })}
              </ol>
            </section>
          )}

          <section className="a-card" aria-labelledby="publish-title">
            <p className="a-eyebrow">Before you publish</p>
            <h2 id="publish-title" className="a-card__title">
              {canPublish ? 'Everything needed to publish is in place.' : 'Still needed to publish'}
            </h2>
            {canPublish ? (
              <p className="a-muted">Publishing your website is coming to the Studio soon.</p>
            ) : (
              <ul className="a-list" style={{ marginTop: '0.8rem' }}>
                {ws.publish_blockers.map((b, i) => (
                  <li key={b.code} style={{ '--i': i } as CSSProperties}>
                    <span>{b.message}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>

        <aside className="a-overview__side">
          <section className="a-card">
            <p className="a-eyebrow">Your listings</p>
            <h2 className="a-card__title">Every home gets its own walkthrough page.</h2>
            <p className="a-muted">Upload a phone video of the home and Scrollwalk turns it into a scroll-controlled walkthrough.</p>
            <div className="a-actions">
              <Link href="/studio/listings" className="a-btn a-btn--ghost a-btn--sm">
                Go to listings
              </Link>
            </div>
          </section>
        </aside>
      </div>
    </div>
  )
}

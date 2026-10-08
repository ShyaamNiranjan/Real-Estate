import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '../lib/auth'
import { COUNTRIES, planName, resetProto, setProto, useProto, type Plan } from '../lib/prototype'
import { useRealtor } from '../lib/realtor'
import { useSite } from '../lib/site'
import { countNewEnquiries } from './api'

const LOCK = (
  <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
    <rect x="5" y="11" width="14" height="9" rx="1.5" />
    <path d="M8 11V8a4 4 0 0 1 8 0v3" />
  </svg>
)

export function AdminLayout() {
  const { settings } = useSite()
  const { profile, signOut } = useAuth()
  const { base } = useRealtor()
  const proto = useProto()
  const location = useLocation()
  const [newCount, setNewCount] = useState(0)
  const [navOpen, setNavOpen] = useState(false)
  const free = proto.plan === 'free'
  const teamPlan = proto.plan === 'team' || proto.plan === 'brokerage'

  const navRef = useRef<HTMLElement>(null)
  const section = location.pathname.split('/')[2] ?? ''

  useEffect(() => {
    countNewEnquiries().then(setNewCount).catch(() => {})
    setNavOpen(false)
  }, [location.pathname])

  useLayoutEffect(() => {
    const nav = navRef.current
    if (!nav) return
    const place = () => {
      const active = nav.querySelector<HTMLElement>('.a-side__link.active')
      nav.style.setProperty('--ind-y', `${active?.offsetTop ?? 0}px`)
      nav.style.setProperty('--ind-h', `${active?.offsetHeight ?? 0}px`)
      nav.classList.toggle('has-active', Boolean(active))
    }
    place()
    window.addEventListener('resize', place)
    return () => window.removeEventListener('resize', place)
  }, [section, free, teamPlan])

  return (
    <div className={`a-shell ${navOpen ? 'nav-open' : ''}`}>
      <aside className="a-side">
        <div className="a-side__top">
          <NavLink to="/studio" end className="a-side__brand" aria-label="YE Studio">
            <span>YE</span>
            <small>Studio</small>
          </NavLink>
          <button
            type="button"
            className="a-side__toggle"
            aria-expanded={navOpen}
            aria-label="Toggle navigation"
            onClick={() => setNavOpen((v) => !v)}
          >
            <span />
            <span />
          </button>
        </div>

        <div className="a-side__workspace">
          <p>{settings.brand_name}</p>
          <span className={`a-plan a-plan--${proto.plan}`}>{planName(proto.plan)}</span>
        </div>

        <nav className="a-side__nav" aria-label="Studio" ref={navRef}>
          <NavLink to="/studio" end className="a-side__link">
            Overview
          </NavLink>
          <NavLink to="/studio/listings" className="a-side__link">
            Listings
          </NavLink>
          <NavLink to="/studio/analytics" className="a-side__link">
            Analytics
          </NavLink>
          <NavLink to="/studio/home" className={`a-side__link ${free ? 'is-locked' : ''}`}>
            Website {free && LOCK}
          </NavLink>
          <NavLink to="/studio/settings" className={`a-side__link ${free ? 'is-locked' : ''}`}>
            Brand &amp; contact {free && LOCK}
          </NavLink>
          <NavLink to="/studio/enquiries" className="a-side__link">
            Enquiries
            {newCount > 0 && <span className="a-side__count">{newCount}</span>}
          </NavLink>
          <NavLink to="/studio/team" className={`a-side__link ${teamPlan ? '' : 'is-locked'}`}>
            Team {!teamPlan && LOCK}
          </NavLink>
          <NavLink to="/studio/plan" className="a-side__link">
            Plan
          </NavLink>
          {!free && (
            <a href={base} target="_blank" rel="noreferrer" className="a-side__link a-side__link--muted">
              View site ↗
            </a>
          )}
        </nav>

        <div className="a-side__proto">
          <p className="a-side__proto-label">Prototype controls</p>
          <label>
            <span>Plan</span>
            <select value={proto.plan} onChange={(e) => setProto({ plan: e.target.value as Plan })}>
              <option value="free">Free preview</option>
              <option value="agent">Agent</option>
              <option value="team">Team</option>
              <option value="brokerage">Brokerage</option>
            </select>
          </label>
          <label>
            <span>Country</span>
            <select value={proto.country} onChange={(e) => setProto({ country: e.target.value })}>
              {COUNTRIES.map((c) => (
                <option key={c.code} value={c.code}>
                  {c.name}
                </option>
              ))}
            </select>
          </label>
          <button type="button" onClick={() => resetProto({ plan: proto.plan, country: proto.country, ownerName: proto.ownerName })}>
            Reset setup progress
          </button>
        </div>

        <div className="a-side__foot">
          <p className="a-side__user" title={profile?.email ?? ''}>
            {proto.ownerName || profile?.full_name || profile?.email}
          </p>
          <button type="button" className="a-side__signout" onClick={() => void signOut()}>
            Sign out
          </button>
        </div>
      </aside>

      <main className="a-main">
        <div className="a-route" key={section}>
          <Outlet />
        </div>
      </main>
    </div>
  )
}

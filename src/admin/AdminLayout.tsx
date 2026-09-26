import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '../lib/auth'
import { useSite } from '../lib/site'
import { countNewEnquiries } from './api'

export function AdminLayout() {
  const { settings } = useSite()
  const { profile, signOut } = useAuth()
  const location = useLocation()
  const [newCount, setNewCount] = useState(0)
  const [navOpen, setNavOpen] = useState(false)

  useEffect(() => {
    countNewEnquiries().then(setNewCount).catch(() => {})
    setNavOpen(false)
  }, [location.pathname])

  return (
    <div className={`a-shell ${navOpen ? 'nav-open' : ''}`}>
      <aside className="a-side">
        <div className="a-side__top">
          <NavLink to="/admin" end className="a-side__brand">
            <span>{settings.brand_name}</span>
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

        <nav className="a-side__nav" aria-label="Admin">
          <NavLink to="/admin" end className="a-side__link">
            Listings
          </NavLink>
          <NavLink to="/admin/enquiries" className="a-side__link">
            Enquiries
            {newCount > 0 && <span className="a-side__count">{newCount}</span>}
          </NavLink>
          <NavLink to="/admin/settings" className="a-side__link">
            Site settings
          </NavLink>
          <a href="/" target="_blank" rel="noreferrer" className="a-side__link a-side__link--muted">
            View site ↗
          </a>
        </nav>

        <div className="a-side__foot">
          <p className="a-side__user" title={profile?.email ?? ''}>
            {profile?.full_name || profile?.email}
          </p>
          <button type="button" className="a-side__signout" onClick={() => void signOut()}>
            Sign out
          </button>
        </div>
      </aside>

      <main className="a-main">
        <Outlet />
      </main>
    </div>
  )
}

'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'
import { useSession } from '@/lib/session'
import { YeMark } from './chrome'

export function SiteNav() {
  const { status } = useSession()
  const [scrolled, setScrolled] = useState(false)

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 24)
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  return (
    <header className={`ye-nav ${scrolled ? 'is-scrolled' : ''}`}>
      <div className="ye-nav__inner">
        <Link href="/" className="ye-nav__brand" aria-label="Scrollwalk home">
          <YeMark />
        </Link>
        <nav className="ye-nav__links" aria-label="Main">
          <a href="#how">How it works</a>
          <a href="#features">Features</a>
          <a href="#pricing">Pricing</a>
          <a href="#waitlist">Waitlist</a>
        </nav>
        <div className="ye-nav__actions">
          {status === 'signed-in' ? (
            <Link href="/studio" className="ye-btn ye-btn--primary ye-btn--sm">
              Open Studio
            </Link>
          ) : (
            <>
              <Link href="/login" className="ye-nav__signin">
                Sign in
              </Link>
              <Link href="/signup?plan=agent" className="ye-btn ye-btn--primary ye-btn--sm">
                Get started
              </Link>
            </>
          )}
        </div>
      </div>
    </header>
  )
}

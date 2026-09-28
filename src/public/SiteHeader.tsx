import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { brandParts, useSite } from '../lib/site'
import { scrollToAnchor } from './links'

type Props = {
  variant: 'home' | 'listing'
  onEnquire?: () => void
}

export function SiteHeader({ variant, onEnquire }: Props) {
  const { settings } = useSite()
  const { name, sub } = brandParts(settings.brand_name)
  const [solid, setSolid] = useState(false)

  useEffect(() => {
    // On listings the fixed walkthrough owns the first screens; only go solid once past it.
    const threshold = () => (variant === 'home' ? window.innerHeight * 0.85 : window.innerHeight * 0.6)
    let raf = 0
    const check = () => {
      raf = 0
      const past = window.scrollY > threshold()
      const stage = document.querySelector('.scroll-stage')
      const onStage = stage ? !stage.classList.contains('is-complete') : false
      setSolid(past && !onStage)
    }
    const onScroll = () => {
      if (!raf) raf = requestAnimationFrame(check)
    }
    check()
    window.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('resize', onScroll, { passive: true })
    return () => {
      window.removeEventListener('scroll', onScroll)
      window.removeEventListener('resize', onScroll)
      if (raf) cancelAnimationFrame(raf)
    }
  }, [variant])

  const enquire = () => {
    if (onEnquire) return onEnquire()
    // The enquiry section can be hidden in the Studio; the footer still has the contact details.
    if (!scrollToAnchor('enquire')) scrollToAnchor('site-footer')
  }

  return (
    <header className={`site-header site-header--${variant} ${solid ? 'is-solid' : ''}`}>
      {variant === 'home' ? (
        <Link to="/" className="wordmark" aria-label={`${settings.brand_name} home`}>
          <span className="wordmark__name">{name}</span>
          {sub && <span className="wordmark__sub">{sub}</span>}
        </Link>
      ) : (
        <Link to="/" className="site-header__back" viewTransition>
          <span className="arrow arrow--left" aria-hidden />
          <span>The collection</span>
        </Link>
      )}

      <nav className="site-header__nav" aria-label="Primary">
        {variant === 'home' && (
          <a
            href="#collection"
            className="site-header__link"
            onClick={(e) => {
              e.preventDefault()
              scrollToAnchor('collection')
            }}
          >
            Collection
          </a>
        )}
        <button type="button" className="site-header__link" onClick={enquire}>
          Enquire
        </button>
      </nav>
    </header>
  )
}

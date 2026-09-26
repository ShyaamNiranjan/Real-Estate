import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useSite } from '../lib/site'

type Props = {
  variant: 'home' | 'listing'
  onEnquire?: () => void
}

export function SiteHeader({ variant, onEnquire }: Props) {
  const { settings } = useSite()
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
    document.getElementById('enquire')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  return (
    <header className={`site-header site-header--${variant} ${solid ? 'is-solid' : ''}`}>
      {variant === 'home' ? (
        <Link to="/" className="wordmark" aria-label={`${settings.brand_name} home`}>
          <span className="wordmark__name">{settings.brand_name}</span>
          <span className="wordmark__by">by YNIIDI</span>
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
              document.getElementById('collection')?.scrollIntoView({ behavior: 'smooth' })
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

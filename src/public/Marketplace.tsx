import { useEffect, useMemo, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { fetchHomeSections, fetchPublishedListings, homeCache, type ListingCard } from '../lib/api'
import { brandParts, useDocumentTitle, useSite } from '../lib/site'
import type { HomeSectionRow } from '../types/database'
import { BrandIntro, introPending } from './BrandIntro'
import { FALLBACK_SECTIONS, HomeSections, LOADING_SECTIONS } from './HomeSections'
import { scrollToAnchor } from './links'
import { SiteFooter } from './SiteFooter'
import { SiteHeader } from './SiteHeader'

export function Marketplace() {
  useDocumentTitle(null)
  const { settings } = useSite()
  const location = useLocation()
  const [listings, setListings] = useState<ListingCard[] | null>(homeCache.listings)
  const [failed, setFailed] = useState(false)
  const [sections, setSections] = useState<HomeSectionRow[] | null>(homeCache.sections)
  const [withIntro] = useState(introPending)
  const [introMounted, setIntroMounted] = useState(withIntro)
  const [heroHeld, setHeroHeld] = useState(withIntro)

  useEffect(() => {
    let active = true
    fetchPublishedListings()
      .then((rows) => active && setListings(rows))
      .catch((err) => {
        console.error(err)
        if (active) {
          setFailed(true)
          setListings([])
        }
      })
    fetchHomeSections()
      .then((rows) => active && setSections(rows))
      .catch((err) => {
        console.error(err)
        if (active) setSections(FALLBACK_SECTIONS)
      })
    return () => {
      active = false
    }
  }, [])

  // Links like /#services from other pages land once the sections exist.
  const landedKey = useRef<string | null>(null)
  useEffect(() => {
    const id = decodeURIComponent(location.hash.slice(1))
    if (!id || !sections || landedKey.current === location.key) return
    const el = document.getElementById(id)
    if (!el) return
    landedKey.current = location.key
    requestAnimationFrame(() => el.scrollIntoView({ block: 'start' }))
  }, [location.hash, location.key, sections])

  const heroImage = settings.hero_image_url ?? '/media/sequence/frame-001.jpg'
  const preload = useMemo(
    () => (listings ?? []).slice(0, 2).flatMap((l) => (l.cover_image_url ? [l.cover_image_url] : [])),
    [listings],
  )
  const { name, sub } = brandParts(settings.brand_name)

  return (
    <div className="page page--home">
      {introMounted && (
        <BrandIntro
          name={name}
          sub={sub}
          heroSrc={heroImage}
          preload={preload}
          onLift={() => setHeroHeld(false)}
          onDone={() => setIntroMounted(false)}
        />
      )}
      <SiteHeader variant="home" />
      <Hero
        brand={settings.brand_name}
        headline={settings.hero_headline ?? ''}
        body={settings.hero_body ?? ''}
        image={heroImage}
        cta={settings.hero_cta_label ?? 'View the collection'}
        afterIntro={withIntro}
        held={heroHeld}
      />
      <HomeSections sections={sections ?? LOADING_SECTIONS} listings={listings} failed={failed} />
      <SiteFooter presets={sections ? sections.map((s) => s.preset) : undefined} />
    </div>
  )
}

function Hero(props: {
  brand: string
  headline: string
  body: string
  image: string
  cta: string
  /** The brand intro played: the photograph settles by scale alone as the curtain lifts. */
  afterIntro: boolean
  /** Entrance animations wait while the intro covers the page. */
  held: boolean
}) {
  const mediaRef = useRef<HTMLDivElement>(null)
  const { name, sub } = brandParts(props.brand)
  const lead = props.afterIntro ? 0.2 : 0.25

  // Scroll polish: the photograph drifts slower than the page as you leave the hero.
  useEffect(() => {
    const el = mediaRef.current
    if (!el || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    let raf = 0
    const update = () => {
      raf = 0
      const y = Math.min(window.scrollY, window.innerHeight * 1.2)
      el.style.transform = `translate3d(0, ${y * 0.28}px, 0)`
    }
    const onScroll = () => {
      if (!raf) raf = requestAnimationFrame(update)
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => {
      window.removeEventListener('scroll', onScroll)
      if (raf) cancelAnimationFrame(raf)
    }
  }, [])

  return (
    <section
      className={`hero ${props.afterIntro ? 'hero--after-intro' : ''} ${props.held ? 'is-held' : ''}`}
      aria-labelledby="hero-title"
    >
      <div className="hero__media" ref={mediaRef} aria-hidden>
        <img src={props.image} alt="" fetchPriority="high" decoding="async" />
      </div>
      <div className="hero__veil" aria-hidden />
      <div className="hero__grain" aria-hidden />

      <div className="hero__content">
        <p className="hero__brand" aria-label={props.brand}>
          {name.split('').map((ch, i) => (
            <span key={i} className="hero__letter" style={{ animationDelay: `${lead + i * 0.06}s` }} aria-hidden>
              {ch}
            </span>
          ))}
          {sub && (
            <span className="hero__brand-sub" style={{ animationDelay: `${lead + name.length * 0.06 + 0.3}s` }} aria-hidden>
              {sub}
            </span>
          )}
        </p>
        <div className="hero__copy">
          <h1 id="hero-title" className="hero__headline">
            {props.headline}
          </h1>
          <p className="hero__body">{props.body}</p>
          <a
            href="#collection"
            className="hero__cta"
            onClick={(e) => {
              e.preventDefault()
              scrollToAnchor('collection')
            }}
          >
            <span>{props.cta}</span>
            <span className="arrow arrow--down" aria-hidden />
          </a>
        </div>
      </div>
    </section>
  )
}

import { useCallback, useEffect, useRef, useState, type CSSProperties } from 'react'
import { listingFacts } from '../lib/format'
import type { HeroSettings } from '../lib/listingHero'
import type { ListingRow } from '../types/database'
import '../styles/experience.css'
import '../styles/hero.css'

export type HeroPhase = 'hero' | 'leaving' | 'gone' | 'returning'

export type HeroContent = {
  eyebrow: string | null
  title: string
  tagline: string | null
  facts: string[]
  price: string | null
}

/** Mirrored in the lhero* keyframe durations. */
export const LEAVE_MS = 1800
export const RETURN_MS = 1500
const REDUCED_MS = 380
/** Trackpad momentum keeps firing after a transition; ignore it this long before reversing. */
const COOLDOWN_MS = 500

type HeroSource = Pick<ListingRow, 'location' | 'title' | 'subtitle' | 'bedrooms' | 'bathrooms' | 'area_sqft' | 'price_label'>

export function heroContent(listing: HeroSource, settings: HeroSettings): HeroContent {
  return {
    eyebrow: listing.location,
    title: listing.title,
    tagline: listing.subtitle,
    facts: settings.showFacts ? listingFacts(listing) : [],
    price: settings.showPrice ? listing.price_label : null,
  }
}

type BannerProps = {
  content: HeroContent
  image: string
  frame: { src: string; fills: boolean } | null
  phase: HeroPhase
  /** The opening entrance plays once; coming back from the walkthrough uses the return animation instead. */
  first: boolean
  onEnter?: () => void
  /** Editor preview: sized by its frame instead of the viewport, with a stand-in site header. */
  preview?: { brand: string }
}

export function HeroBanner({ content, image, frame, phase, first, onEnter, preview }: BannerProps) {
  const cls = [
    'lhero',
    `is-${phase}`,
    first && phase === 'hero' ? 'is-first' : '',
    preview ? 'lhero--preview' : '',
    frame && !frame.fills ? 'is-letterboxed' : '',
  ]
    .filter(Boolean)
    .join(' ')
  const at = (i: number) => ({ '--i': i }) as CSSProperties

  return (
    <section className={cls} aria-label={`${content.title} cover`} aria-hidden={phase === 'gone' && !preview}>
      {frame && (
        <div className="lhero__frame" aria-hidden>
          <img src={frame.src} alt="" decoding="async" />
          <div className="scroll-veil" />
        </div>
      )}

      <div className="lhero__scene">
        <img className="lhero__img" src={image} alt="" decoding="async" fetchPriority="high" />
        <div className="lhero__veil" aria-hidden />

        {preview && (
          <div className="lhero__mockbar" aria-hidden>
            <span>{preview.brand}</span>
            <span>Enquire</span>
          </div>
        )}

        <div className="lhero__content">
          <span className="lhero__rule lhero__in" style={at(0)} aria-hidden />
          {content.eyebrow && (
            <p className="lhero__eyebrow lhero__in" style={at(0)}>
              {content.eyebrow}
            </p>
          )}
          <h1 className="lhero__title lhero__in" style={at(1)}>
            {content.title}
          </h1>
          {content.tagline && (
            <p className="lhero__tagline lhero__in" style={at(2)}>
              {content.tagline}
            </p>
          )}
          {(content.facts.length > 0 || content.price) && (
            <div className="lhero__meta lhero__in" style={at(3)}>
              {content.facts.length > 0 && (
                <ul className="lhero__facts">
                  {content.facts.map((f) => (
                    <li key={f}>{f}</li>
                  ))}
                </ul>
              )}
              {content.price && (
                <p className="lhero__price">
                  <span>Guide</span>
                  <strong>{content.price}</strong>
                </p>
              )}
            </div>
          )}
        </div>

        <button type="button" className="lhero__hint" onClick={onEnter} tabIndex={preview ? -1 : 0}>
          <span>Scroll to step inside</span>
          <span className="lhero__hint-line" aria-hidden />
        </button>
      </div>

      <div className="lhero__bar lhero__bar--top" aria-hidden />
      <div className="lhero__bar lhero__bar--bottom" aria-hidden />
      <div className="lhero__seam" aria-hidden />
    </section>
  )
}

const DOWN_KEYS = new Set(['ArrowDown', 'PageDown', ' ', 'Spacebar', 'End'])
const UP_KEYS = new Set(['ArrowUp', 'PageUp', 'Home'])

function isTyping(target: EventTarget | null) {
  const el = target as HTMLElement | null
  return Boolean(el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName)))
}

/**
 * The banner sits in front of the walkthrough's first frame. The first scroll plays the cut into
 * the walkthrough instead of moving the page; scrolling up at the very start plays it back.
 */
export function useHeroCurtain(active: boolean) {
  const [phase, setPhase] = useState<HeroPhase>(() => (active && window.scrollY < 4 ? 'hero' : 'gone'))
  const [first, setFirst] = useState(true)
  const phaseRef = useRef(phase)
  const readyAt = useRef(0)
  const timer = useRef(0)

  const move = useCallback((to: 'leaving' | 'returning') => {
    if (performance.now() < readyAt.current) return
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (to === 'returning') window.scrollTo(0, 0)
    setFirst(false)
    phaseRef.current = to
    setPhase(to)
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(
      () => {
        const next = to === 'leaving' ? 'gone' : 'hero'
        phaseRef.current = next
        setPhase(next)
        readyAt.current = performance.now() + COOLDOWN_MS
      },
      reduced ? REDUCED_MS : to === 'leaving' ? LEAVE_MS : RETURN_MS,
    )
  }, [])

  // Lets the walkthrough's opening line time its entrance to the moment the cut lands.
  useEffect(() => {
    if (!active) return
    document.documentElement.dataset.hero = phase
    return () => {
      delete document.documentElement.dataset.hero
    }
  }, [active, phase])

  useEffect(() => {
    if (!active) return
    const atTop = () => window.scrollY <= 2
    const busy = () => phaseRef.current === 'leaving' || phaseRef.current === 'returning'

    const onWheel = (e: WheelEvent) => {
      if (busy()) return e.preventDefault()
      if (phaseRef.current === 'hero') {
        e.preventDefault()
        if (e.deltaY > 2) move('leaving')
      } else if (atTop() && e.deltaY < -2) {
        e.preventDefault()
        move('returning')
      }
    }

    let startY = 0
    let startedAtTop = false
    const onTouchStart = (e: TouchEvent) => {
      startY = e.touches[0]?.clientY ?? 0
      startedAtTop = atTop()
    }
    const onTouchMove = (e: TouchEvent) => {
      if (busy()) return e.preventDefault()
      const dy = (e.touches[0]?.clientY ?? startY) - startY
      if (phaseRef.current === 'hero') {
        e.preventDefault()
        if (dy < -10) move('leaving')
      } else if (startedAtTop && atTop() && dy > 14) {
        e.preventDefault()
        move('returning')
      }
    }

    const onKey = (e: KeyboardEvent) => {
      if (isTyping(e.target) || e.metaKey || e.ctrlKey || e.altKey) return
      if (busy()) {
        if (DOWN_KEYS.has(e.key) || UP_KEYS.has(e.key)) e.preventDefault()
        return
      }
      if (phaseRef.current === 'hero' && DOWN_KEYS.has(e.key)) {
        e.preventDefault()
        move('leaving')
      } else if (phaseRef.current === 'gone' && atTop() && UP_KEYS.has(e.key)) {
        e.preventDefault()
        move('returning')
      }
    }

    // Dragging the scrollbar or jumping to an anchor skips the banner rather than fighting it.
    const onScroll = () => {
      if (phaseRef.current === 'hero' && window.scrollY > 4) {
        phaseRef.current = 'gone'
        setPhase('gone')
        setFirst(false)
      }
    }

    window.addEventListener('wheel', onWheel, { passive: false })
    window.addEventListener('touchstart', onTouchStart, { passive: true })
    window.addEventListener('touchmove', onTouchMove, { passive: false })
    window.addEventListener('keydown', onKey)
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => {
      window.removeEventListener('wheel', onWheel)
      window.removeEventListener('touchstart', onTouchStart)
      window.removeEventListener('touchmove', onTouchMove)
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('scroll', onScroll)
      window.clearTimeout(timer.current)
    }
  }, [active, move])

  return { phase, first, enter: useCallback(() => move('leaving'), [move]) }
}

/** Editor preview: plays the cut into the first frame, holds, then plays it back. */
export function usePreviewCurtain() {
  const [phase, setPhase] = useState<HeroPhase>('hero')
  const [first, setFirst] = useState(true)
  const timers = useRef<number[]>([])
  useEffect(() => () => timers.current.forEach((t) => window.clearTimeout(t)), [])

  const play = useCallback(() => {
    timers.current.forEach((t) => window.clearTimeout(t))
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const leave = reduced ? REDUCED_MS : LEAVE_MS
    const back = reduced ? REDUCED_MS : RETURN_MS
    const hold = 1400
    setFirst(false)
    setPhase('leaving')
    timers.current = [
      window.setTimeout(() => setPhase('gone'), leave),
      window.setTimeout(() => setPhase('returning'), leave + hold),
      window.setTimeout(() => setPhase('hero'), leave + hold + back),
    ]
  }, [])

  const replayEntrance = useCallback(() => {
    timers.current.forEach((t) => window.clearTimeout(t))
    setPhase('hero')
    setFirst(false)
    requestAnimationFrame(() => setFirst(true))
  }, [])

  return { phase, first, play, replayEntrance, busy: phase !== 'hero' }
}

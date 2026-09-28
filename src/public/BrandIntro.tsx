import { useEffect, useRef, useState } from 'react'
import { prefersReducedMotion } from './links'

const SEEN_KEY = 'yniidi:intro-seen'
/** Earliest lift, measured from when the letters start (the hero image may still be loading). */
const LIFT_AT = 1550
/** Latest lift, however slow the hero image is. */
const LIFT_CAP = 1850
/** Must match the curtain transition in public.css. */
const LIFT_MS = 700
/** Longest wait for the display font before the letters start anyway. */
const FONT_WAIT = 450
const REDUCED = { at: 450, cap: 800, lift: 400 }

function readSeen() {
  try {
    return sessionStorage.getItem(SEEN_KEY) === '1'
  } catch {
    return true
  }
}

function writeSeen() {
  try {
    sessionStorage.setItem(SEEN_KEY, '1')
  } catch {
    /* private mode */
  }
}

/**
 * Decided once per page load: the intro greets visitors whose first page this session is the home
 * page. Deep links (a listing, the Studio, `/#services`) count as already arrived.
 */
let pending = (() => {
  if (typeof window === 'undefined') return false
  const { pathname, hash } = window.location
  const eligible = pathname === '/' && !hash && !readSeen()
  if (!eligible) writeSeen()
  return eligible
})()

export function introPending() {
  return pending
}

type Props = {
  name: string
  sub: string
  heroSrc: string
  /** Warmed during the intro so the collection tiles are ready when the visitor scrolls. */
  preload: string[]
  onLift: () => void
  onDone: () => void
}

export function BrandIntro({ name, sub, heroSrc, preload, onLift, onDone }: Props) {
  const [playing, setPlaying] = useState(false)
  const [lifting, setLifting] = useState(false)
  const latest = useRef({ heroSrc, onLift, onDone })
  latest.current = { heroSrc, onLift, onDone }

  useEffect(() => {
    pending = false
    writeSeen()
    const root = document.documentElement
    const reduced = prefersReducedMotion()
    const t = reduced ? REDUCED : { at: LIFT_AT, cap: LIFT_CAP, lift: LIFT_MS }
    const timers: number[] = []
    let cancelled = false
    let started = 0
    let heroReady = false
    let lifted = false

    root.classList.add('is-intro')
    window.scrollTo(0, 0)

    const lift = () => {
      if (lifted || cancelled) return
      lifted = true
      setLifting(true)
      latest.current.onLift()
      timers.push(
        window.setTimeout(() => {
          root.classList.remove('is-intro')
          latest.current.onDone()
        }, t.lift),
      )
    }

    const begin = () => {
      if (cancelled || started) return
      started = performance.now()
      setPlaying(true)
      timers.push(window.setTimeout(() => heroReady && lift(), t.at))
      timers.push(window.setTimeout(lift, t.cap))
    }

    const img = new Image()
    img.decoding = 'async'
    const onHero = () => {
      heroReady = true
      if (started && performance.now() - started >= t.at) lift()
    }
    img.onload = () => {
      const decoded = img.decode ? img.decode() : Promise.resolve()
      decoded.then(onHero, onHero)
    }
    img.onerror = onHero
    img.src = latest.current.heroSrc

    // Letters wait (briefly) for the display face so they never swap mid-reveal.
    const fonts = document.fonts?.load ? document.fonts.load('500 64px "Cormorant Garamond"') : Promise.resolve()
    Promise.race([fonts, new Promise((r) => window.setTimeout(r, FONT_WAIT))]).then(begin, begin)

    const skip = () => {
      begin()
      lift()
    }
    window.addEventListener('pointerdown', skip)
    window.addEventListener('keydown', skip)
    window.addEventListener('wheel', skip, { passive: true })
    window.addEventListener('touchmove', skip, { passive: true })

    return () => {
      cancelled = true
      timers.forEach((id) => window.clearTimeout(id))
      window.removeEventListener('pointerdown', skip)
      window.removeEventListener('keydown', skip)
      window.removeEventListener('wheel', skip)
      window.removeEventListener('touchmove', skip)
      root.classList.remove('is-intro')
    }
  }, [])

  const preloadKey = preload.join('|')
  useEffect(() => {
    for (const src of preloadKey.split('|').filter(Boolean)) {
      const img = new Image()
      img.decoding = 'async'
      img.src = src
    }
  }, [preloadKey])

  const letters = [...name]
  const stagger = letters.length > 1 ? Math.min(0.09, 0.5 / (letters.length - 1)) : 0

  return (
    <div className={`intro ${playing ? 'is-playing' : ''} ${lifting ? 'is-lifting' : ''}`} aria-hidden>
      <div className="intro__mark">
        <p className="intro__name">
          {letters.map((ch, i) => (
            <span key={i} style={{ animationDelay: `${0.1 + i * stagger}s` }}>
              {ch}
            </span>
          ))}
        </p>
        <span className="intro__line" />
        {sub && <p className="intro__sub">{sub}</p>}
      </div>
    </div>
  )
}

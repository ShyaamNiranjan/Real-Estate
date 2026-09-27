import { useEffect, useRef, useState } from 'react'
import { expandFramePattern, joinUrl } from '../lib/format'
import type { ExperienceHero, FrameSequence, MobileMode, ScrollBeat } from '../types/content'

type Variant = 'landscape' | 'portrait'
/** cover: full-bleed crop (desktop, landscape, portrait sequences). rotate/fit: landscape frames on an upright phone. */
type Layout = 'cover' | 'rotate' | 'fit'

const STAGE_BG = '#0c0e0d'
const HERO_UNTIL = 0.04
const BEATS_UNTIL = 0.95
const COMPLETE_AT = 0.999
/** In rotate mode, "Turn upright to continue" appears from here until the stage releases. */
const END_CUE_AT = 0.9
/** First ~2–3 scroll gestures hold on the hero with zero camera movement. */
const HOLD_VIEWPORTS = 0.7
/** Scroll distance of the whole walkthrough, independent of how many frames a listing has. */
const TRACK_PX: Record<Variant, number> = { landscape: 2880, portrait: 2640 }
/** Fit mode: share of the spare height that goes above the video (the rest is below). Mirrored in CSS object-position. */
const FIT_BIAS = 0.56
/** Rotate mode: page pixels scrolled per pixel of sideways finger travel. */
const SWIPE_FACTOR = 1.2
/** Rotate mode: momentum decay per millisecond after the finger lifts. */
const SWIPE_DECAY = 0.9965
const SWIPED_KEY = 'aurelia:walkthrough-swiped'

type Props = {
  sequences: Partial<Record<Variant, FrameSequence>>
  hero: ExperienceHero
  beats: ScrollBeat[]
  label: string
  mobileMode?: MobileMode
}

type View = { variant: Variant; portrait: boolean }

function getView(): View {
  const w = window.innerWidth
  const h = window.innerHeight
  return { variant: w > h || w > 900 ? 'landscape' : 'portrait', portrait: h > w }
}

function resolveLayout(view: View, hasPortrait: boolean, mode: MobileMode): Layout {
  if (!view.portrait || hasPortrait || mode === 'fill') return 'cover'
  if (mode === 'fit') return 'fit'
  // A portrait desktop window cannot be tilted, so only touch devices rotate.
  return window.matchMedia('(pointer: coarse)').matches ? 'rotate' : 'cover'
}

function readSwiped() {
  try {
    return sessionStorage.getItem(SWIPED_KEY) === '1'
  } catch {
    return false
  }
}

function writeSwiped() {
  try {
    sessionStorage.setItem(SWIPED_KEY, '1')
  } catch {
    /* private mode */
  }
}

function frameSrc(seq: FrameSequence, index: number) {
  return joinUrl(seq.baseUrl, expandFramePattern(seq.pattern, index + 1))
}

/** Coarse-to-fine order so the whole timeline is scrubbable before every frame lands. */
function loadOrder(total: number) {
  const order: number[] = []
  const seen = new Uint8Array(total)
  for (const step of [16, 8, 4, 2, 1]) {
    for (let i = 0; i < total; i += step) {
      if (!seen[i]) {
        seen[i] = 1
        order.push(i)
      }
    }
  }
  if (!seen[total - 1]) order.splice(1, 0, total - 1)
  return order
}

function drawCover(ctx: CanvasRenderingContext2D, img: HTMLImageElement, w: number, h: number) {
  const iw = img.naturalWidth
  const ih = img.naturalHeight
  if (!iw || !ih) return
  const scale = Math.max(w / iw, h / ih)
  const dw = iw * scale
  const dh = ih * scale
  ctx.drawImage(img, (w - dw) / 2, (h - dh) / 2, dw, dh)
}

function drawContain(ctx: CanvasRenderingContext2D, img: HTMLImageElement, w: number, h: number) {
  const iw = img.naturalWidth
  const ih = img.naturalHeight
  if (!iw || !ih) return
  const scale = Math.min(w / iw, h / ih)
  const dw = iw * scale
  const dh = ih * scale
  ctx.fillStyle = STAGE_BG
  ctx.fillRect(0, 0, w, h)
  ctx.drawImage(img, (w - dw) / 2, Math.round((h - dh) * FIT_BIAS), dw, dh)
}

export function ScrollExperience({ sequences, hero, beats, label, mobileMode = 'rotate' }: Props) {
  const trackRef = useRef<HTMLDivElement>(null)
  const stageRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const heroRef = useRef<HTMLDivElement>(null)
  const barRef = useRef<HTMLSpanElement>(null)
  const endRef = useRef<HTMLDivElement>(null)
  const beatRefs = useRef<(HTMLElement | null)[]>([])
  const framesRef = useRef<(HTMLImageElement | null)[]>([])
  const requestPaintRef = useRef<() => void>(() => {})
  const [view, setView] = useState<View>(() =>
    typeof window === 'undefined' ? { variant: 'landscape', portrait: false } : getView(),
  )
  const { variant } = view

  const seq = (variant === 'portrait' ? sequences.portrait ?? sequences.landscape : sequences.landscape ?? sequences.portrait)!
  const layout = resolveLayout(view, Boolean(sequences.portrait), mobileMode)
  const rotate = layout === 'rotate'
  const total = Math.max(1, seq.frameCount)
  // Rotate mode plays the landscape walkthrough, so it gets the landscape scroll length.
  const pxPerFrame = seq.pxPerFrame ?? Math.min(40, Math.max(6, TRACK_PX[rotate ? 'landscape' : variant] / total))
  const seqKey = `${seq.baseUrl}|${seq.pattern}|${total}`
  const seqRef = useRef(seq)
  seqRef.current = seq
  const beatsRef = useRef(beats)
  beatsRef.current = beats
  const layoutRef = useRef(layout)
  layoutRef.current = layout

  useEffect(() => {
    const sync = () => {
      const next = getView()
      setView((prev) => (prev.variant === next.variant && prev.portrait === next.portrait ? prev : next))
    }
    const vv = window.visualViewport
    window.addEventListener('resize', sync, { passive: true })
    window.addEventListener('orientationchange', sync)
    vv?.addEventListener('resize', sync, { passive: true })
    return () => {
      window.removeEventListener('resize', sync)
      window.removeEventListener('orientationchange', sync)
      vv?.removeEventListener('resize', sync)
    }
  }, [])

  // Frame loading — writes progress straight to the DOM, no per-image React state.
  useEffect(() => {
    let cancelled = false
    const frames: (HTMLImageElement | null)[] = new Array(total).fill(null)
    framesRef.current = frames
    const stage = stageRef.current
    stage?.classList.remove('is-loaded', 'is-ready')

    const order = loadOrder(total)
    const concurrency = window.matchMedia('(pointer: coarse)').matches ? 6 : 12
    let cursor = 0
    let settled = 0

    const next = () => {
      if (cancelled || cursor >= order.length) return
      const index = order[cursor++]
      const img = new Image()
      img.decoding = 'async'
      img.src = frameSrc(seqRef.current, index)

      const finish = (ok: boolean) => {
        if (cancelled) return
        if (ok) frames[index] = img
        settled += 1
        if (barRef.current) barRef.current.style.transform = `scaleX(${settled / total})`
        if (ok && index === 0) stage?.classList.add('is-ready')
        if (settled >= total) stage?.classList.add('is-loaded')
        requestPaintRef.current()
        next()
      }

      img.onload = () => {
        const decoded = img.decode ? img.decode() : Promise.resolve()
        decoded.then(
          () => finish(true),
          () => finish(true),
        )
      }
      img.onerror = () => finish(false)
    }

    for (let i = 0; i < concurrency; i++) next()

    return () => {
      cancelled = true
      frames.forEach((img) => {
        if (img) img.src = ''
      })
    }
  }, [seqKey, total])

  // Scroll → frame. Passive listener schedules at most one rAF; all updates are imperative.
  useEffect(() => {
    const track = trackRef.current
    const stage = stageRef.current
    const canvas = canvasRef.current
    if (!track || !stage || !canvas) return

    const ctx = canvas.getContext('2d', { alpha: false })
    if (!ctx) return

    const root = document.documentElement
    const coarse = window.matchMedia('(pointer: coarse)').matches
    let raf = 0
    let drawnFrame = -1
    let drawnLayout = layoutRef.current
    let lastTarget = 0
    let activeBeat = -2
    let heroShown: boolean | null = null
    let complete: boolean | null = null
    let ending: boolean | null = null
    let rotatedRoot: boolean | null = null
    let cssW = 0
    let cssH = 0
    let aspect = 0
    let bandKey = ''

    let swiped = readSwiped()
    let startRaw = -1
    if (swiped) stage.classList.add('has-swiped')

    // Orientation changes: remember where the visitor was, keep the last frame up while the
    // new layout settles, then put them back at the same point of the walkthrough.
    type Snapshot = { progress: number; holdPart: number }
    let lastW = window.innerWidth
    let snap: Snapshot | null = null
    let pending: Snapshot | null = null
    let settleTimer = 0

    const holdRatioFor = (maxScroll: number) => {
      const base = layoutRef.current === 'rotate' ? window.innerWidth : window.innerHeight
      return Math.min(0.32, (base * HOLD_VIEWPORTS) / maxScroll)
    }

    const sizeCanvas = () => {
      const w = stage.clientWidth
      const h = stage.clientHeight
      if (w === cssW && h === cssH) return false
      cssW = w
      cssH = h
      const dpr = Math.min(window.devicePixelRatio || 1, coarse ? 1.5 : 2)
      canvas.width = Math.round(w * dpr)
      canvas.height = Math.round(h * dpr)
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.imageSmoothingEnabled = true
      ctx.imageSmoothingQuality = coarse ? 'medium' : 'high'
      ctx.fillStyle = STAGE_BG
      ctx.fillRect(0, 0, w, h)
      drawnFrame = -1
      return true
    }

    const nearestLoaded = (target: number) => {
      const frames = framesRef.current
      if (frames[target]) return target
      for (let d = 1; d < total; d++) {
        if (target - d >= 0 && frames[target - d]) return target - d
        if (target + d < total && frames[target + d]) return target + d
      }
      return -1
    }

    const paint = (target: number) => {
      lastTarget = target
      const idx = nearestLoaded(target)
      if (idx < 0 || idx === drawnFrame) return
      const img = framesRef.current[idx]
      if (!img) return
      if (drawnLayout === 'fit') drawContain(ctx, img, cssW, cssH)
      else drawCover(ctx, img, cssW, cssH)
      drawnFrame = idx
    }

    /** Fit mode: tells the CSS where the letterboxed video sits so copy can live in the bars. */
    const syncBand = () => {
      if (drawnLayout !== 'fit') return
      if (!aspect) {
        const img = framesRef.current.find((f) => f && f.naturalWidth && f.naturalHeight)
        if (img) aspect = img.naturalWidth / img.naturalHeight
      }
      const bandH = Math.min(cssH, cssW / (aspect || 16 / 9))
      const bandTop = Math.round((cssH - bandH) * FIT_BIAS)
      const key = `${bandTop}|${Math.round(bandH)}`
      if (key === bandKey) return
      bandKey = key
      stage.style.setProperty('--band-top', `${bandTop}px`)
      stage.style.setProperty('--band-h', `${Math.round(bandH)}px`)
    }

    const syncOverlays = (progress: number) => {
      const showHero = progress < HERO_UNTIL
      if (showHero !== heroShown) {
        heroShown = showHero
        heroRef.current?.classList.toggle('is-visible', showHero)
      }

      let beat = -1
      if (progress >= HERO_UNTIL && progress < BEATS_UNTIL) {
        beatsRef.current.forEach((b, i) => {
          if (progress >= b.at) beat = i
        })
      }
      if (beat !== activeBeat) {
        activeBeat = beat
        beatRefs.current.forEach((el, i) => el?.classList.toggle('is-active', i === beat))
      }
    }

    const alignEnd = (maxScroll: number) => {
      const end = endRef.current
      if (!end) return
      // Rotated, the stage's width is the viewport's height.
      const endH = drawnLayout === 'rotate' ? cssW : cssH
      if (end.dataset.top !== String(maxScroll)) {
        end.dataset.top = String(maxScroll)
        end.style.top = `${maxScroll}px`
      }
      if (end.dataset.h !== String(endH)) {
        end.dataset.h = String(endH)
        end.style.height = `${endH}px`
      }
    }

    const restore = () => {
      settleTimer = 0
      const p = pending
      pending = null
      if (!p) return
      const maxScroll = Math.max(1, track.offsetHeight - window.innerHeight)
      const hold = holdRatioFor(maxScroll)
      const raw = p.progress > 0 ? hold + p.progress * (1 - hold) : p.holdPart * hold
      window.scrollTo(0, Math.round(raw * maxScroll))
      schedule()
    }

    const settle = (delay: number) => {
      if (!pending && snap) pending = snap
      if (!pending) return
      window.clearTimeout(settleTimer)
      settleTimer = window.setTimeout(restore, delay)
    }

    const update = () => {
      raf = 0
      const layout = layoutRef.current
      if (layout === 'rotate') {
        track.style.setProperty('--rot-w', `${window.innerHeight}px`)
        track.style.setProperty('--rot-h', `${window.innerWidth}px`)
      }
      if (layout !== drawnLayout) {
        drawnLayout = layout
        cssW = 0
        bandKey = ''
      }
      sizeCanvas()
      syncBand()
      const maxScroll = Math.max(1, track.offsetHeight - window.innerHeight)
      alignEnd(maxScroll)

      if (window.innerWidth !== lastW) {
        lastW = window.innerWidth
        settle(200)
      }
      if (pending) {
        paint(lastTarget)
        return
      }

      const raw = Math.min(1, Math.max(0, window.scrollY / maxScroll))
      // Dead-zone at the start: first ~2–3 scrolls keep frame 0 + hero locked
      const holdRatio = holdRatioFor(maxScroll)
      const progress =
        raw <= holdRatio ? 0 : Math.min(1, (raw - holdRatio) / (1 - holdRatio))
      snap = progress < COMPLETE_AT ? { progress, holdPart: holdRatio > 0 ? Math.min(1, raw / holdRatio) : 1 } : null

      const done = progress >= COMPLETE_AT
      if (done !== complete) {
        complete = done
        stage.classList.toggle('is-complete', done)
      }

      const rotated = layout === 'rotate' && !done
      if (rotated !== rotatedRoot) {
        rotatedRoot = rotated
        root.classList.toggle('stage-rotated', rotated)
      }

      if (layout === 'rotate') {
        const isEnding = progress >= END_CUE_AT
        if (isEnding !== ending) {
          ending = isEnding
          stage.classList.toggle('is-ending', isEnding)
        }
        if (!swiped) {
          if (startRaw < 0) startRaw = raw
          else if (Math.abs(raw - startRaw) > 0.01) {
            swiped = true
            stage.classList.add('has-swiped')
            writeSwiped()
          }
        }
      }

      paint(Math.round(progress * (total - 1)))
      syncOverlays(progress)
    }

    const schedule = () => {
      if (!raf) raf = requestAnimationFrame(update)
    }

    const onViewport = () => {
      if (window.innerWidth !== lastW) {
        lastW = window.innerWidth
        settle(200)
      } else if (pending) settle(200)
      schedule()
    }
    // iOS fires this before the viewport has its new size, so wait a little longer.
    const onOrientation = () => {
      settle(350)
      schedule()
    }

    requestPaintRef.current = schedule

    update()
    const vv = window.visualViewport
    window.addEventListener('scroll', schedule, { passive: true })
    window.addEventListener('resize', onViewport, { passive: true })
    window.addEventListener('orientationchange', onOrientation)
    vv?.addEventListener('resize', onViewport, { passive: true })

    return () => {
      window.removeEventListener('scroll', schedule)
      window.removeEventListener('resize', onViewport)
      window.removeEventListener('orientationchange', onOrientation)
      vv?.removeEventListener('resize', onViewport)
      if (raf) cancelAnimationFrame(raf)
      window.clearTimeout(settleTimer)
      root.classList.remove('stage-rotated')
      requestPaintRef.current = () => {}
    }
  }, [seqKey, total])

  // Rotate mode: the visitor holds the phone sideways, so their "swipe up" is a sideways move in
  // portrait coordinates. Translate it into page scroll so it drives the same scroll progress.
  useEffect(() => {
    if (!rotate) return
    const track = trackRef.current
    const stage = stageRef.current
    if (!track || !stage) return

    let axis: 'x' | 'y' | null = null
    let startX = 0
    let startY = 0
    let lastX = 0
    let lastT = 0
    let velocity = 0
    let pos = 0
    let glide = 0

    const active = () => !stage.classList.contains('is-complete')
    const maxY = () => Math.max(0, track.offsetTop + track.offsetHeight - window.innerHeight)

    /** Returns false once the walkthrough bounds are reached. */
    const drive = (dx: number) => {
      const limit = maxY()
      const next = Math.min(limit, Math.max(0, pos + dx * SWIPE_FACTOR))
      const moved = next !== pos
      pos = next
      window.scrollTo(0, pos)
      return moved && next > 0 && next < limit
    }

    const stopGlide = () => {
      if (glide) cancelAnimationFrame(glide)
      glide = 0
    }

    const onStart = (e: TouchEvent) => {
      stopGlide()
      axis = null
      if (!active() || e.touches.length !== 1) return
      const t = e.touches[0]
      startX = lastX = t.clientX
      startY = t.clientY
      lastT = e.timeStamp
      velocity = 0
    }

    const onMove = (e: TouchEvent) => {
      if (e.touches.length !== 1 || !active()) return
      const t = e.touches[0]
      if (axis === null) {
        const dx = t.clientX - startX
        const dy = t.clientY - startY
        if (Math.hypot(dx, dy) < 8) return
        axis = Math.abs(dx) > Math.abs(dy) ? 'x' : 'y'
        if (axis === 'x') {
          if (e.cancelable) e.preventDefault()
          pos = window.scrollY
          lastX = t.clientX
          lastT = e.timeStamp
          return
        }
      }
      if (axis !== 'x') return
      if (e.cancelable) e.preventDefault()
      const step = t.clientX - lastX
      const dt = e.timeStamp - lastT
      if (dt > 0) velocity = 0.8 * (step / dt) + 0.2 * velocity
      lastX = t.clientX
      lastT = e.timeStamp
      drive(step)
    }

    const onEnd = (e: TouchEvent) => {
      if (axis !== 'x') return
      axis = null
      if (e.timeStamp - lastT > 80 || Math.abs(velocity) < 0.05) return
      let prev = performance.now()
      const step = (now: number) => {
        const dt = Math.min(48, now - prev)
        prev = now
        const inBounds = drive(velocity * dt)
        velocity *= Math.pow(SWIPE_DECAY, dt)
        glide = inBounds && active() && Math.abs(velocity) > 0.02 ? requestAnimationFrame(step) : 0
      }
      glide = requestAnimationFrame(step)
    }

    track.addEventListener('touchstart', onStart, { passive: true })
    track.addEventListener('touchmove', onMove, { passive: false })
    track.addEventListener('touchend', onEnd, { passive: true })
    track.addEventListener('touchcancel', onEnd, { passive: true })
    return () => {
      stopGlide()
      track.removeEventListener('touchstart', onStart)
      track.removeEventListener('touchmove', onMove)
      track.removeEventListener('touchend', onEnd)
      track.removeEventListener('touchcancel', onEnd)
    }
  }, [rotate])

  const trackClass = `scroll-track${rotate ? ' is-rotated' : ''}${layout === 'fit' ? ' is-fit' : ''}`

  return (
    <div
      className={trackClass}
      ref={trackRef}
      style={{ height: `calc(${total * pxPerFrame}px + 100svh)` }}
      aria-label={label}
    >
      {/* Positioned (in JS) exactly where the viewport sits at max scroll, sized like the
          stage, so fading the fixed stage out is invisible and the scene scrolls away with the page. */}
      <div className="scroll-track__end" ref={endRef} aria-hidden>
        <div className="scroll-track__frame">
          <img src={frameSrc(seq, total - 1)} alt="" decoding="async" />
          <div className="scroll-veil" />
          {rotate && <UprightCue />}
        </div>
      </div>

      <div className="scroll-stage" ref={stageRef}>
        <canvas ref={canvasRef} className="scroll-stage__canvas" />
        <div className="scroll-veil" aria-hidden />

        <div className="scroll-stage__ui">
          <div className="scroll-hero" ref={heroRef}>
            <div className="scroll-hero__copy">
              {hero.brand && <p className="scroll-hero__brand">{hero.brand}</p>}
              {hero.line && <h1 className="scroll-hero__line">{hero.line}</h1>}
              {hero.support && <p className="scroll-hero__support">{hero.support}</p>}
            </div>
            <div className="scroll-hero__hint">
              <span>{hero.scrollHint ?? 'Scroll to enter'}</span>
              <span className="scroll-hero__hint-line" />
            </div>
            {rotate && (
              <div className="scroll-cue scroll-cue--turn" aria-hidden>
                <svg className="scroll-cue__icon scroll-cue__icon--turn" viewBox="0 0 40 40" fill="none">
                  <path className="scroll-cue__arc" d="M31 11.5A13.5 13.5 0 0 0 9 11.5" />
                  <path className="scroll-cue__arc" d="M12.6 10.6 9 11.5 8.4 7.8" />
                  <g className="scroll-cue__phone">
                    <rect x="8" y="14" width="24" height="14" rx="2.6" />
                    <path d="M29 19.2v3.6" />
                  </g>
                </svg>
                <span>Turn your phone sideways</span>
              </div>
            )}
          </div>

          <div className="scroll-beats">
            {beats.map((beat, i) => (
              <aside
                key={beat.id}
                ref={(el) => {
                  beatRefs.current[i] = el
                }}
                className={`beat beat--${beat.side}`}
              >
                <p className="beat__label">{beat.label}</p>
                <p className="beat__text">{beat.text}</p>
              </aside>
            ))}
          </div>

          {rotate && (
            <>
              <div className="scroll-swipe" aria-hidden>
                <span className="scroll-swipe__trail">
                  <span className="scroll-swipe__dot" />
                </span>
                <span className="scroll-swipe__label">Swipe to walk through</span>
              </div>
              <UprightCue />
            </>
          )}

          <div className="scroll-loader" aria-hidden>
            <span className="scroll-loader__bar" ref={barRef} />
          </div>
        </div>
      </div>
    </div>
  )
}

function UprightCue() {
  return (
    <div className="scroll-cue scroll-cue--upright" aria-hidden>
      <svg className="scroll-cue__icon" viewBox="0 0 40 40" fill="none">
        <path className="scroll-cue__arc" d="M9 28.5A13.5 13.5 0 0 1 9 11.5" />
        <path className="scroll-cue__arc" d="M5.4 13.2 9 11.5 9.9 15.2" />
        <g className="scroll-cue__phone scroll-cue__phone--upright">
          <rect x="14" y="7" width="14" height="26" rx="2.6" />
          <path d="M19.2 30h3.6" />
        </g>
      </svg>
      <span>Turn upright to continue</span>
    </div>
  )
}

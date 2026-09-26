import { useEffect, useRef, useState } from 'react'
import { expandFramePattern, joinUrl } from '../lib/format'
import type { ExperienceHero, FrameSequence, ScrollBeat } from '../types/content'

type Variant = 'landscape' | 'portrait'

const STAGE_BG = '#0c0e0d'
const HERO_UNTIL = 0.04
const BEATS_UNTIL = 0.95
const COMPLETE_AT = 0.999
/** First ~2–3 scroll gestures hold on the hero with zero camera movement. */
const HOLD_VIEWPORTS = 0.7
/** Scroll distance of the whole walkthrough, independent of how many frames a listing has. */
const TRACK_PX: Record<Variant, number> = { landscape: 2880, portrait: 2640 }

type Props = {
  sequences: Partial<Record<Variant, FrameSequence>>
  hero: ExperienceHero
  beats: ScrollBeat[]
  label: string
}

function getVariant(): Variant {
  const w = window.innerWidth
  const h = window.innerHeight
  return w > h || w > 900 ? 'landscape' : 'portrait'
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

export function ScrollExperience({ sequences, hero, beats, label }: Props) {
  const trackRef = useRef<HTMLDivElement>(null)
  const stageRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const heroRef = useRef<HTMLDivElement>(null)
  const barRef = useRef<HTMLSpanElement>(null)
  const endRef = useRef<HTMLDivElement>(null)
  const beatRefs = useRef<(HTMLElement | null)[]>([])
  const framesRef = useRef<(HTMLImageElement | null)[]>([])
  const requestPaintRef = useRef<() => void>(() => {})
  const [variant, setVariant] = useState<Variant>(() =>
    typeof window === 'undefined' ? 'landscape' : getVariant(),
  )

  const seq = (variant === 'portrait' ? sequences.portrait ?? sequences.landscape : sequences.landscape ?? sequences.portrait)!
  const total = Math.max(1, seq.frameCount)
  const pxPerFrame = seq.pxPerFrame ?? Math.min(40, Math.max(6, TRACK_PX[variant] / total))
  const seqKey = `${seq.baseUrl}|${seq.pattern}|${total}`
  const seqRef = useRef(seq)
  seqRef.current = seq
  const beatsRef = useRef(beats)
  beatsRef.current = beats

  useEffect(() => {
    const sync = () => {
      const next = getVariant()
      setVariant((prev) => (prev === next ? prev : next))
    }
    window.addEventListener('resize', sync, { passive: true })
    window.addEventListener('orientationchange', sync)
    return () => {
      window.removeEventListener('resize', sync)
      window.removeEventListener('orientationchange', sync)
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

    const coarse = window.matchMedia('(pointer: coarse)').matches
    let raf = 0
    let drawnFrame = -1
    let activeBeat = -2
    let heroShown: boolean | null = null
    let complete: boolean | null = null
    let cssW = 0
    let cssH = 0

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
      const idx = nearestLoaded(target)
      if (idx < 0 || idx === drawnFrame) return
      const img = framesRef.current[idx]
      if (!img) return
      drawCover(ctx, img, cssW, cssH)
      drawnFrame = idx
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
      if (end.dataset.top !== String(maxScroll)) {
        end.dataset.top = String(maxScroll)
        end.style.top = `${maxScroll}px`
      }
      if (end.dataset.h !== String(cssH)) {
        end.dataset.h = String(cssH)
        end.style.height = `${cssH}px`
      }
    }

    const update = () => {
      raf = 0
      sizeCanvas()
      const maxScroll = Math.max(1, track.offsetHeight - window.innerHeight)
      alignEnd(maxScroll)

      const raw = Math.min(1, Math.max(0, window.scrollY / maxScroll))
      // Dead-zone at the start: first ~2–3 scrolls keep frame 0 + hero locked
      const holdRatio = Math.min(0.32, (window.innerHeight * HOLD_VIEWPORTS) / maxScroll)
      const progress =
        raw <= holdRatio ? 0 : Math.min(1, (raw - holdRatio) / (1 - holdRatio))

      const done = progress >= COMPLETE_AT
      if (done !== complete) {
        complete = done
        stage.classList.toggle('is-complete', done)
      }

      paint(Math.round(progress * (total - 1)))
      syncOverlays(progress)
    }

    const schedule = () => {
      if (!raf) raf = requestAnimationFrame(update)
    }

    requestPaintRef.current = schedule

    update()
    window.addEventListener('scroll', schedule, { passive: true })
    window.addEventListener('resize', schedule, { passive: true })

    return () => {
      window.removeEventListener('scroll', schedule)
      window.removeEventListener('resize', schedule)
      if (raf) cancelAnimationFrame(raf)
      requestPaintRef.current = () => {}
    }
  }, [seqKey, total])

  return (
    <div
      className="scroll-track"
      ref={trackRef}
      style={{ height: `calc(${total * pxPerFrame}px + 100svh)` }}
      aria-label={label}
    >
      {/* Positioned (in JS) exactly where the viewport sits at max scroll, sized like the
          stage, so fading the fixed stage out is invisible and the scene scrolls away with the page. */}
      <div className="scroll-track__end" ref={endRef} aria-hidden>
        <img src={frameSrc(seq, total - 1)} alt="" decoding="async" />
        <div className="scroll-veil" />
      </div>

      <div className="scroll-stage" ref={stageRef}>
        <canvas ref={canvasRef} className="scroll-stage__canvas" />
        <div className="scroll-veil" aria-hidden />

        <div className="scroll-stage__ui">
          <div className="scroll-hero" ref={heroRef}>
            {hero.brand && <p className="scroll-hero__brand">{hero.brand}</p>}
            {hero.line && <h1 className="scroll-hero__line">{hero.line}</h1>}
            {hero.support && <p className="scroll-hero__support">{hero.support}</p>}
            <div className="scroll-hero__hint">
              <span>{hero.scrollHint ?? 'Scroll to enter'}</span>
              <span className="scroll-hero__hint-line" />
            </div>
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

          <div className="scroll-loader" aria-hidden>
            <span className="scroll-loader__bar" ref={barRef} />
          </div>
        </div>
      </div>
    </div>
  )
}

'use client'

import { useEffect, useRef, useState } from 'react'

export type LoopSource = {
  /** Folder under /public holding `01.jpg`, `02.jpg`, … */
  baseUrl: string
  count: number
}

/** Seconds for one there-and-back drift through the frames. */
const PERIOD_S = 22
const CONCURRENCY = 6

function frameUrl(source: LoopSource, n: number) {
  return `${source.baseUrl}/${String(n).padStart(2, '0')}.jpg`
}

function prefersReducedMotion() {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
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

/**
 * A slow, silent drift through walkthrough frames, eased at both ends so the camera glides
 * forward and back. Loads only near the viewport, pauses off-screen, and stays a still for
 * visitors who prefer reduced motion. Ported from src/public/FrameLoop.tsx.
 */
export function FrameLoop({
  source,
  poster,
  eager = false,
}: {
  source: LoopSource
  poster: string | null
  /** Above the fold: load the poster straight away. */
  eager?: boolean
}) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [live, setLive] = useState(false)
  const { baseUrl, count } = source

  useEffect(() => {
    const wrap = wrapRef.current
    const canvas = canvasRef.current
    const ctx = canvas?.getContext('2d', { alpha: false })
    if (!wrap || !canvas || !ctx || prefersReducedMotion() || !('IntersectionObserver' in window)) return

    const total = Math.max(1, count)
    const frames: (HTMLImageElement | null)[] = Array.from({ length: total }, () => null)

    let cancelled = false
    let loading = false
    let ready = false
    let visible = false
    let raf = 0
    let clock = 0
    let lastNow = 0

    const size = () => {
      const r = wrap.getBoundingClientRect()
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      canvas.width = Math.max(1, Math.round(r.width * dpr))
      canvas.height = Math.max(1, Math.round(r.height * dpr))
    }

    const draw = () => {
      const last = frames.length - 1
      const phase = (clock / PERIOD_S) * Math.PI * 2
      const pos = ((1 - Math.cos(phase)) / 2) * last
      const a = Math.floor(pos)
      const b = Math.min(last, a + 1)
      const mix = pos - a
      const w = canvas.width
      const h = canvas.height
      ctx.globalAlpha = 1
      const fa = frames[a]
      const fb = frames[b]
      if (fa) drawCover(ctx, fa, w, h)
      if (mix > 0.01 && fb) {
        ctx.globalAlpha = mix
        drawCover(ctx, fb, w, h)
        ctx.globalAlpha = 1
      }
    }

    const tick = (now: number) => {
      raf = 0
      if (!visible || !ready || document.hidden) {
        lastNow = 0
        return
      }
      if (lastNow) clock += Math.min(0.1, (now - lastNow) / 1000)
      lastNow = now
      draw()
      raf = requestAnimationFrame(tick)
    }

    const play = () => {
      if (!raf && visible && ready && !document.hidden) raf = requestAnimationFrame(tick)
    }

    const load = () => {
      if (loading) return
      loading = true
      let cursor = 0
      let settled = 0
      const next = () => {
        if (cancelled || cursor >= total) return
        const i = cursor++
        const img = new Image()
        img.decoding = 'async'
        const done = (ok: boolean) => {
          if (cancelled) return
          if (ok) frames[i] = img
          settled += 1
          if (settled === total && frames[0]) {
            ready = true
            size()
            draw()
            setLive(true)
            play()
          }
          next()
        }
        img.onload = () => {
          const decoded = img.decode ? img.decode() : Promise.resolve()
          decoded.then(
            () => done(true),
            () => done(true),
          )
        }
        img.onerror = () => done(false)
        img.src = frameUrl({ baseUrl, count }, i + 1)
      }
      for (let c = 0; c < CONCURRENCY; c++) next()
    }

    const near = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          load()
          near.disconnect()
        }
      },
      { rootMargin: '600px 0px' },
    )
    const onScreen = new IntersectionObserver((entries) => {
      visible = entries.some((e) => e.isIntersecting)
      play()
    })
    const resize = new ResizeObserver(() => {
      if (!ready) return
      size()
      draw()
    })
    const onVisibility = () => play()

    near.observe(wrap)
    onScreen.observe(wrap)
    resize.observe(wrap)
    document.addEventListener('visibilitychange', onVisibility)

    return () => {
      cancelled = true
      near.disconnect()
      onScreen.disconnect()
      resize.disconnect()
      document.removeEventListener('visibilitychange', onVisibility)
      if (raf) cancelAnimationFrame(raf)
      setLive(false)
    }
  }, [baseUrl, count])

  return (
    <div className={`frame-loop ${live ? 'is-live' : ''}`} ref={wrapRef}>
      {poster && (
        // eslint-disable-next-line @next/next/no-img-element -- decorative poster under the canvas, sized by CSS
        <img src={poster} alt="" loading={eager ? 'eager' : 'lazy'} fetchPriority={eager ? 'high' : 'auto'} decoding="async" />
      )}
      <canvas ref={canvasRef} aria-hidden />
    </div>
  )
}

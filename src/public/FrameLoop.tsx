import { useEffect, useRef, useState } from 'react'
import { expandFramePattern, joinUrl } from '../lib/format'
import type { FrameLoop as FrameLoopSource } from '../types/content'
import { prefersReducedMotion } from './links'

/** Frames sampled from the full sequence; keeps the teaser to ~2–3 MB. */
const MAX_FRAMES = 48
/** Seconds for one there-and-back drift through the sampled frames. */
const PERIOD_S = 22
const CONCURRENCY = 6

export function loopFrameUrl(source: FrameLoopSource, frameNumber: number) {
  return joinUrl(source.baseUrl, expandFramePattern(source.pattern, frameNumber))
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
 * A slow, silent drift through a listing's walkthrough frames, eased at both ends so the camera
 * glides forward and back. Loads only near the viewport, pauses off-screen, and stays a still
 * for visitors who prefer reduced motion.
 */
export function FrameLoop({ source, poster }: { source: FrameLoopSource; poster: string | null }) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [live, setLive] = useState(false)
  const key = `${source.baseUrl}|${source.pattern}|${source.count}`

  useEffect(() => {
    const wrap = wrapRef.current
    const canvas = canvasRef.current
    const ctx = canvas?.getContext('2d', { alpha: false })
    if (!wrap || !canvas || !ctx || prefersReducedMotion() || !('IntersectionObserver' in window)) return

    const count = Math.max(1, source.count)
    const step = Math.max(1, Math.ceil(count / MAX_FRAMES))
    const numbers: number[] = []
    for (let n = 1; n <= count; n += step) numbers.push(n)
    const frames: (HTMLImageElement | null)[] = numbers.map(() => null)

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
      if (frames[a]) drawCover(ctx, frames[a]!, w, h)
      if (mix > 0.01 && frames[b]) {
        ctx.globalAlpha = mix
        drawCover(ctx, frames[b]!, w, h)
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
        if (cancelled || cursor >= numbers.length) return
        const i = cursor++
        const img = new Image()
        img.decoding = 'async'
        const done = (ok: boolean) => {
          if (cancelled) return
          if (ok) frames[i] = img
          settled += 1
          if (settled === numbers.length && frames[0]) {
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
        img.src = loopFrameUrl(source, numbers[i])
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
    // `key` captures every field of `source` that affects loading.
  }, [key])

  return (
    <div className={`frame-loop ${live ? 'is-live' : ''}`} ref={wrapRef}>
      {poster && <img src={poster} alt="" loading="lazy" decoding="async" />}
      <canvas ref={canvasRef} aria-hidden />
    </div>
  )
}

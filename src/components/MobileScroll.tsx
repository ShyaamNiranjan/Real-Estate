import { useEffect, useRef, useState } from 'react'
import { copy } from '../content/copy'

const FRAME_COUNT = 120
const PX_PER_FRAME = 16

const frameSrc = (index: number) =>
  `/media/sequence-portrait-lite/frame-${String(index + 1).padStart(3, '0')}.jpg`

function drawCover(
  ctx: CanvasRenderingContext2D,
  img: HTMLImageElement,
  width: number,
  height: number,
) {
  const iw = img.naturalWidth
  const ih = img.naturalHeight
  if (!iw || !ih) return
  const scale = Math.max(width / iw, height / ih)
  ctx.drawImage(
    img,
    (width - iw * scale) / 2,
    (height - ih * scale) / 2,
    iw * scale,
    ih * scale,
  )
}

/**
 * Dedicated mobile scroll experience.
 * Fixed fullscreen stage + tall scroll track — no GSAP pin —
 * so cream/white page background never flashes between frames.
 */
export function MobileScroll() {
  const trackRef = useRef<HTMLDivElement>(null)
  const stageRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const heroRef = useRef<HTMLDivElement>(null)
  const beatRefs = useRef<(HTMLElement | null)[]>([])
  const framesRef = useRef<(HTMLImageElement | null)[]>([])
  const drawnFrameRef = useRef(-1)
  const activeBeatRef = useRef(-1)
  const rafRef = useRef(0)
  const [ready, setReady] = useState(false)
  const [loadPct, setLoadPct] = useState(0)

  const trackHeight = `calc(${FRAME_COUNT * PX_PER_FRAME}px + 100svh)`

  useEffect(() => {
    // Optional hook for mobile-specific CSS; no global bg override
    document.documentElement.classList.add('mobile-scroll-active')
    return () => document.documentElement.classList.remove('mobile-scroll-active')
  }, [])

  useEffect(() => {
    let cancelled = false
    const frames: (HTMLImageElement | null)[] = Array(FRAME_COUNT).fill(null)
    framesRef.current = frames
    let loaded = 0

    const bump = () => {
      loaded += 1
      if (cancelled) return
      setLoadPct(Math.round((loaded / FRAME_COUNT) * 100))
      if (loaded >= FRAME_COUNT) setReady(true)
    }

    let i = 0
    const batch = 8
    const loadBatch = () => {
      if (cancelled) return
      const end = Math.min(FRAME_COUNT, i + batch)
      for (; i < end; i++) {
        const index = i
        const img = new Image()
        img.decoding = 'async'
        img.src = frameSrc(index)
        img.onload = () => {
          frames[index] = img
          if (img.decode) img.decode().then(bump).catch(bump)
          else bump()
        }
        img.onerror = () => bump()
      }
      if (i < FRAME_COUNT) window.setTimeout(loadBatch, 0)
    }
    loadBatch()

    return () => {
      cancelled = true
      frames.forEach((img) => {
        if (img) img.src = ''
      })
    }
  }, [])

  useEffect(() => {
    if (!ready) return

    const track = trackRef.current
    const stage = stageRef.current
    const canvas = canvasRef.current
    if (!track || !stage || !canvas) return

    const ctx = canvas.getContext('2d', { alpha: false, desynchronized: true })
    if (!ctx) return
    ctx.imageSmoothingEnabled = true
    ctx.imageSmoothingQuality = 'low'

    const sizeCanvas = () => {
      const w = window.innerWidth
      const h = window.innerHeight
      // Solid fill first so resize never flashes white
      canvas.width = w
      canvas.height = h
      canvas.style.width = `${w}px`
      canvas.style.height = `${h}px`
      ctx.setTransform(1, 0, 0, 1, 0, 0)
      ctx.fillStyle = '#0c0e0d'
      ctx.fillRect(0, 0, w, h)
      drawnFrameRef.current = -1
    }

    const paint = (frameIndex: number) => {
      const idx = Math.max(0, Math.min(FRAME_COUNT - 1, frameIndex))
      if (idx === drawnFrameRef.current) return
      const img = framesRef.current[idx]
      if (!img) return
      drawCover(ctx, img, canvas.width, canvas.height)
      drawnFrameRef.current = idx
    }

    const syncCopy = (progress: number) => {
      heroRef.current?.classList.toggle('is-visible', progress < 0.04)
      let next = -1
      if (progress >= 0.04) {
        copy.scrollBeats.forEach((beat, i) => {
          if (progress >= beat.at) next = i
        })
      }
      if (activeBeatRef.current !== next) {
        activeBeatRef.current = next
        beatRefs.current.forEach((el, i) => {
          el?.classList.toggle('is-active', i === next)
        })
      }
    }

    const update = () => {
      rafRef.current = 0
      const maxScroll = Math.max(1, track.offsetHeight - window.innerHeight)
      const progress = Math.min(1, Math.max(0, window.scrollY / maxScroll))
      const done = progress >= 0.999

      stage.classList.toggle('is-complete', done)

      if (done) {
        // Uncover the site below — stage stays black behind until then
        stage.style.opacity = '0'
        stage.style.pointerEvents = 'none'
        return
      }

      stage.style.opacity = '1'
      stage.style.pointerEvents = 'none'
      paint(Math.round(progress * (FRAME_COUNT - 1)))
      syncCopy(progress)
    }

    const onScroll = () => {
      if (rafRef.current) return
      rafRef.current = requestAnimationFrame(update)
    }

    const onOrient = () => {
      window.setTimeout(() => {
        sizeCanvas()
        update()
      }, 300)
    }

    sizeCanvas()
    paint(0)
    syncCopy(0)
    update()

    window.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('resize', sizeCanvas, { passive: true })
    window.addEventListener('orientationchange', onOrient)

    return () => {
      window.removeEventListener('scroll', onScroll)
      window.removeEventListener('resize', sizeCanvas)
      window.removeEventListener('orientationchange', onOrient)
      if (rafRef.current) cancelAnimationFrame(rafRef.current)
    }
  }, [ready])

  return (
    <div
      className="mobile-scroll"
      ref={trackRef}
      style={{ height: trackHeight }}
      aria-label="Scroll sequence"
    >
      <div className="mobile-scroll__stage" ref={stageRef}>
        <canvas ref={canvasRef} className="mobile-scroll__canvas" />

        {!ready && (
          <div className="mobile-scroll__loader" aria-live="polite">
            <p>{loadPct}%</p>
          </div>
        )}

        <div className="mobile-scroll__veil" aria-hidden />

        <div className={`mobile-scroll__hero ${ready ? 'is-visible' : ''}`} ref={heroRef}>
          <p className="mobile-scroll__brand">{copy.hero.brand}</p>
          <h1 className="mobile-scroll__line">{copy.hero.line}</h1>
          <p className="mobile-scroll__support">{copy.hero.support}</p>
          <div className="mobile-scroll__hint">
            <span>{copy.hero.scrollHint}</span>
            <span className="mobile-scroll__hint-line" />
          </div>
        </div>

        <div className="mobile-scroll__beats" aria-live="polite">
          {copy.scrollBeats.map((beat, i) => (
            <aside
              key={beat.id}
              ref={(el) => {
                beatRefs.current[i] = el
              }}
              className="mobile-scroll__beat"
            >
              <p className="mobile-scroll__beat-label">{beat.label}</p>
              <p className="mobile-scroll__beat-text">{beat.text}</p>
            </aside>
          ))}
        </div>
      </div>
    </div>
  )
}

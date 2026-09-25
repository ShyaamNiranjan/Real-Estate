import { useEffect, useRef, useState } from 'react'
import { gsap } from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import { useGSAP } from '@gsap/react'

gsap.registerPlugin(ScrollTrigger, useGSAP)

// Stops iOS/Android URL-bar resize from constantly recalculating pins mid-scroll
ScrollTrigger.config({ ignoreMobileResize: true })

const FRAME_COUNT = 240

type Variant = 'landscape' | 'portrait'

function isTouchDevice() {
  return window.matchMedia('(hover: none), (pointer: coarse)').matches
}

function getVariant(): Variant {
  const narrow = window.matchMedia('(max-width: 900px)').matches
  const tall = window.innerHeight >= window.innerWidth
  return narrow && tall ? 'portrait' : 'landscape'
}

function frameSrc(variant: Variant, index: number) {
  const folder = variant === 'portrait' ? 'sequence-portrait' : 'sequence'
  return `/media/${folder}/frame-${String(index + 1).padStart(3, '0')}.jpg`
}

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
  const dw = iw * scale
  const dh = ih * scale
  ctx.drawImage(img, (width - dw) / 2, (height - dh) / 2, dw, dh)
}

function loadFrames(
  variant: Variant,
  onProgress: (pct: number) => void,
  signal: { cancelled: boolean },
) {
  return new Promise<(HTMLImageElement | null)[]>((resolve) => {
    const frames: (HTMLImageElement | null)[] = Array(FRAME_COUNT).fill(null)
    let loaded = 0

    const bump = () => {
      loaded += 1
      if (signal.cancelled) return
      onProgress(Math.round((loaded / FRAME_COUNT) * 100))
      if (loaded >= FRAME_COUNT) resolve(frames)
    }

    // Stagger decode a bit on mobile so the main thread isn't flooded
    const touch = isTouchDevice()
    const kick = (i: number) => {
      const img = new Image()
      img.decoding = 'async'
      img.src = frameSrc(variant, i)
      const done = () => {
        frames[i] = img
        bump()
      }
      img.onload = () => {
        if (img.decode) img.decode().then(done).catch(done)
        else done()
      }
      img.onerror = () => bump()
    }

    if (!touch) {
      for (let i = 0; i < FRAME_COUNT; i++) kick(i)
      return
    }

    let i = 0
    const batch = 12
    const pump = () => {
      if (signal.cancelled) return
      const end = Math.min(FRAME_COUNT, i + batch)
      for (; i < end; i++) kick(i)
      if (i < FRAME_COUNT) {
        window.setTimeout(pump, 0)
      }
    }
    pump()
  })
}

export function VideoScroll() {
  const sectionRef = useRef<HTMLElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const framesRef = useRef<(HTMLImageElement | null)[]>([])
  const drawnFrameRef = useRef(-1)
  const lastWidthRef = useRef(0)
  const [variant, setVariant] = useState<Variant>(() =>
    typeof window !== 'undefined' ? getVariant() : 'landscape',
  )
  const [ready, setReady] = useState(false)
  const [loadPct, setLoadPct] = useState(0)

  useEffect(() => {
    const syncVariant = () => {
      const next = getVariant()
      setVariant((prev) => (prev === next ? prev : next))
    }

    syncVariant()
    const mqWidth = window.matchMedia('(max-width: 900px)')
    const mqOrient = window.matchMedia('(orientation: portrait)')
    mqWidth.addEventListener('change', syncVariant)
    mqOrient.addEventListener('change', syncVariant)
    // Intentionally NOT listening to window resize — mobile chrome toggles fire it constantly

    return () => {
      mqWidth.removeEventListener('change', syncVariant)
      mqOrient.removeEventListener('change', syncVariant)
    }
  }, [])

  useEffect(() => {
    const signal = { cancelled: false }
    setReady(false)
    setLoadPct(0)
    framesRef.current = []
    drawnFrameRef.current = -1

    loadFrames(variant, setLoadPct, signal).then((frames) => {
      if (signal.cancelled) return
      framesRef.current = frames
      setReady(true)
    })

    return () => {
      signal.cancelled = true
    }
  }, [variant])

  useGSAP(
    () => {
      const section = sectionRef.current
      const canvas = canvasRef.current
      if (!section || !canvas || !ready) return

      const touch = isTouchDevice()
      const ctx = canvas.getContext('2d', {
        alpha: false,
        desynchronized: true,
        // Prefer speed over readback on mobile GPUs
        willReadFrequently: false,
      })
      if (!ctx) return
      ctx.imageSmoothingEnabled = true
      ctx.imageSmoothingQuality = touch ? 'medium' : 'high'

      // Smooths touch scrolling with pinned scrub on iOS/Android
      const normalizer = touch
        ? ScrollTrigger.normalizeScroll({
            allowNestedScroll: true,
            lockAxis: false,
            type: 'touch,wheel,pointer',
          })
        : null

      const resizeCanvas = () => {
        // Cap DPR on phones — 3x canvases are a common stutter source
        const dpr = Math.min(window.devicePixelRatio || 1, touch ? 1.5 : 2)
        const w = section.clientWidth
        const h = section.clientHeight
        canvas.width = Math.floor(w * dpr)
        canvas.height = Math.floor(h * dpr)
        canvas.style.width = `${w}px`
        canvas.style.height = `${h}px`
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
        drawnFrameRef.current = -1
        lastWidthRef.current = window.innerWidth
      }

      const paint = (frameIndex: number) => {
        const idx = Math.max(0, Math.min(FRAME_COUNT - 1, frameIndex))
        if (idx === drawnFrameRef.current) return
        const img = framesRef.current[idx]
        if (!img) return

        const w = section.clientWidth
        const h = section.clientHeight
        drawCover(ctx, img, w, h)
        drawnFrameRef.current = idx
      }

      const pxPerFrame = variant === 'portrait' ? 9 : 11
      const st = ScrollTrigger.create({
        trigger: section,
        start: 'top top',
        end: () => `+=${FRAME_COUNT * pxPerFrame}`,
        pin: true,
        // Fixed pin is more stable on mobile browsers than transform pinning
        pinType: touch ? 'fixed' : 'transform',
        scrub: true,
        anticipatePin: touch ? 0 : 1,
        invalidateOnRefresh: true,
        fastScrollEnd: true,
        preventOverlaps: true,
        onUpdate: (self) => {
          paint(Math.round(self.progress * (FRAME_COUNT - 1)))
        },
      })

      resizeCanvas()
      paint(0)

      const onOrientation = () => {
        // Only hard-refresh after orientation settles
        window.setTimeout(() => {
          resizeCanvas()
          ScrollTrigger.refresh()
          paint(Math.round(st.progress * (FRAME_COUNT - 1)))
        }, 250)
      }

      const onResize = () => {
        // Ignore height-only changes (mobile URL bar). Refresh only on real width changes.
        const width = window.innerWidth
        if (Math.abs(width - lastWidthRef.current) < 2) return
        resizeCanvas()
        ScrollTrigger.refresh()
        paint(Math.round(st.progress * (FRAME_COUNT - 1)))
      }

      window.addEventListener('resize', onResize, { passive: true })
      window.addEventListener('orientationchange', onOrientation)

      return () => {
        window.removeEventListener('resize', onResize)
        window.removeEventListener('orientationchange', onOrientation)
        normalizer?.kill()
        st.kill()
      }
    },
    { dependencies: [ready, variant], scope: sectionRef },
  )

  return (
    <section className="video-scroll" ref={sectionRef} aria-label="Scroll sequence">
      <div className="video-scroll__stage">
        <canvas ref={canvasRef} className="video-scroll__media" />

        {!ready && (
          <div className="video-scroll__loader" aria-live="polite">
            <p className="video-scroll__loader-pct">{loadPct}%</p>
          </div>
        )}
      </div>
    </section>
  )
}

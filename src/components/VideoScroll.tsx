import { useEffect, useRef, useState } from 'react'
import { gsap } from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import { useGSAP } from '@gsap/react'
import { copy } from '../content/copy'

gsap.registerPlugin(ScrollTrigger, useGSAP)

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
      if (i < FRAME_COUNT) window.setTimeout(pump, 0)
    }
    pump()
  })
}

export function VideoScroll() {
  const sectionRef = useRef<HTMLElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const heroRef = useRef<HTMLDivElement>(null)
  const beatRefs = useRef<(HTMLElement | null)[]>([])
  const framesRef = useRef<(HTMLImageElement | null)[]>([])
  const drawnFrameRef = useRef(-1)
  const activeBeatRef = useRef(-1)
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
        willReadFrequently: false,
      })
      if (!ctx) return
      ctx.imageSmoothingEnabled = true
      ctx.imageSmoothingQuality = touch ? 'medium' : 'high'

      const normalizer = touch
        ? ScrollTrigger.normalizeScroll({
            allowNestedScroll: true,
            lockAxis: false,
            type: 'touch,wheel,pointer',
          })
        : null

      const resizeCanvas = () => {
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
        drawCover(ctx, img, section.clientWidth, section.clientHeight)
        drawnFrameRef.current = idx
      }

      const setHero = (visible: boolean) => {
        heroRef.current?.classList.toggle('is-visible', visible)
      }

      const setBeat = (index: number) => {
        if (activeBeatRef.current === index) return
        activeBeatRef.current = index
        beatRefs.current.forEach((el, i) => {
          el?.classList.toggle('is-active', i === index)
        })
      }

      const syncCopy = (progress: number) => {
        setHero(progress < 0.04)
        let next = -1
        if (progress >= 0.04) {
          copy.scrollBeats.forEach((beat, i) => {
            if (progress >= beat.at) next = i
          })
        }
        setBeat(next)
      }

      const pxPerFrame = variant === 'portrait' ? 9 : 11
      const st = ScrollTrigger.create({
        trigger: section,
        start: 'top top',
        end: () => `+=${FRAME_COUNT * pxPerFrame}`,
        pin: true,
        pinType: touch ? 'fixed' : 'transform',
        scrub: true,
        anticipatePin: touch ? 0 : 1,
        invalidateOnRefresh: true,
        fastScrollEnd: true,
        preventOverlaps: true,
        onUpdate: (self) => {
          paint(Math.round(self.progress * (FRAME_COUNT - 1)))
          syncCopy(self.progress)
        },
      })

      resizeCanvas()
      paint(0)
      syncCopy(0)

      const onOrientation = () => {
        window.setTimeout(() => {
          resizeCanvas()
          ScrollTrigger.refresh()
          paint(Math.round(st.progress * (FRAME_COUNT - 1)))
          syncCopy(st.progress)
        }, 250)
      }

      const onResize = () => {
        const width = window.innerWidth
        if (Math.abs(width - lastWidthRef.current) < 2) return
        resizeCanvas()
        ScrollTrigger.refresh()
        paint(Math.round(st.progress * (FRAME_COUNT - 1)))
        syncCopy(st.progress)
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

        <div className="video-scroll__veil" aria-hidden />

        <div className={`video-scroll__hero ${ready ? 'is-visible' : ''}`} ref={heroRef}>
          <p className="video-scroll__brand">{copy.hero.brand}</p>
          <h1 className="video-scroll__line">{copy.hero.line}</h1>
          <p className="video-scroll__support">{copy.hero.support}</p>
          <div className="video-scroll__hint">
            <span>{copy.hero.scrollHint}</span>
            <span className="video-scroll__hint-line" />
          </div>
        </div>

        <div className="video-scroll__beats" aria-live="polite">
          {copy.scrollBeats.map((beat, i) => (
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
      </div>
    </section>
  )
}

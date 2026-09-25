import { useEffect, useRef, useState } from 'react'
import { gsap } from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import { useGSAP } from '@gsap/react'
import { copy } from '../content/copy'

gsap.registerPlugin(ScrollTrigger, useGSAP)

const FRAME_COUNT = 240
const frameSrc = (index: number) =>
  `/media/sequence/frame-${String(index + 1).padStart(3, '0')}.jpg`

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
  const dx = (width - dw) / 2
  const dy = (height - dh) / 2
  ctx.clearRect(0, 0, width, height)
  ctx.drawImage(img, dx, dy, dw, dh)
}

export function VideoScroll() {
  const sectionRef = useRef<HTMLElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const progressRef = useRef<HTMLDivElement>(null)
  const heroRef = useRef<HTMLDivElement>(null)
  const beatRefs = useRef<(HTMLElement | null)[]>([])
  const framesRef = useRef<(HTMLImageElement | null)[]>([])
  const activeBeatRef = useRef(-1)
  const drawnFrameRef = useRef(-1)
  const [ready, setReady] = useState(false)
  const [loadPct, setLoadPct] = useState(0)

  useEffect(() => {
    let cancelled = false
    const frames: (HTMLImageElement | null)[] = Array(FRAME_COUNT).fill(null)
    framesRef.current = frames

    let loaded = 0
    const bump = () => {
      loaded += 1
      if (!cancelled) {
        setLoadPct(Math.round((loaded / FRAME_COUNT) * 100))
        // Ready once we have the first stretch — rest continues loading
        if (loaded >= Math.min(36, FRAME_COUNT)) setReady(true)
      }
    }

    for (let i = 0; i < FRAME_COUNT; i++) {
      const img = new Image()
      img.decoding = 'async'
      img.src = frameSrc(i)
      img.onload = () => {
        frames[i] = img
        bump()
      }
      img.onerror = () => bump()
    }

    return () => {
      cancelled = true
    }
  }, [])

  useGSAP(
    () => {
      const section = sectionRef.current
      const canvas = canvasRef.current
      if (!section || !canvas || !ready) return

      const ctx = canvas.getContext('2d', { alpha: false })
      if (!ctx) return

      const resize = () => {
        const dpr = Math.min(window.devicePixelRatio || 1, 2)
        const w = section.clientWidth
        const h = section.clientHeight
        canvas.width = Math.floor(w * dpr)
        canvas.height = Math.floor(h * dpr)
        canvas.style.width = `${w}px`
        canvas.style.height = `${h}px`
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
        // Force redraw on resize
        drawnFrameRef.current = -1
      }
      resize()
      window.addEventListener('resize', resize)

      const paint = (frameIndex: number) => {
        const idx = Math.max(0, Math.min(FRAME_COUNT - 1, frameIndex))
        if (idx === drawnFrameRef.current) return

        const img = framesRef.current[idx]
        if (!img) {
          // Fallback to nearest loaded frame
          for (let d = 1; d < FRAME_COUNT; d++) {
            const a = framesRef.current[idx - d]
            const b = framesRef.current[idx + d]
            if (a) {
              drawCover(ctx, a, section.clientWidth, section.clientHeight)
              drawnFrameRef.current = idx - d
              return
            }
            if (b) {
              drawCover(ctx, b, section.clientWidth, section.clientHeight)
              drawnFrameRef.current = idx + d
              return
            }
          }
          return
        }

        drawCover(ctx, img, section.clientWidth, section.clientHeight)
        drawnFrameRef.current = idx
      }

      // Draw opening frame
      paint(0)

      let target = 0
      let current = 0
      const ease = 0.065 // lower = silkier catch-up (reference feel)

      const setBeat = (index: number) => {
        if (activeBeatRef.current === index) return
        activeBeatRef.current = index
        beatRefs.current.forEach((el, i) => {
          el?.classList.toggle('is-active', i === index)
        })
      }

      const setHero = (visible: boolean) => {
        heroRef.current?.classList.toggle('is-visible', visible)
      }

      const st = ScrollTrigger.create({
        trigger: section,
        start: 'top top',
        end: '+=900%',
        pin: true,
        scrub: true,
        anticipatePin: 1,
        onUpdate: (self) => {
          target = self.progress
        },
      })

      const tick = () => {
        current += (target - current) * ease
        // Snap when nearly there to avoid endless micro-lerp
        if (Math.abs(target - current) < 0.00015) current = target

        const frameIndex = Math.round(current * (FRAME_COUNT - 1))
        paint(frameIndex)

        if (progressRef.current) {
          progressRef.current.style.transform = `scaleX(${current})`
        }

        // Hero only at the very start — never stack with side captions
        setHero(current < 0.035)

        let next = -1
        if (current >= 0.04) {
          copy.scrollBeats.forEach((beat, i) => {
            if (current >= beat.at) next = i
          })
        }
        setBeat(next)
      }

      gsap.ticker.add(tick)

      return () => {
        gsap.ticker.remove(tick)
        window.removeEventListener('resize', resize)
        st.kill()
      }
    },
    { dependencies: [ready], scope: sectionRef },
  )

  return (
    <section className="video-scroll" ref={sectionRef} aria-label="Arrival sequence">
      <div className="video-scroll__stage">
        <canvas ref={canvasRef} className="video-scroll__media" />

        {!ready && (
          <div className="video-scroll__loader" aria-live="polite">
            <p className="video-scroll__brand">AURELIA</p>
            <p className="video-scroll__loader-pct">{loadPct}%</p>
          </div>
        )}

        <div className="video-scroll__veil" />
        <div className="video-scroll__grain" aria-hidden />

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

        <div className="video-scroll__progress" aria-hidden>
          <div className="video-scroll__progress-bar" ref={progressRef} />
        </div>
      </div>
    </section>
  )
}

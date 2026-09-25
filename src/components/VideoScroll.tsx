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
  ctx.drawImage(img, (width - dw) / 2, (height - dh) / 2, dw, dh)
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
      if (cancelled) return
      setLoadPct(Math.round((loaded / FRAME_COUNT) * 100))
      if (loaded >= FRAME_COUNT) setReady(true)
    }

    for (let i = 0; i < FRAME_COUNT; i++) {
      const img = new Image()
      img.decoding = 'async'
      img.src = frameSrc(i)
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

    return () => {
      cancelled = true
    }
  }, [])

  useGSAP(
    () => {
      const section = sectionRef.current
      const canvas = canvasRef.current
      if (!section || !canvas || !ready) return

      const ctx = canvas.getContext('2d', { alpha: false, desynchronized: true })
      if (!ctx) return
      // Crisp pixels — no soft resampling haze
      ctx.imageSmoothingEnabled = true
      ctx.imageSmoothingQuality = 'high'

      const resize = () => {
        const dpr = Math.min(window.devicePixelRatio || 1, 2)
        const w = section.clientWidth
        const h = section.clientHeight
        canvas.width = Math.floor(w * dpr)
        canvas.height = Math.floor(h * dpr)
        canvas.style.width = `${w}px`
        canvas.style.height = `${h}px`
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
        drawnFrameRef.current = -1
      }

      const paint = (frameIndex: number) => {
        const idx = Math.max(0, Math.min(FRAME_COUNT - 1, frameIndex))
        if (idx === drawnFrameRef.current) return
        const img = framesRef.current[idx]
        if (!img) return

        const w = section.clientWidth
        const h = section.clientHeight
        ctx.globalAlpha = 1
        ctx.fillStyle = '#0c0e0d'
        ctx.fillRect(0, 0, w, h)
        drawCover(ctx, img, w, h)
        drawnFrameRef.current = idx
      }

      // ~11px of scroll per frame → camera advances one clear step at a time
      const pxPerFrame = 11
      const st = ScrollTrigger.create({
        trigger: section,
        start: 'top top',
        end: () => `+=${FRAME_COUNT * pxPerFrame}`,
        pin: true,
        scrub: true,
        anticipatePin: 1,
        onUpdate: (self) => {
          const frame = Math.round(self.progress * (FRAME_COUNT - 1))
          paint(frame)

          if (progressRef.current) {
            progressRef.current.style.transform = `scaleX(${self.progress})`
          }

          const p = self.progress
          heroRef.current?.classList.toggle('is-visible', p < 0.03)

          let next = -1
          if (p >= 0.035) {
            copy.scrollBeats.forEach((beat, i) => {
              if (p >= beat.at) next = i
            })
          }
          if (activeBeatRef.current !== next) {
            activeBeatRef.current = next
            beatRefs.current.forEach((el, i) => {
              el?.classList.toggle('is-active', i === next)
            })
          }
        },
      })

      resize()
      paint(0)

      const onResize = () => {
        resize()
        paint(Math.round(st.progress * (FRAME_COUNT - 1)))
      }
      window.addEventListener('resize', onResize)

      return () => {
        window.removeEventListener('resize', onResize)
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
            <p className="video-scroll__loader-pct">Preparing {loadPct}%</p>
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

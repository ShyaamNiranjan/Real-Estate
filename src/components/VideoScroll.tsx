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
  img: CanvasImageSource,
  width: number,
  height: number,
  iw: number,
  ih: number,
) {
  if (!iw || !ih) return
  const scale = Math.max(width / iw, height / ih)
  const dw = iw * scale
  const dh = ih * scale
  const dx = (width - dw) / 2
  const dy = (height - dh) / 2
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
      const pct = Math.round((loaded / FRAME_COUNT) * 100)
      setLoadPct(pct)
      // Wait for every frame — missing frames are what makes scrub feel choppy
      if (loaded >= FRAME_COUNT) setReady(true)
    }

    // Load in waves so early frames decode first, then fill the rest
    const loadOne = (i: number) => {
      const img = new Image()
      img.decoding = 'async'
      img.src = frameSrc(i)
      const done = () => {
        frames[i] = img
        bump()
      }
      img.onload = () => {
        if (img.decode) {
          img.decode().then(done).catch(done)
        } else {
          done()
        }
      }
      img.onerror = () => bump()
    }

    for (let i = 0; i < FRAME_COUNT; i++) loadOne(i)

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
      }
      resize()
      window.addEventListener('resize', resize)

      const paintBlended = (exact: number) => {
        const max = FRAME_COUNT - 1
        const clamped = Math.max(0, Math.min(max, exact))
        const i0 = Math.floor(clamped)
        const i1 = Math.min(max, i0 + 1)
        const t = clamped - i0

        const a = framesRef.current[i0]
        const b = framesRef.current[i1]
        const w = section.clientWidth
        const h = section.clientHeight

        ctx.globalAlpha = 1
        ctx.fillStyle = '#0c0e0d'
        ctx.fillRect(0, 0, w, h)

        if (a) {
          ctx.globalAlpha = 1
          drawCover(ctx, a, w, h, a.naturalWidth, a.naturalHeight)
        }

        // Crossfade into the next frame — removes hard frame pops
        if (b && t > 0.001 && i1 !== i0) {
          ctx.globalAlpha = t
          drawCover(ctx, b, w, h, b.naturalWidth, b.naturalHeight)
          ctx.globalAlpha = 1
        }
      }

      paintBlended(0)

      let target = 0
      let current = 0
      // Higher = snappier; lower = silkier. Tuned for Apple-page feel with Lenis.
      const smoothing = 7.5

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
        end: '+=1100%',
        pin: true,
        scrub: true,
        anticipatePin: 1,
        onUpdate: (self) => {
          target = self.progress
        },
      })

      const tick = () => {
        const dt = Math.min(0.05, gsap.ticker.deltaRatio(60) / 60)
        // Frame-rate independent exponential smooth damp
        const alpha = 1 - Math.exp(-smoothing * dt)
        current += (target - current) * alpha
        if (Math.abs(target - current) < 0.00008) current = target

        paintBlended(current * (FRAME_COUNT - 1))

        if (progressRef.current) {
          progressRef.current.style.transform = `scaleX(${current})`
        }

        setHero(current < 0.03)

        let next = -1
        if (current >= 0.035) {
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

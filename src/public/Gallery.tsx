import { useCallback, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import { track } from '../lib/analytics'

export type GalleryImage = { src: string; alt: string }

/** Horizontal scroller with a drawn progress bar (native bars are hidden on iOS) and mouse drag. */
function useStrip(count: number) {
  const trackRef = useRef<HTMLDivElement>(null)
  const barRef = useRef<HTMLDivElement>(null)
  const [thumb, setThumb] = useState({ size: 1, start: 0 })
  const drag = useRef({ active: false, x: 0, left: 0, moved: 0 })

  useEffect(() => {
    const el = trackRef.current
    if (!el) return
    const update = () => {
      const size = el.scrollWidth ? Math.min(1, el.clientWidth / el.scrollWidth) : 1
      const max = el.scrollWidth - el.clientWidth
      setThumb({ size, start: max > 0 ? (el.scrollLeft / max) * (1 - size) : 0 })
    }
    update()
    el.addEventListener('scroll', update, { passive: true })
    const ro = new ResizeObserver(update)
    ro.observe(el)
    el.querySelectorAll('img').forEach((img) => img.addEventListener('load', update))
    return () => {
      el.removeEventListener('scroll', update)
      ro.disconnect()
    }
  }, [count])

  const dragHandlers = {
    onPointerDown: (e: ReactPointerEvent<HTMLDivElement>) => {
      if (e.pointerType !== 'mouse' || e.button !== 0) return
      drag.current = { active: true, x: e.clientX, left: e.currentTarget.scrollLeft, moved: 0 }
    },
    onPointerMove: (e: ReactPointerEvent<HTMLDivElement>) => {
      const d = drag.current
      if (!d.active) return
      const dx = e.clientX - d.x
      d.moved = Math.max(d.moved, Math.abs(dx))
      if (d.moved > 4) {
        e.currentTarget.classList.add('is-dragging')
        e.currentTarget.scrollLeft = d.left - dx
      }
    },
    onPointerUp: (e: ReactPointerEvent<HTMLDivElement>) => {
      drag.current.active = false
      e.currentTarget.classList.remove('is-dragging')
    },
    onPointerLeave: (e: ReactPointerEvent<HTMLDivElement>) => {
      drag.current.active = false
      e.currentTarget.classList.remove('is-dragging')
    },
  }

  const onBarPointerDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    const el = trackRef.current
    const bar = barRef.current
    if (!el || !bar) return
    const seek = (clientX: number) => {
      const r = bar.getBoundingClientRect()
      const ratio = Math.min(1, Math.max(0, (clientX - r.left) / r.width))
      el.scrollLeft = ratio * el.scrollWidth - el.clientWidth / 2
    }
    seek(e.clientX)
    const move = (ev: PointerEvent) => seek(ev.clientX)
    const up = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }

  return {
    trackRef,
    barRef,
    thumb,
    overflow: thumb.size < 0.999,
    dragHandlers,
    onBarPointerDown,
    dragged: () => drag.current.moved > 4,
  }
}

export function Gallery({ images }: { images: GalleryImage[] }) {
  const [open, setOpen] = useState<number | null>(null)
  const dialogRef = useRef<HTMLDialogElement>(null)

  const show = (i: number) => {
    track('gallery_open')
    setOpen(i)
    dialogRef.current?.showModal()
  }
  const close = useCallback(() => {
    dialogRef.current?.close()
  }, [])
  const step = useCallback(
    (d: number) => setOpen((i) => (i === null ? i : (i + d + images.length) % images.length)),
    [images.length],
  )

  useEffect(() => {
    if (open === null) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'ArrowRight') step(1)
      if (e.key === 'ArrowLeft') step(-1)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, step])

  const strip = useStrip(images.length)

  if (!images.length) return null

  return (
    <>
      <div className="gallery-strip">
        <div className="gallery-strip__track" ref={strip.trackRef} {...strip.dragHandlers}>
          {images.map((img, i) => (
            <button
              key={`${img.src}-${i}`}
              type="button"
              className="gallery-strip__item"
              onClick={() => !strip.dragged() && show(i)}
              aria-label={`Open image ${i + 1} of ${images.length}`}
            >
              <img src={img.src} alt={img.alt} loading="lazy" decoding="async" draggable={false} />
            </button>
          ))}
        </div>
        {strip.overflow && (
          <div className="gallery-strip__bar" ref={strip.barRef} onPointerDown={strip.onBarPointerDown} aria-hidden>
            <span style={{ width: `${strip.thumb.size * 100}%`, left: `${strip.thumb.start * 100}%` }} />
          </div>
        )}
      </div>

      <dialog ref={dialogRef} className="lightbox" onClose={() => setOpen(null)} onClick={(e) => e.target === e.currentTarget && close()}>
        {open !== null && (
          <figure className="lightbox__figure">
            <img src={images[open].src} alt={images[open].alt} />
            <figcaption>
              {String(open + 1).padStart(2, '0')} / {String(images.length).padStart(2, '0')}
            </figcaption>
          </figure>
        )}
        <button type="button" className="lightbox__close" onClick={close} aria-label="Close">
          Close
        </button>
        {images.length > 1 && (
          <>
            <button type="button" className="lightbox__nav lightbox__nav--prev" onClick={() => step(-1)} aria-label="Previous image">
              <span className="arrow arrow--left" aria-hidden />
            </button>
            <button type="button" className="lightbox__nav lightbox__nav--next" onClick={() => step(1)} aria-label="Next image">
              <span className="arrow" aria-hidden />
            </button>
          </>
        )}
      </dialog>
    </>
  )
}

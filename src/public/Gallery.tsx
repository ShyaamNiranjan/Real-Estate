import { useCallback, useEffect, useRef, useState } from 'react'

export type GalleryImage = { src: string; alt: string }

export function Gallery({ images }: { images: GalleryImage[] }) {
  const [open, setOpen] = useState<number | null>(null)
  const dialogRef = useRef<HTMLDialogElement>(null)

  const show = (i: number) => {
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

  if (!images.length) return null

  return (
    <>
      <div className="gallery">
        {images.map((img, i) => (
          <button
            key={`${img.src}-${i}`}
            type="button"
            className={`gallery__item gallery__item--${i % 5 === 0 ? 'wide' : 'half'}`}
            onClick={() => show(i)}
            aria-label={`Open image ${i + 1} of ${images.length}`}
          >
            <img src={img.src} alt={img.alt} loading="lazy" decoding="async" />
          </button>
        ))}
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

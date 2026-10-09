import { useMemo, useState, type DragEvent } from 'react'
import { Link } from 'react-router-dom'
import { expandFramePattern, joinUrl } from '../lib/format'
import { fallbackHeroImage, heroImageFromFile, saveHero, useListingHero, type HeroSettings } from '../lib/listingHero'
import { useRealtor } from '../lib/realtor'
import { useSite } from '../lib/site'
import { HeroBanner, heroContent, usePreviewCurtain } from '../public/ListingHero'
import type { EditorData } from './ListingEditor'
import { errorMessage, useToast } from './ui'

type Device = 'desktop' | 'phone'

export function HeroTab({ data }: { data: EditorData }) {
  const { listing, media } = data
  const toast = useToast()
  const { listing: listingPath } = useRealtor()
  const { settings: site } = useSite()
  const hero = useListingHero(listing.id)
  const [device, setDevice] = useState<Device>('desktop')
  const [busy, setBusy] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const curtain = usePreviewCurtain()

  const content = heroContent(listing, hero)

  const frames = useMemo(() => {
    const seq = (aspect: 'landscape' | 'portrait') =>
      media.find((x) => x.kind === 'frame_sequence' && (x.aspect === 'portrait') === (aspect === 'portrait') && x.public_url && x.frame_pattern)
    const at = (m: ReturnType<typeof seq>, n: number) => (m ? joinUrl(m.public_url!, expandFramePattern(m.frame_pattern!, n)) : null)
    const land = seq('landscape')
    const port = seq('portrait')
    const main = land ?? port
    return { landscape: at(land, 1), portrait: at(port, 1), last: at(main, main?.frame_count ?? 1) }
  }, [media])
  const frameSrc = device === 'phone' ? (frames.portrait ?? frames.landscape) : (frames.landscape ?? frames.portrait)

  const gallery = media.filter((m) => m.kind === 'gallery' && m.public_url).map((m) => m.public_url!)
  const fallback = fallbackHeroImage({
    cover: listing.cover_image_url ?? gallery[0] ?? null,
    gallery,
    firstFrame: frames.landscape ?? frames.portrait,
    lastFrame: frames.last,
  })
  const image = hero.image ?? fallback.src
  const cover = fallback.src

  const commit = (next: HeroSettings) => {
    try {
      saveHero(listing.id, next)
      return true
    } catch {
      toast('This browser is out of space for the image. Try a smaller one.', 'error')
      return false
    }
  }

  const upload = async (file: File | undefined) => {
    if (!file) return
    if (!file.type.startsWith('image/')) return toast('Choose a JPG, PNG or WebP image', 'error')
    setBusy(true)
    try {
      const src = await heroImageFromFile(file)
      if (commit({ ...hero, image: src, enabled: true })) {
        toast('Hero image updated')
        curtain.replayEntrance()
      }
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setBusy(false)
    }
  }

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    void upload(e.dataTransfer.files[0])
  }

  const textRows: { label: string; value: string | null }[] = [
    { label: 'Location', value: listing.location },
    { label: 'Title', value: listing.title },
    { label: 'Tagline', value: listing.subtitle },
  ]

  return (
    <div className="a-editor a-hero-ed">
      <section className="a-card a-hero-ed__preview">
        <div className="a-card__head a-hero-ed__bar">
          <div>
            <h2 className="a-card__title">Preview</h2>
            <p className="a-muted">What a buyer sees the moment your link opens.</p>
          </div>
          <div className="a-hero-ed__controls">
            <div className="a-seg" role="radiogroup" aria-label="Preview size">
              {(['desktop', 'phone'] as Device[]).map((d) => (
                <label key={d} className={`a-seg__opt ${device === d ? 'is-on' : ''}`}>
                  <input type="radio" name="hero-device" checked={device === d} onChange={() => setDevice(d)} />
                  {d === 'desktop' ? 'Desktop' : 'Phone'}
                </label>
              ))}
            </div>
            <button type="button" className="a-btn a-btn--primary" onClick={curtain.play} disabled={!image || !hero.enabled || curtain.busy}>
              {curtain.busy ? 'Playing…' : 'Play the transition'}
            </button>
          </div>
        </div>

        <div className={`a-hero-ed__stage is-${device}`}>
          {image && hero.enabled ? (
            <div className={`a-hero-ed__device a-hero-ed__device--${device}`}>
              <HeroBanner
                key={`${device}:${image.length}`}
                content={content}
                image={image}
                frame={frameSrc ? { src: frameSrc, fills: true } : null}
                phase={curtain.phase}
                first={curtain.first}
                preview={{ brand: site.brand_name }}
              />
            </div>
          ) : (
            <div className="a-hero-ed__empty">
              <strong>{hero.enabled ? 'Add an image to see your hero banner' : 'The hero banner is off'}</strong>
              <span>{hero.enabled ? 'Upload one on the right.' : 'Buyers land straight on the first frame of the walkthrough, with your title on it.'}</span>
            </div>
          )}
        </div>
        <p className="a-hero-ed__caption">
          One scroll cuts from your banner into the first frame of the walkthrough. Scrolling back up at the start brings the banner back.{' '}
          <a href={listingPath(listing.slug)} target="_blank" rel="noreferrer" className="a-link">
            Try it on the page ↗
          </a>
        </p>
      </section>

      <aside className="a-editor__side a-hero-ed__side">
        <section className="a-card">
          <div className="a-card__head">
            <div>
              <h2 className="a-card__title">Hero banner</h2>
              <p className="a-muted">Your best photo of the home, with its name on it. It opens the page, then hands over to the walkthrough.</p>
            </div>
          </div>
          <label className="a-check">
            <input type="checkbox" checked={hero.enabled} onChange={(e) => commit({ ...hero, enabled: e.target.checked })} />
            <span>Open the page with a hero banner</span>
          </label>
        </section>

        <section className={`a-card ${hero.enabled ? '' : 'is-muted'}`}>
          <h3 className="a-hero-ed__label">Image</h3>
          {image && (
            <div className="a-hero-ed__thumb">
              <img src={image} alt="" />
              <span>{hero.image ? 'Your upload' : fallback.label}</span>
            </div>
          )}
          <label
            className={`a-drop a-drop--compact ${dragOver ? 'is-over' : ''}`}
            onDragOver={(e) => {
              e.preventDefault()
              setDragOver(true)
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={onDrop}
          >
            <input
              type="file"
              accept="image/jpeg,image/png,image/webp"
              disabled={busy}
              onChange={(e) => {
                void upload(e.target.files?.[0])
                e.target.value = ''
              }}
            />
            <strong>{busy ? 'Preparing image…' : hero.image ? 'Replace the image' : 'Upload the perfect shot'}</strong>
            <span>Landscape, 2000px wide or more. Keep the subject near the middle so it stays in view on phones.</span>
          </label>
          {hero.image && cover && (
            <button type="button" className="a-link" onClick={() => commit({ ...hero, image: null })}>
              Remove my upload
            </button>
          )}
        </section>

        <section className={`a-card ${hero.enabled ? '' : 'is-muted'}`}>
          <h3 className="a-hero-ed__label">Text on the banner</h3>
          <dl className="a-hero-ed__text">
            {textRows.map((r) => (
              <div key={r.label}>
                <dt>{r.label}</dt>
                <dd className={r.value ? '' : 'is-empty'}>{r.value || 'Not set'}</dd>
              </div>
            ))}
          </dl>
          <label className="a-check">
            <input type="checkbox" checked={hero.showFacts} onChange={(e) => commit({ ...hero, showFacts: e.target.checked })} />
            <span>Show beds, baths and size</span>
          </label>
          <label className="a-check">
            <input type="checkbox" checked={hero.showPrice} onChange={(e) => commit({ ...hero, showPrice: e.target.checked })} />
            <span>Show the guide price{listing.price_label ? '' : ' (none set)'}</span>
          </label>
          <Link to={`/studio/listings/${listing.id}/details`} className="a-link" replace>
            Edit this text in Details →
          </Link>
        </section>
        <p className="a-note">Prototype: the hero image is kept in this browser only, so it shows on your preview but not on other devices yet.</p>
      </aside>
    </div>
  )
}

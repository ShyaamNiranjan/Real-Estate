import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchPublishedListings, type ListingCard } from '../lib/api'
import { listingFacts } from '../lib/format'
import { useDocumentTitle, useSite } from '../lib/site'
import { EnquiryForm } from './EnquiryForm'
import { SiteFooter } from './SiteFooter'
import { SiteHeader } from './SiteHeader'
import { useReveal } from './useReveal'

export function Marketplace() {
  useDocumentTitle(null)
  const { settings } = useSite()
  const [listings, setListings] = useState<ListingCard[] | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let active = true
    fetchPublishedListings()
      .then((rows) => active && setListings(rows))
      .catch((err) => {
        console.error(err)
        if (active) {
          setFailed(true)
          setListings([])
        }
      })
    return () => {
      active = false
    }
  }, [])

  return (
    <div className="page page--home">
      <SiteHeader variant="home" />
      <Hero
        brand={settings.brand_name}
        headline={settings.hero_headline ?? ''}
        body={settings.hero_body ?? ''}
        image={settings.hero_image_url ?? '/media/sequence/frame-001.jpg'}
        cta={settings.hero_cta_label ?? 'View the collection'}
      />
      <Collection listings={listings} failed={failed} />
      <Approach />
      <Contact />
      <SiteFooter />
    </div>
  )
}

function Hero(props: { brand: string; headline: string; body: string; image: string; cta: string }) {
  const mediaRef = useRef<HTMLDivElement>(null)

  // Scroll polish: the photograph drifts slower than the page as you leave the hero.
  useEffect(() => {
    const el = mediaRef.current
    if (!el || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    let raf = 0
    const update = () => {
      raf = 0
      const y = Math.min(window.scrollY, window.innerHeight * 1.2)
      el.style.transform = `translate3d(0, ${y * 0.28}px, 0)`
    }
    const onScroll = () => {
      if (!raf) raf = requestAnimationFrame(update)
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => {
      window.removeEventListener('scroll', onScroll)
      if (raf) cancelAnimationFrame(raf)
    }
  }, [])

  return (
    <section className="hero" aria-labelledby="hero-title">
      <div className="hero__media" ref={mediaRef} aria-hidden>
        <img src={props.image} alt="" fetchPriority="high" decoding="async" />
      </div>
      <div className="hero__veil" aria-hidden />
      <div className="hero__grain" aria-hidden />

      <div className="hero__content">
        <p className="hero__brand" aria-label={props.brand}>
          {props.brand.split('').map((ch, i) => (
            <span key={i} style={{ animationDelay: `${0.25 + i * 0.06}s` }} aria-hidden>
              {ch}
            </span>
          ))}
        </p>
        <div className="hero__copy">
          <h1 id="hero-title" className="hero__headline">
            {props.headline}
          </h1>
          <p className="hero__body">{props.body}</p>
          <a
            href="#collection"
            className="hero__cta"
            onClick={(e) => {
              e.preventDefault()
              document.getElementById('collection')?.scrollIntoView({ behavior: 'smooth' })
            }}
          >
            <span>{props.cta}</span>
            <span className="arrow arrow--down" aria-hidden />
          </a>
        </div>
      </div>
    </section>
  )
}

function Collection({ listings, failed }: { listings: ListingCard[] | null; failed: boolean }) {
  const headRef = useReveal<HTMLDivElement>()
  const count = listings?.length ?? 0

  return (
    <section className="collection" id="collection" aria-labelledby="collection-title">
      <div className="collection__inner">
        <div className="collection__head reveal" ref={headRef}>
          <h2 id="collection-title" className="collection__title">
            The collection
          </h2>
          <p className="collection__count">
            {listings === null ? '—' : String(count).padStart(2, '0')}
            <span>{count === 1 ? 'residence' : 'residences'}</span>
          </p>
        </div>

        {listings === null ? (
          <div className="collection__grid" aria-busy>
            {[0, 1].map((i) => (
              <div key={i} className="tile tile--skeleton">
                <div className="tile__media" />
              </div>
            ))}
          </div>
        ) : count === 0 ? (
          <p className="collection__empty">
            {failed
              ? 'The collection could not be loaded. Please refresh in a moment.'
              : 'New residences are being prepared. Enquire below for private previews.'}
          </p>
        ) : (
          <div className={`collection__grid ${count === 1 ? 'is-single' : ''}`}>
            {listings.map((listing, i) => (
              <ListingTile key={listing.id} listing={listing} index={i} />
            ))}
          </div>
        )}
      </div>
    </section>
  )
}

function ListingTile({ listing, index }: { listing: ListingCard; index: number }) {
  const ref = useReveal<HTMLAnchorElement>()
  const facts = [listing.location, ...listingFacts(listing)].filter(Boolean)
  return (
    <Link
      to={`/listing/${listing.slug}`}
      viewTransition
      className="tile reveal-tile"
      ref={ref}
      style={{ transitionDelay: `${(index % 2) * 0.12}s` }}
    >
      <div className="tile__media">
        {listing.cover_image_url ? (
          <img src={listing.cover_image_url} alt="" loading={index < 2 ? 'eager' : 'lazy'} decoding="async" />
        ) : (
          <div className="tile__placeholder" />
        )}
        <span className="tile__enter">
          {listing.experience_type === 'immersive' ? 'Walk through' : 'View residence'}
          <span className="arrow" aria-hidden />
        </span>
      </div>
      <div className="tile__body">
        <span className="tile__index">{String(index + 1).padStart(2, '0')}</span>
        <div className="tile__text">
          <h3 className="tile__title">{listing.title}</h3>
          {listing.subtitle && <p className="tile__subtitle">{listing.subtitle}</p>}
          <p className="tile__facts">{facts.join('  ·  ')}</p>
        </div>
        <div className="tile__aside">
          {listing.price_label && <p className="tile__price">{listing.price_label}</p>}
          <p className="tile__kind">{listing.experience_type === 'immersive' ? 'Immersive walkthrough' : 'Photography'}</p>
        </div>
      </div>
    </Link>
  )
}

function Approach() {
  const ref = useReveal<HTMLDivElement>()
  return (
    <section className="approach" aria-label="Our approach">
      <div className="approach__inner reveal" ref={ref}>
        <p className="eyebrow">How we present a home</p>
        <p className="approach__statement">
          In sequence, in daylight, at the pace of walking through it. Arrive at the door, cross the threshold, find the
          light at the back of the house. Then decide whether to visit.
        </p>
      </div>
    </section>
  )
}

function Contact() {
  const { settings } = useSite()
  const ref = useReveal<HTMLDivElement>()
  return (
    <section className="contact" id="enquire" aria-labelledby="contact-title">
      <div className="contact__inner reveal" ref={ref}>
        <div className="contact__intro">
          <p className="eyebrow">Private enquiries</p>
          <h2 id="contact-title" className="contact__title">
            Tell us what you are looking for.
          </h2>
          <p className="contact__body">
            Viewings are arranged one at a time. Off-market residences are shared on request.
          </p>
          {settings.contact_email && (
            <a className="contact__email" href={`mailto:${settings.contact_email}`}>
              {settings.contact_email}
            </a>
          )}
          {settings.contact_phone && (
            <a className="contact__phone" href={`tel:${settings.contact_phone.replace(/\s+/g, '')}`}>
              {settings.contact_phone}
            </a>
          )}
        </div>
        <EnquiryForm listingId={null} tone="dark" />
      </div>
    </section>
  )
}

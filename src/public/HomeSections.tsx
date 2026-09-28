import { useEffect, useMemo, useRef, type CSSProperties, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import type { ListingCard } from '../lib/api'
import { listingFacts } from '../lib/format'
import { useSite } from '../lib/site'
import { asObject, HOME_ANCHORS, type HomeContent, type HomeItem, type SectionStyle, type SectionTone } from '../types/content'
import type { HomeSectionPreset, HomeSectionRow } from '../types/database'
import { EnquiryForm } from './EnquiryForm'
import { FrameLoop, loopFrameUrl } from './FrameLoop'
import { prefersReducedMotion, SAFE_HREF, scrollToAnchor } from './links'
import { Paragraphs } from './Sections'
import { useReveal } from './useReveal'

const DEFAULT_TONE: Partial<Record<HomeSectionPreset, SectionTone>> = {
  walkthrough: 'dark',
  stats: 'dark',
  services: 'light',
  neighbourhoods: 'dark',
  testimonials: 'stone',
}

function fallbackRow(preset: HomeSectionPreset, sort_order: number, fields: Partial<HomeSectionRow>): HomeSectionRow {
  return {
    id: `fallback-${preset}`,
    preset,
    sort_order,
    is_visible: true,
    title: null,
    body: null,
    content: {},
    style: {},
    created_at: '',
    updated_at: '',
    ...fields,
  }
}

/** Shown while the page loads, so the collection skeleton holds the space below the hero. */
export const LOADING_SECTIONS: HomeSectionRow[] = [fallbackRow('collection', 0, { title: 'The collection' })]

/** Used when home sections cannot be loaded (e.g. the migration has not been applied yet). */
export const FALLBACK_SECTIONS: HomeSectionRow[] = [
  LOADING_SECTIONS[0],
  fallbackRow('approach', 1, {
    body: 'In sequence, in daylight, at the pace of walking through it. Arrive at the door, cross the threshold, find the light at the back of the house. Then decide whether to visit.',
    content: { eyebrow: 'How we present a home' },
  }),
  fallbackRow('contact', 2, {
    title: 'Tell us what you are looking for.',
    body: 'Viewings are arranged one at a time. Off-market residences are shared on request.',
    content: { eyebrow: 'Private enquiries' },
  }),
]

type Props = {
  sections: HomeSectionRow[]
  listings: ListingCard[] | null
  failed: boolean
}

export function HomeSections({ sections, listings, failed }: Props) {
  return (
    <>
      {sections.map((section) => (
        // Keyed by preset for the collection so the loading skeleton and the loaded row are one instance.
        <HomeSection
          key={section.preset === 'collection' ? 'collection' : section.id}
          section={section}
          listings={listings}
          failed={failed}
        />
      ))}
    </>
  )
}

function HomeSection({ section, listings, failed }: { section: HomeSectionRow; listings: ListingCard[] | null; failed: boolean }) {
  const content = asObject<HomeContent>(section.content)
  const style = asObject<SectionStyle>(section.style)
  const items = (Array.isArray(content.items) ? content.items : []).filter((item) => item && typeof item === 'object')
  const tone = style.tone ?? DEFAULT_TONE[section.preset] ?? 'dark'

  switch (section.preset) {
    case 'collection':
      return <Collection title={section.title || 'The collection'} listings={listings} failed={failed} />
    case 'approach':
      return section.body ? <Approach eyebrow={content.eyebrow} statement={section.body} /> : null
    case 'contact':
      return <Contact eyebrow={content.eyebrow} title={section.title} body={section.body} />
    case 'walkthrough':
      return <Walkthrough section={section} content={content} tone={tone} />
    case 'stats':
      return items.length ? <Stats section={section} content={content} items={items} tone={tone} /> : null
    case 'services':
      return items.length ? <Services section={section} content={content} items={items} tone={tone} /> : null
    case 'neighbourhoods':
      return items.length ? <Neighbourhoods section={section} content={content} items={items} tone={tone} /> : null
    case 'testimonials':
      return items.length ? <Testimonials section={section} content={content} items={items} tone={tone} /> : null
    default:
      return null
  }
}

// Shared ---------------------------------------------------------------------

function Shell({
  preset,
  tone,
  labelledBy,
  label,
  children,
}: {
  preset: HomeSectionPreset
  tone: SectionTone
  labelledBy?: string
  label?: string
  children: ReactNode
}) {
  return (
    <section
      id={HOME_ANCHORS[preset]}
      className={`home-sec home-sec--${preset} tone-${tone}`}
      aria-labelledby={labelledBy}
      aria-label={labelledBy ? undefined : label}
    >
      <div className="home-sec__inner">{children}</div>
    </section>
  )
}

function Head({ id, eyebrow, title, body }: { id: string; eyebrow?: string; title: string | null; body: string | null }) {
  const ref = useReveal<HTMLDivElement>()
  if (!eyebrow && !title && !body) return null
  return (
    <div className="home-head reveal" ref={ref}>
      <div>
        {eyebrow && <p className="eyebrow">{eyebrow}</p>}
        {title && (
          <h2 id={id} className="home-head__title">
            {title}
          </h2>
        )}
      </div>
      {body && <p className="home-head__body">{body}</p>}
    </div>
  )
}

function CtaLink({ href, label }: { href: string; label: string }) {
  const inner = (
    <>
      <span>{label}</span>
      <span className="arrow" aria-hidden />
    </>
  )
  if (href.startsWith('/') && !href.startsWith('//')) {
    return (
      <Link to={href} viewTransition className="button">
        {inner}
      </Link>
    )
  }
  if (href.startsWith('#')) {
    return (
      <a
        href={href}
        className="button"
        onClick={(e) => {
          if (scrollToAnchor(href.slice(1))) e.preventDefault()
        }}
      >
        {inner}
      </a>
    )
  }
  if (!SAFE_HREF.test(href)) return null
  const external = /^https?:/i.test(href)
  return (
    <a href={href} className="button" target={external ? '_blank' : undefined} rel={external ? 'noreferrer' : undefined}>
      {inner}
    </a>
  )
}

// Collection -----------------------------------------------------------------

function Collection({ title, listings, failed }: { title: string; listings: ListingCard[] | null; failed: boolean }) {
  const headRef = useReveal<HTMLDivElement>()
  const count = listings?.length ?? 0

  return (
    <section className="collection" id="collection" aria-labelledby="collection-title">
      <div className="collection__inner">
        <div className="collection__head reveal" ref={headRef}>
          <h2 id="collection-title" className="collection__title">
            {title}
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

// Approach & contact ---------------------------------------------------------

function Approach({ eyebrow, statement }: { eyebrow?: string; statement: string }) {
  const ref = useReveal<HTMLDivElement>()
  return (
    <section className="approach" id={HOME_ANCHORS.approach} aria-label={eyebrow || 'Our approach'}>
      <div className="approach__inner reveal" ref={ref}>
        {eyebrow && <p className="eyebrow">{eyebrow}</p>}
        <p className="approach__statement">{statement}</p>
      </div>
    </section>
  )
}

function Contact({ eyebrow, title, body }: { eyebrow?: string; title: string | null; body: string | null }) {
  const { settings } = useSite()
  const ref = useReveal<HTMLDivElement>()
  return (
    <section className="contact" id={HOME_ANCHORS.contact} aria-labelledby={title ? 'contact-title' : undefined} aria-label={title ? undefined : 'Enquire'}>
      <div className="contact__inner reveal" ref={ref}>
        <div className="contact__intro">
          {eyebrow && <p className="eyebrow">{eyebrow}</p>}
          {title && (
            <h2 id="contact-title" className="contact__title">
              {title}
            </h2>
          )}
          {body && <p className="contact__body">{body}</p>}
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

// Walk before you visit ------------------------------------------------------

type PresetProps = { section: HomeSectionRow; content: HomeContent; tone: SectionTone }

function Walkthrough({ section, content, tone }: PresetProps) {
  const copyRef = useReveal<HTMLDivElement>()
  const mediaRef = useReveal<HTMLElement>()
  const frames = content.frames
  const loop = content.visual !== 'still' && frames?.baseUrl && frames.pattern && frames.count > 1 ? frames : null
  const poster = content.image || (frames?.baseUrl && frames.pattern ? loopFrameUrl(frames, 1) : null)
  const href = content.href || '/listing/aurelia'

  return (
    <Shell preset="walkthrough" tone={tone} labelledBy={section.title ? 'walkthrough-title' : undefined} label="Walk before you visit">
      <div className="walk">
        <div className="walk__copy reveal" ref={copyRef}>
          {content.eyebrow && <p className="eyebrow">{content.eyebrow}</p>}
          {section.title && (
            <h2 id="walkthrough-title" className="walk__title">
              {section.title}
            </h2>
          )}
          <Paragraphs text={section.body} className="walk__body" />
          <div className="walk__cta">
            <CtaLink href={href} label={content.ctaLabel || 'Take the walkthrough'} />
          </div>
        </div>
        <figure className="walk__media reveal-media" ref={mediaRef}>
          <div className="walk__frame">
            {loop ? (
              <FrameLoop source={loop} poster={poster} />
            ) : (
              <div className="frame-loop">{poster && <img src={poster} alt="" loading="lazy" decoding="async" />}</div>
            )}
          </div>
          {content.caption && <figcaption className="walk__caption">{content.caption}</figcaption>}
        </figure>
      </div>
    </Shell>
  )
}

// Numbers --------------------------------------------------------------------

type ListProps = PresetProps & { items: HomeItem[] }

function Stats({ section, content, items, tone }: ListProps) {
  const ref = useReveal<HTMLDListElement>()
  const stats = items.filter((item) => item.value)
  return (
    <Shell preset="stats" tone={tone} labelledBy={section.title ? 'numbers-title' : undefined} label="In numbers">
      <Head id="numbers-title" eyebrow={content.eyebrow} title={section.title} body={section.body} />
      <dl className="stats reveal" ref={ref} data-count={stats.length}>
        {stats.map((item, i) => (
          <div className="stats__item" key={i}>
            <dt>{item.label}</dt>
            <dd>
              <CountUp value={item.value!} />
            </dd>
          </div>
        ))}
      </dl>
    </Shell>
  )
}

function parseStat(value: string) {
  const m = value.match(/^(\D*?)(\d[\d,]*(?:\.\d+)?)(.*)$/)
  if (!m) return null
  const [, prefix, digits, suffix] = m
  const decimals = digits.split('.')[1]?.length ?? 0
  const format = new Intl.NumberFormat('en-IN', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
    useGrouping: digits.includes(','),
  })
  return { prefix, suffix, target: Number(digits.replace(/,/g, '')), format: (n: number) => format.format(n) }
}

const COUNT_MS = 1600

/** Counts up from zero the first time it scrolls into view; the final value reserves the width. */
function CountUp({ value }: { value: string }) {
  const ref = useRef<HTMLSpanElement>(null)
  const stat = useMemo(() => parseStat(value), [value])
  const initial = stat && !prefersReducedMotion() ? `${stat.prefix}${stat.format(0)}${stat.suffix}` : value

  useEffect(() => {
    const el = ref.current
    if (!el || !stat) return
    if (prefersReducedMotion() || !('IntersectionObserver' in window)) {
      el.textContent = value
      return
    }
    let raf = 0
    const run = () => {
      const start = performance.now()
      const frame = (now: number) => {
        const t = Math.min(1, (now - start) / COUNT_MS)
        const eased = 1 - Math.pow(1 - t, 3)
        el.textContent = t < 1 ? `${stat.prefix}${stat.format(stat.target * eased)}${stat.suffix}` : value
        if (t < 1) raf = requestAnimationFrame(frame)
      }
      raf = requestAnimationFrame(frame)
    }
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          io.disconnect()
          run()
        }
      },
      { rootMargin: '0px 0px -12% 0px', threshold: 0.4 },
    )
    io.observe(el)
    return () => {
      io.disconnect()
      if (raf) cancelAnimationFrame(raf)
    }
  }, [stat, value])

  return (
    <span className="count">
      <span className="count__ghost" aria-hidden>
        {value}
      </span>
      <span className="count__live" ref={ref} aria-hidden>
        {initial}
      </span>
      <span className="visually-hidden">{value}</span>
    </span>
  )
}

// Services -------------------------------------------------------------------

function Services({ section, content, items, tone }: ListProps) {
  return (
    <Shell preset="services" tone={tone} labelledBy={section.title ? 'services-title' : undefined} label="Services">
      <Head id="services-title" eyebrow={content.eyebrow} title={section.title} body={section.body} />
      <ol className="services">
        {items
          .filter((item) => item.title)
          .map((item, i) => (
            <ServiceRow key={i} item={item} index={i} />
          ))}
      </ol>
    </Shell>
  )
}

function ServiceRow({ item, index }: { item: HomeItem; index: number }) {
  const ref = useReveal<HTMLLIElement>()
  return (
    <li className="services__row reveal" ref={ref} style={{ transitionDelay: `${index * 0.08}s` }}>
      <span className="services__index">{String(index + 1).padStart(2, '0')}</span>
      <h3 className="services__title">{item.title}</h3>
      {item.body && <p className="services__body">{item.body}</p>}
    </li>
  )
}

// Neighbourhoods -------------------------------------------------------------

/** Placeholder art per tile: [contour centre x, y, gradient from, gradient to]. */
const PLACE_ART = [
  ['72%', '28%', '#2b302a', '#151916'],
  ['24%', '70%', '#332e26', '#171714'],
  ['80%', '76%', '#283033', '#131718'],
  ['30%', '24%', '#312b24', '#161614'],
  ['64%', '58%', '#2a3028', '#141814'],
  ['18%', '38%', '#302a28', '#161514'],
] as const

function Neighbourhoods({ section, content, items, tone }: ListProps) {
  return (
    <Shell preset="neighbourhoods" tone={tone} labelledBy={section.title ? 'neighbourhoods-title' : undefined} label="Neighbourhoods">
      <Head id="neighbourhoods-title" eyebrow={content.eyebrow} title={section.title} body={section.body} />
      <ul className="places">
        {items
          .filter((item) => item.title)
          .map((item, i) => (
            <Place key={i} item={item} index={i} />
          ))}
      </ul>
    </Shell>
  )
}

function Place({ item, index }: { item: HomeItem; index: number }) {
  const ref = useReveal<HTMLLIElement>()
  const [cx, cy, from, to] = PLACE_ART[index % PLACE_ART.length]
  const art = { '--cx': cx, '--cy': cy, '--from': from, '--to': to } as CSSProperties
  return (
    <li className="place reveal-tile" ref={ref} style={{ transitionDelay: `${(index % 3) * 0.1}s` }}>
      <div className={`place__media ${item.image ? 'has-image' : ''}`}>
        {item.image ? (
          <img src={item.image} alt="" loading="lazy" decoding="async" />
        ) : (
          <div className="place__art" style={art} aria-hidden />
        )}
        <div className="place__label">
          {item.meta && <span className="place__meta">{item.meta}</span>}
          <h3 className="place__name">{item.title}</h3>
        </div>
      </div>
      {item.body && <p className="place__body">{item.body}</p>}
    </li>
  )
}

// Testimonials ---------------------------------------------------------------

function Testimonials({ section, content, items, tone }: ListProps) {
  const quotes = items.filter((item) => item.quote)
  return (
    <Shell preset="testimonials" tone={tone} labelledBy={section.title ? 'testimonials-title' : undefined} label="Testimonials">
      <Head id="testimonials-title" eyebrow={content.eyebrow} title={section.title} body={section.body} />
      <div className="quotes" data-count={Math.min(quotes.length, 3)}>
        {quotes.map((item, i) => (
          <Quote key={i} item={item} index={i} />
        ))}
      </div>
    </Shell>
  )
}

function Quote({ item, index }: { item: HomeItem; index: number }) {
  const ref = useReveal<HTMLElement>()
  return (
    <figure className="quote reveal" ref={ref} style={{ transitionDelay: `${(index % 3) * 0.12}s` }}>
      <span className="quote__mark" aria-hidden>
        “
      </span>
      <blockquote>
        <p>{item.quote}</p>
      </blockquote>
      {(item.name || item.context) && (
        <figcaption>
          {item.name && <strong>{item.name}</strong>}
          {item.context && <span>{item.context}</span>}
        </figcaption>
      )}
    </figure>
  )
}

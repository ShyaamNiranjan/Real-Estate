import type { CSSProperties, ReactNode } from 'react'
import { asObject, type SectionContent, type SectionStyle } from '../types/content'
import type { PageSectionRow } from '../types/database'
import { Gallery, type GalleryImage } from './Gallery'
import { useReveal } from './useReveal'

type Props = {
  sections: PageSectionRow[]
  gallery: GalleryImage[]
  fallbackImage: string | null
  onEnquire: () => void
}

const SAFE_HREF = /^(https?:\/\/|\/(?!\/)|mailto:|tel:|#)/i

export function Sections({ sections, gallery, fallbackImage, onEnquire }: Props) {
  return (
    <>
      {sections.map((section) => (
        <Section
          key={section.id}
          section={section}
          gallery={gallery}
          fallbackImage={fallbackImage}
          onEnquire={onEnquire}
        />
      ))}
    </>
  )
}

function Paragraphs({ text, className }: { text: string | null; className: string }) {
  if (!text) return null
  return (
    <div className={className}>
      {text
        .split(/\n{2,}/)
        .map((p) => p.trim())
        .filter(Boolean)
        .map((p, i) => (
          <p key={i}>{p}</p>
        ))}
    </div>
  )
}

function Shell({
  section,
  style,
  children,
}: {
  section: PageSectionRow
  style: SectionStyle
  children: ReactNode
}) {
  const ref = useReveal<HTMLDivElement>()
  const tone = style.tone ?? (section.preset === 'cta' ? 'dark' : 'light')
  const vars: CSSProperties & Record<string, string> = {}
  if (style.background) vars['--sec-bg'] = style.background
  if (style.text) vars['--sec-fg'] = style.text
  if (style.accent) vars['--sec-accent'] = style.accent
  return (
    <section
      className={`sec sec--${section.preset} sec--layout-${section.layout} tone-${tone}`}
      style={vars}
      data-section={section.id}
    >
      <div className="sec__inner reveal" ref={ref}>
        {children}
      </div>
    </section>
  )
}

function Section({
  section,
  gallery,
  fallbackImage,
  onEnquire,
}: {
  section: PageSectionRow
  gallery: GalleryImage[]
  fallbackImage: string | null
  onEnquire: () => void
}) {
  const style = asObject<SectionStyle>(section.style)
  const content = asObject<SectionContent>(section.content)
  const items = Array.isArray(content.items) ? content.items : []
  const head = (
    <>
      {content.eyebrow && <p className="eyebrow">{content.eyebrow}</p>}
      {section.title && <h2 className="sec__title">{section.title}</h2>}
    </>
  )

  switch (section.preset) {
    case 'hero': {
      const image = content.image || fallbackImage
      return (
        <section className="sec sec--hero-band tone-dark" data-section={section.id}>
          {image && <img className="sec__bg" src={image} alt="" loading="lazy" decoding="async" />}
          <div className="sec__veil" aria-hidden />
          <div className="sec__inner">
            {head}
            <Paragraphs text={section.body} className="sec__body" />
          </div>
        </section>
      )
    }

    case 'text':
    case 'custom':
      return (
        <Shell section={section} style={style}>
          <div className="sec__split">
            <div className="sec__head">{head}</div>
            <div>
              <Paragraphs text={section.body} className="sec__body sec__body--lead" />
              {content.image && (
                <figure className="sec__figure">
                  <img src={content.image} alt={content.caption ?? ''} loading="lazy" decoding="async" />
                  {content.caption && <figcaption>{content.caption}</figcaption>}
                </figure>
              )}
            </div>
          </div>
        </Shell>
      )

    case 'specs':
      return (
        <Shell section={section} style={style}>
          {head}
          <dl className="specs">
            {items.map((item, i) => (
              <div className="specs__item" key={i}>
                <dt>{item.label}</dt>
                <dd>{item.value}</dd>
              </div>
            ))}
          </dl>
        </Shell>
      )

    case 'tiles':
      return (
        <Shell section={section} style={style}>
          <div className="sec__head sec__head--row">
            <div>{head}</div>
            <Paragraphs text={section.body} className="sec__body" />
          </div>
          <div className={`feature-grid ${items.some((t) => t.image) ? 'has-media' : ''}`}>
            {items.map((item, i) => (
              <article className="feature" key={i}>
                {item.image && (
                  <div className="feature__media">
                    <img src={item.image} alt="" loading="lazy" decoding="async" />
                  </div>
                )}
                <span className="feature__index">{String(i + 1).padStart(2, '0')}</span>
                {item.title && <h3 className="feature__title">{item.title}</h3>}
                {item.body && <p className="feature__body">{item.body}</p>}
              </article>
            ))}
          </div>
        </Shell>
      )

    case 'gallery': {
      const images =
        Array.isArray(content.images) && content.images.length
          ? content.images.map((src) => ({ src, alt: '' }))
          : gallery
      if (!images.length) return null
      return (
        <Shell section={section} style={style}>
          {(section.title || content.eyebrow) && <div className="sec__head">{head}</div>}
          <Gallery images={images} />
        </Shell>
      )
    }

    case 'cta': {
      const label = content.ctaLabel || 'Enquire'
      const isLink = content.ctaAction === 'link' && content.href && SAFE_HREF.test(content.href)
      return (
        <Shell section={section} style={style}>
          <div className="cta">
            {head}
            <Paragraphs text={section.body} className="sec__body" />
            {isLink ? (
              <a className="button button--light" href={content.href}>
                {label}
                <span className="arrow" aria-hidden />
              </a>
            ) : (
              <button type="button" className="button button--light" onClick={onEnquire}>
                {label}
                <span className="arrow" aria-hidden />
              </button>
            )}
          </div>
        </Shell>
      )
    }

    default:
      return null
  }
}

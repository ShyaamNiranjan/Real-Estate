import { createContext, useContext, type ClipboardEvent, type CSSProperties, type ReactNode } from 'react'
import { asObject, type SectionContent, type SectionStyle } from '../types/content'
import type { PageSectionRow } from '../types/database'
import { Gallery, type GalleryImage } from './Gallery'
import { SAFE_HREF } from './links'
import { useReveal } from './useReveal'

/** Set while the agent is customising: text becomes editable in place. `path` is a dotted field path. */
export type EditCommit = (sectionId: string, path: string, value: string) => void
export const EditContext = createContext<EditCommit | null>(null)

type Props = {
  sections: PageSectionRow[]
  gallery: GalleryImage[]
  fallbackImage: string | null
  onEnquire: () => void
}

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

export function Paragraphs({ text, className }: { text: string | null; className: string }) {
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

function pastePlain(e: ClipboardEvent<HTMLElement>) {
  e.preventDefault()
  document.execCommand('insertText', false, e.clipboardData.getData('text/plain'))
}

/**
 * Plain text normally (hidden when empty). While customising it is contentEditable, shows a
 * placeholder when empty, and commits on blur. Keyed by value so React never fights the edits.
 */
export function Editable({
  sectionId,
  path,
  value,
  tag: Tag = 'p',
  className,
  placeholder,
  multiline = false,
}: {
  sectionId: string
  path: string
  value: string | null | undefined
  tag?: 'p' | 'h1' | 'h2' | 'h3' | 'dt' | 'dd' | 'span' | 'div'
  className?: string
  placeholder: string
  multiline?: boolean
}) {
  const commit = useContext(EditContext)
  const text = value ?? ''
  if (!commit) {
    if (!text) return null
    return multiline ? <Paragraphs text={text} className={className ?? ''} /> : <Tag className={className}>{text}</Tag>
  }
  const El = multiline ? 'div' : Tag
  return (
    <El
      key={text}
      className={`${className ?? ''} is-editable`}
      contentEditable
      suppressContentEditableWarning
      data-placeholder={placeholder}
      spellCheck
      onPaste={pastePlain}
      onKeyDown={
        multiline
          ? undefined
          : (e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                e.currentTarget.blur()
              }
            }
      }
      onBlur={(e) => {
        const raw = e.currentTarget.innerText
        const next = multiline
          ? raw
              .split(/\n\s*\n|\n/)
              .map((p) => p.trim())
              .filter(Boolean)
              .join('\n\n')
          : raw.replace(/\s+/g, ' ').trim()
        if (next !== text) commit(sectionId, path, next)
      }}
    >
      {multiline ? text.split(/\n{2,}/).map((p, i) => <p key={i}>{p}</p>) : text}
    </El>
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
  const editing = Boolean(useContext(EditContext))
  const style = asObject<SectionStyle>(section.style)
  const content = asObject<SectionContent>(section.content)
  const items = Array.isArray(content.items) ? content.items : []
  const id = section.id
  const head = (
    <>
      <Editable sectionId={id} path="content.eyebrow" value={content.eyebrow} className="eyebrow" placeholder="Add a label" />
      <Editable sectionId={id} path="title" value={section.title} tag="h2" className="sec__title" placeholder="Add a heading" />
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
            <Editable sectionId={id} path="body" value={section.body} className="sec__body" placeholder="Add a line of text" multiline />
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
              <Editable sectionId={id} path="body" value={section.body} className="sec__body sec__body--lead" placeholder="Add a paragraph" multiline />
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
            {items.map((item, i) =>
              item.label || item.value || editing ? (
                <div className="specs__item" key={i}>
                  <Editable sectionId={id} path={`content.items.${i}.label`} value={item.label} tag="dt" placeholder="Label" />
                  <Editable sectionId={id} path={`content.items.${i}.value`} value={item.value} tag="dd" placeholder="Value" />
                </div>
              ) : null,
            )}
          </dl>
        </Shell>
      )

    case 'tiles':
      return (
        <Shell section={section} style={style}>
          <div className="sec__head sec__head--row">
            <div>{head}</div>
            <Editable sectionId={id} path="body" value={section.body} className="sec__body" placeholder="Add an introduction" multiline />
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
                <Editable sectionId={id} path={`content.items.${i}.title`} value={item.title} tag="h3" className="feature__title" placeholder="Title" />
                <Editable sectionId={id} path={`content.items.${i}.body`} value={item.body} className="feature__body" placeholder="Describe it in a sentence" />
              </article>
            ))}
          </div>
        </Shell>
      )

    case 'faq':
      return (
        <Shell section={section} style={style}>
          <div className="sec__split">
            <div className="sec__head">{head}</div>
            <dl className="faq">
              {items.map((item, i) => (
                <div className="faq__item" key={i}>
                  <Editable sectionId={id} path={`content.items.${i}.title`} value={item.title} tag="dt" className="faq__q" placeholder="Question" />
                  <Editable sectionId={id} path={`content.items.${i}.body`} value={item.body} tag="dd" className="faq__a" placeholder="Answer" />
                </div>
              ))}
            </dl>
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
          {(section.title || content.eyebrow || editing) && <div className="sec__head">{head}</div>}
          <Gallery images={images} />
        </Shell>
      )
    }

    case 'cta': {
      const label = content.ctaLabel || 'Enquire'
      const isLink = content.ctaAction === 'link' && content.href && SAFE_HREF.test(content.href)
      const labelEl = editing ? (
        <Editable sectionId={id} path="content.ctaLabel" value={label} tag="span" placeholder="Button label" />
      ) : (
        label
      )
      return (
        <Shell section={section} style={style}>
          <div className="cta">
            {head}
            <Editable sectionId={id} path="body" value={section.body} className="sec__body" placeholder="Add a sentence" multiline />
            {isLink && !editing ? (
              <a className="button button--light" href={content.href}>
                {labelEl}
                <span className="arrow" aria-hidden />
              </a>
            ) : (
              <button type="button" className="button button--light" onClick={editing ? undefined : onEnquire}>
                {labelEl}
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

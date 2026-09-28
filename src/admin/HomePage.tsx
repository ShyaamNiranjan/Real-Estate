import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useDocumentTitle, useSite } from '../lib/site'
import { loopFrameUrl } from '../public/FrameLoop'
import { SAFE_HREF } from '../public/links'
import { asObject, type HomeContent, type HomeItem, type SectionStyle, type SectionTone } from '../types/content'
import type { HomeSectionPreset, HomeSectionRow, Json } from '../types/database'
import { listHomeSections, listWalkthroughSources, reorderRows, updateHomeSection, uploadImage, type WalkthroughSource } from './api'
import { EmptyState, Field, Kbd, Spinner, errorMessage, isMac, useSaveShortcut, useToast, useUnsavedGuard } from './ui'

const PRESETS: Record<HomeSectionPreset, { label: string; hint: string }> = {
  collection: { label: 'Collection', hint: 'Published listings as tiles, in the order set on Listings.' },
  walkthrough: { label: 'Walkthrough', hint: 'Walk before you visit: copy, a looping glimpse of a walkthrough, and a link to it.' },
  stats: { label: 'Numbers', hint: 'Three or four figures that count up as they scroll into view.' },
  services: { label: 'Services', hint: 'An editorial list: a title and one line each.' },
  approach: { label: 'Statement', hint: 'One large sentence on the paper surface.' },
  neighbourhoods: { label: 'Neighbourhoods', hint: 'Area tiles with an optional photograph, a name and one line.' },
  testimonials: { label: 'Testimonials', hint: 'Two or three quotes with a name and context.' },
  contact: { label: 'Enquiry', hint: 'Contact details (from Site settings) beside the enquiry form.' },
}

const TONED: HomeSectionPreset[] = ['walkthrough', 'stats', 'services', 'neighbourhoods', 'testimonials']

function summary(row: HomeSectionRow) {
  if (row.title) return row.title
  const items = asObject<HomeContent>(row.content).items ?? []
  if (row.preset === 'stats') return items.map((i) => i.value).filter(Boolean).join(' · ') || null
  if (row.body) return row.body.length > 90 ? `${row.body.slice(0, 90)}…` : row.body
  return null
}

export function HomePage() {
  useDocumentTitle('Home page')
  const toast = useToast()
  const { settings } = useSite()
  const [rows, setRows] = useState<HomeSectionRow[] | null>(null)
  const [openId, setOpenId] = useState<string | null>(null)
  const dirtyRef = useRef(false)
  const setDirty = useCallback((dirty: boolean) => {
    dirtyRef.current = dirty
  }, [])

  useEffect(() => {
    listHomeSections()
      .then(setRows)
      .catch((err) => {
        toast(errorMessage(err), 'error')
        setRows([])
      })
  }, [toast])

  const open = (id: string | null) => {
    if (dirtyRef.current && !window.confirm('Discard unsaved changes to this section?')) return
    dirtyRef.current = false
    setOpenId(id)
  }

  const move = async (index: number, delta: number) => {
    if (!rows) return
    const next = [...rows]
    const target = index + delta
    if (target < 0 || target >= next.length) return
    ;[next[index], next[target]] = [next[target], next[index]]
    const reordered = next.map((s, i) => ({ ...s, sort_order: i }))
    setRows(reordered)
    try {
      await reorderRows('home_sections', reordered.map((s) => s.id))
    } catch (err) {
      toast(errorMessage(err), 'error')
    }
  }

  const toggle = async (row: HomeSectionRow) => {
    try {
      const saved = await updateHomeSection(row.id, { is_visible: !row.is_visible })
      setRows((all) => all?.map((x) => (x.id === saved.id ? saved : x)) ?? null)
      toast(saved.is_visible ? `${PRESETS[saved.preset].label} is visible` : `${PRESETS[saved.preset].label} is hidden`)
    } catch (err) {
      toast(errorMessage(err), 'error')
    }
  }

  return (
    <div className="a-page">
      <header className="a-page__head">
        <div>
          <p className="a-eyebrow">Marketplace</p>
          <h1 className="a-title">Home page</h1>
        </div>
        <div className="a-page__head-actions">
          <a className="a-btn a-btn--ghost" href="/" target="_blank" rel="noreferrer">
            View home ↗
          </a>
        </div>
      </header>
      <p className="a-muted a-home__lead">
        Sections run between the hero and the footer in this order. Reorder or hide them here, or open one to edit its words and
        images. Saved changes are live straight away.
      </p>

      {rows === null ? (
        <Spinner />
      ) : rows.length === 0 ? (
        <EmptyState title="No home sections found">
          <p>Apply the latest Supabase migration to create the home page sections.</p>
        </EmptyState>
      ) : (
        <ol className="a-sections a-sections--home">
          <FixedRow label="Hero" title={settings.hero_headline} />
          {rows.map((s, i) => (
            <li key={s.id} className={`a-section ${openId === s.id ? 'is-open' : ''} ${s.is_visible ? '' : 'is-hidden'}`}>
              <div className="a-section__bar">
                <span className="a-section__num">{String(i + 1).padStart(2, '0')}</span>
                <button
                  type="button"
                  className="a-section__summary"
                  onClick={() => open(openId === s.id ? null : s.id)}
                  aria-expanded={openId === s.id}
                >
                  <span className="a-section__preset">{PRESETS[s.preset].label}</span>
                  <span className="a-section__title">{summary(s) || <em>Untitled</em>}</span>
                </button>
                <div className="a-section__tools">
                  {!s.is_visible && <span className="a-home__hidden">Hidden</span>}
                  <button type="button" className="a-icon-btn" onClick={() => void move(i, -1)} disabled={i === 0} aria-label="Move up">
                    ↑
                  </button>
                  <button type="button" className="a-icon-btn" onClick={() => void move(i, 1)} disabled={i === rows.length - 1} aria-label="Move down">
                    ↓
                  </button>
                  <button type="button" className="a-link" onClick={() => void toggle(s)}>
                    {s.is_visible ? 'Hide' : 'Show'}
                  </button>
                </div>
              </div>
              {openId === s.id && (
                <HomeSectionEditor
                  row={s}
                  onDirty={setDirty}
                  onSaved={(saved) => setRows((all) => all?.map((x) => (x.id === saved.id ? saved : x)) ?? null)}
                  onClose={() => open(null)}
                />
              )}
            </li>
          ))}
          <FixedRow label="Footer" title="Address, contact, RERA number, social links" />
        </ol>
      )}
    </div>
  )
}

function FixedRow({ label, title }: { label: string; title: string | null }) {
  return (
    <li className="a-section a-section--fixed">
      <div className="a-section__bar">
        <span className="a-section__num">—</span>
        <div className="a-section__summary">
          <span className="a-section__preset">{label}</span>
          <span className="a-section__title">{title}</span>
        </div>
        <div className="a-section__tools">
          <Link to="/admin/settings" className="a-link">
            Edit in Site settings
          </Link>
        </div>
      </div>
    </li>
  )
}

// Editor ---------------------------------------------------------------------

type Draft = { title: string; body: string; content: HomeContent; style: SectionStyle }

function HomeSectionEditor({
  row,
  onDirty,
  onSaved,
  onClose,
}: {
  row: HomeSectionRow
  onDirty: (dirty: boolean) => void
  onSaved: (row: HomeSectionRow) => void
  onClose: () => void
}) {
  const toast = useToast()
  const initial = useMemo<Draft>(
    () => ({
      title: row.title ?? '',
      body: row.body ?? '',
      content: asObject<HomeContent>(row.content),
      style: asObject<SectionStyle>(row.style),
    }),
    [row],
  )
  const [draft, setDraft] = useState<Draft>(initial)
  const [saving, setSaving] = useState(false)
  const dirty = JSON.stringify(draft) !== JSON.stringify(initial)
  useUnsavedGuard(dirty)
  useEffect(() => onDirty(dirty), [dirty, onDirty])
  useEffect(() => () => onDirty(false), [onDirty])

  const preset = row.preset
  const content = draft.content
  const items = content.items ?? []
  const set = (patch: Partial<Draft>) => setDraft((d) => ({ ...d, ...patch }))
  const setContent = (patch: Partial<HomeContent>) => setDraft((d) => ({ ...d, content: { ...d.content, ...patch } }))
  const setItems = (next: HomeItem[]) => setContent({ items: next })

  const save = async () => {
    if (saving || !dirty) return
    if (preset === 'walkthrough' && content.href && !SAFE_HREF.test(content.href.trim())) {
      return toast('The button link must start with /, #, https://, mailto: or tel:', 'error')
    }
    setSaving(true)
    try {
      const cleanItems = items
        .map((item) =>
          Object.fromEntries(
            Object.entries(item)
              .map(([k, v]) => [k, typeof v === 'string' ? v.trim() : v])
              .filter(([, v]) => v !== '' && v !== undefined),
          ),
        )
        .filter((item) => Object.keys(item).length > 0)
      const nextContent: HomeContent = Object.fromEntries(
        Object.entries({ ...content, items: content.items ? cleanItems : undefined }).filter(
          ([, v]) => v !== '' && v !== undefined,
        ),
      )
      const style = Object.fromEntries(Object.entries(draft.style).filter(([, v]) => v !== '' && v !== undefined))
      const saved = await updateHomeSection(row.id, {
        title: draft.title.trim() || null,
        body: draft.body.trim() || null,
        content: nextContent as Json,
        style: style as Json,
      })
      onSaved(saved)
      toast(`${PRESETS[preset].label} saved`)
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setSaving(false)
    }
  }
  useSaveShortcut(() => void save())

  const eyebrow = (
    <Field label="Eyebrow" hint="Small label above the heading">
      {(id) => <input id={id} className="a-input" value={content.eyebrow ?? ''} onChange={(e) => setContent({ eyebrow: e.target.value })} />}
    </Field>
  )
  const heading = (label = 'Heading', hint?: string) => (
    <Field label={label} wide hint={hint}>
      {(id) => <input id={id} className="a-input a-input--lg" value={draft.title} onChange={(e) => set({ title: e.target.value })} />}
    </Field>
  )
  const bodyField = (label: string, rows: number, hint?: string) => (
    <Field label={label} wide hint={hint}>
      {(id) => <textarea id={id} className="a-input" rows={rows} value={draft.body} onChange={(e) => set({ body: e.target.value })} />}
    </Field>
  )

  return (
    <div className="a-section__editor">
      <p className="a-note a-home__hint">{PRESETS[preset].hint}</p>

      {preset === 'collection' && <div className="a-grid">{heading('Heading', 'The listings themselves are managed on the Listings page.')}</div>}

      {preset === 'approach' && (
        <div className="a-grid">
          {eyebrow}
          {bodyField('Statement', 3, 'One or two sentences. Set large, so keep it short.')}
        </div>
      )}

      {preset === 'contact' && (
        <div className="a-grid">
          {eyebrow}
          {heading()}
          {bodyField('Body', 2, 'Email and phone come from Site settings.')}
        </div>
      )}

      {preset === 'walkthrough' && <WalkthroughFields draft={draft} setContent={setContent} eyebrow={eyebrow} heading={heading()} body={bodyField('Body', 4, 'Leave a blank line between paragraphs; the second is set in italics.')} />}

      {preset === 'stats' && (
        <>
          <div className="a-grid">
            {eyebrow}
            <Field label="Heading" hint="Optional; the strip reads well without one">
              {(id) => <input id={id} className="a-input" value={draft.title} onChange={(e) => set({ title: e.target.value })} />}
            </Field>
          </div>
          <ListEditor
            title="Figures"
            noun="figure"
            items={items}
            onChange={setItems}
            blank={{ value: '', label: '' }}
            max={4}
            render={(item, update) => (
              <>
                <input className="a-input" placeholder="320+" value={item.value ?? ''} onChange={(e) => update({ value: e.target.value })} aria-label="Figure" />
                <input className="a-input" placeholder="Residences placed" value={item.label ?? ''} onChange={(e) => update({ label: e.target.value })} aria-label="Label" />
              </>
            )}
          />
          <p className="a-field__hint a-home__after">The number counts up; anything around it (+, %, “days”) stays as typed.</p>
        </>
      )}

      {preset === 'services' && (
        <>
          <div className="a-grid">
            {eyebrow}
            {heading()}
            {bodyField('Intro line', 2)}
          </div>
          <ListEditor
            title="Services"
            noun="service"
            items={items}
            onChange={setItems}
            blank={{ title: '', body: '' }}
            render={(item, update) => (
              <>
                <input className="a-input" placeholder="Buy" value={item.title ?? ''} onChange={(e) => update({ title: e.target.value })} aria-label="Service" />
                <input className="a-input" placeholder="One line about it" value={item.body ?? ''} onChange={(e) => update({ body: e.target.value })} aria-label="Description" />
              </>
            )}
          />
        </>
      )}

      {preset === 'neighbourhoods' && (
        <>
          <div className="a-grid">
            {eyebrow}
            {heading()}
            {bodyField('Intro line', 2)}
          </div>
          <ListEditor
            title="Tiles"
            noun="neighbourhood"
            items={items}
            onChange={setItems}
            blank={{ title: '', meta: '', body: '' }}
            render={(item, update) => (
              <div className="a-home-tile">
                <ImageInput value={item.image ?? ''} onChange={(image) => update({ image })} />
                <div className="a-home-tile__fields">
                  <input className="a-input" placeholder="Name (Adyar)" value={item.title ?? ''} onChange={(e) => update({ title: e.target.value })} aria-label="Name" />
                  <input className="a-input a-input--mono" placeholder="Label (600 020)" value={item.meta ?? ''} onChange={(e) => update({ meta: e.target.value })} aria-label="Small label" />
                  <input className="a-input a-home-tile__wide" placeholder="One line about the area" value={item.body ?? ''} onChange={(e) => update({ body: e.target.value })} aria-label="Description" />
                </div>
              </div>
            )}
          />
          <p className="a-field__hint a-home__after">Tiles without a photograph get a quiet contour-map texture.</p>
        </>
      )}

      {preset === 'testimonials' && (
        <>
          <div className="a-grid">
            {eyebrow}
            {heading()}
          </div>
          <ListEditor
            title="Quotes"
            noun="quote"
            items={items}
            onChange={setItems}
            blank={{ quote: '', name: '', context: '' }}
            render={(item, update) => (
              <div className="a-tile-edit">
                <textarea className="a-input" rows={2} placeholder="What they said" value={item.quote ?? ''} onChange={(e) => update({ quote: e.target.value })} aria-label="Quote" />
                <div className="a-item__fields">
                  <input className="a-input" placeholder="Name (Priya R.)" value={item.name ?? ''} onChange={(e) => update({ name: e.target.value })} aria-label="Name" />
                  <input className="a-input" placeholder="Context (Adyar · Bought in 2025)" value={item.context ?? ''} onChange={(e) => update({ context: e.target.value })} aria-label="Context" />
                </div>
              </div>
            )}
          />
        </>
      )}

      {TONED.includes(preset) && (
        <fieldset className="a-fieldset">
          <legend>Style</legend>
          <div className="a-grid">
            <Field label="Surface" hint="Alternate light and dark as sections are reordered.">
              {(id) => (
                <select
                  id={id}
                  className="a-input"
                  value={draft.style.tone ?? ''}
                  onChange={(e) => set({ style: { ...draft.style, tone: (e.target.value || undefined) as SectionTone | undefined } })}
                >
                  <option value="">Default</option>
                  <option value="light">Paper</option>
                  <option value="stone">Stone</option>
                  <option value="dark">Charcoal</option>
                </select>
              )}
            </Field>
          </div>
        </fieldset>
      )}

      <div className="a-section__actions">
        <button type="button" className="a-btn a-btn--primary" onClick={() => void save()} disabled={saving || !dirty}>
          {saving ? 'Saving…' : dirty ? 'Save section' : 'Saved'}
          <Kbd>{isMac ? '⌘' : 'Ctrl'} S</Kbd>
        </button>
        <button type="button" className="a-btn a-btn--ghost" onClick={onClose}>
          Close
        </button>
        {dirty && (
          <button type="button" className="a-link" onClick={() => setDraft(initial)}>
            Undo changes
          </button>
        )}
      </div>
    </div>
  )
}

function WalkthroughFields({
  draft,
  setContent,
  eyebrow,
  heading,
  body,
}: {
  draft: Draft
  setContent: (patch: Partial<HomeContent>) => void
  eyebrow: ReactNode
  heading: ReactNode
  body: ReactNode
}) {
  const toast = useToast()
  const content = draft.content
  const [sources, setSources] = useState<WalkthroughSource[] | null>(null)

  useEffect(() => {
    listWalkthroughSources()
      .then(setSources)
      .catch((err) => {
        toast(errorMessage(err), 'error')
        setSources([])
      })
  }, [toast])

  const current = content.frames?.listing ?? ''

  /** Switching listings carries the link, label and caption along when they still point at the old one. */
  const pick = (slug: string) => {
    const next = sources?.find((s) => s.slug === slug)
    if (!next) return
    const prev = sources?.find((s) => s.slug === current)
    const swap = (text: string | undefined) => (text && prev && text.includes(prev.title) ? text.split(prev.title).join(next.title) : text)
    const prevFirst = content.frames ? loopFrameUrl(content.frames, 1) : null
    setContent({
      frames: { baseUrl: next.baseUrl, pattern: next.pattern, count: next.count, listing: next.slug },
      href: !content.href || (prev && content.href === `/listing/${prev.slug}`) ? `/listing/${next.slug}` : content.href,
      ctaLabel: swap(content.ctaLabel),
      caption: swap(content.caption),
      image: content.image && content.image !== prevFirst ? content.image : undefined,
    })
  }

  return (
    <>
      <div className="a-grid">
        {eyebrow}
        {heading}
        {body}
        <Field label="Button label">
          {(id) => <input id={id} className="a-input" value={content.ctaLabel ?? ''} onChange={(e) => setContent({ ctaLabel: e.target.value })} />}
        </Field>
        <Field label="Button link" hint="Usually an immersive listing, e.g. /listing/aurelia">
          {(id) => <input id={id} className="a-input a-input--mono" value={content.href ?? ''} onChange={(e) => setContent({ href: e.target.value })} />}
        </Field>
      </div>

      <fieldset className="a-fieldset">
        <legend>Visual</legend>
        <div className="a-grid">
          <Field label="Show">
            {(id) => (
              <select id={id} className="a-input" value={content.visual ?? 'loop'} onChange={(e) => setContent({ visual: e.target.value as 'loop' | 'still' })}>
                <option value="loop">A slow loop of walkthrough frames</option>
                <option value="still">A still image</option>
              </select>
            )}
          </Field>
          {(content.visual ?? 'loop') === 'loop' && (
            <Field label="Frames from" hint={sources && sources.length === 0 ? 'No immersive listing has a landscape sequence yet.' : 'Any immersive listing with a landscape frame sequence.'}>
              {(id) => (
                <select id={id} className="a-input" value={current} onChange={(e) => pick(e.target.value)} disabled={!sources?.length}>
                  {!current && <option value="">{sources ? 'Choose a listing' : 'Loading…'}</option>}
                  {current && !sources?.some((s) => s.slug === current) && <option value={current}>{current}</option>}
                  {sources?.map((s) => (
                    <option key={s.slug} value={s.slug}>
                      {s.title} · {s.count} frames{s.status === 'published' ? '' : ` (${s.status})`}
                    </option>
                  ))}
                </select>
              )}
            </Field>
          )}
          <Field label="Caption" wide hint="Small label on the image">
            {(id) => <input id={id} className="a-input" value={content.caption ?? ''} onChange={(e) => setContent({ caption: e.target.value })} />}
          </Field>
        </div>
        <div className="a-home__still">
          <span className="a-field__label">Still image</span>
          <ImageInput
            value={content.image ?? ''}
            onChange={(image) => setContent({ image: image || undefined })}
            placeholder={content.frames ? loopFrameUrl(content.frames, 1) : undefined}
            wide
          />
          <p className="a-field__hint">
            {(content.visual ?? 'loop') === 'loop'
              ? 'Shown while the loop loads and to visitors who prefer reduced motion. Leave empty to use the first frame.'
              : 'Landscape images around 1600 × 1000 work best.'}
          </p>
        </div>
      </fieldset>
    </>
  )
}

// Shared form pieces ---------------------------------------------------------

function ImageInput({
  value,
  onChange,
  placeholder,
  wide,
}: {
  value: string
  onChange: (url: string) => void
  placeholder?: string
  wide?: boolean
}) {
  const toast = useToast()
  const [busy, setBusy] = useState(false)
  const shown = value || placeholder

  const upload = async (file: File | undefined) => {
    if (!file) return
    setBusy(true)
    try {
      const { url } = await uploadImage(file, 'home')
      onChange(url)
      toast('Image uploaded — save to apply')
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className={`a-home-img ${wide ? 'a-home-img--wide' : ''}`}>
      <div className={`a-home-img__thumb ${value ? '' : 'is-placeholder'}`}>{shown ? <img src={shown} alt="" loading="lazy" /> : <span>No image</span>}</div>
      <div className="a-home-img__controls">
        <input
          className="a-input a-input--mono a-input--sm"
          value={value}
          placeholder={placeholder ?? 'Image URL, or upload'}
          onChange={(e) => onChange(e.target.value)}
          aria-label="Image URL"
        />
        <div className="a-home-img__actions">
          <label className={`a-btn a-btn--ghost a-btn--sm a-file ${busy ? 'is-disabled' : ''}`}>
            {busy ? 'Uploading…' : 'Upload image'}
            <input type="file" accept="image/jpeg,image/png,image/webp,image/avif" disabled={busy} onChange={(e) => void upload(e.target.files?.[0])} />
          </label>
          {value && (
            <button type="button" className="a-link" onClick={() => onChange('')}>
              Remove
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

function ListEditor({
  title,
  noun,
  items,
  onChange,
  blank,
  render,
  max,
}: {
  title: string
  noun: string
  items: HomeItem[]
  onChange: (items: HomeItem[]) => void
  blank: HomeItem
  render: (item: HomeItem, update: (patch: Partial<HomeItem>) => void) => ReactNode
  max?: number
}) {
  const move = (i: number, d: number) => {
    const next = [...items]
    const t = i + d
    if (t < 0 || t >= next.length) return
    ;[next[i], next[t]] = [next[t], next[i]]
    onChange(next)
  }
  return (
    <fieldset className="a-fieldset">
      <legend>{title}</legend>
      <ol className="a-items">
        {items.map((item, i) => (
          <li key={i} className="a-item">
            <span className="a-item__num">{i + 1}</span>
            <div className="a-item__fields">{render(item, (patch) => onChange(items.map((x, j) => (j === i ? { ...x, ...patch } : x))))}</div>
            <div className="a-item__tools">
              <button type="button" className="a-icon-btn" onClick={() => move(i, -1)} disabled={i === 0} aria-label="Move up">
                ↑
              </button>
              <button type="button" className="a-icon-btn" onClick={() => move(i, 1)} disabled={i === items.length - 1} aria-label="Move down">
                ↓
              </button>
              <button type="button" className="a-icon-btn a-icon-btn--danger" onClick={() => onChange(items.filter((_, j) => j !== i))} aria-label="Remove">
                ×
              </button>
            </div>
          </li>
        ))}
      </ol>
      <button
        type="button"
        className="a-btn a-btn--ghost a-btn--sm"
        onClick={() => onChange([...items, { ...blank }])}
        disabled={max !== undefined && items.length >= max}
      >
        Add {noun}
      </button>
    </fieldset>
  )
}

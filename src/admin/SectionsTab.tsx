import { useMemo, useState, type ReactNode } from 'react'
import { asObject, type SectionContent, type SectionStyle, type SectionTone } from '../types/content'
import type { Json, ListingMediaRow, PageSectionRow, SectionLayout, SectionPreset } from '../types/database'
import { createSection, deleteSection, reorderRows, updateSection } from './api'
import type { EditorData } from './ListingEditor'
import { ColorField, ConfirmButton, EmptyState, Field, Kbd, errorMessage, isMac, useSaveShortcut, useToast } from './ui'

const PRESETS: { key: SectionPreset; label: string; hint: string }[] = [
  { key: 'text', label: 'Text', hint: 'Heading with a paragraph or two' },
  { key: 'specs', label: 'Specs', hint: 'Large numbers: beds, baths, area' },
  { key: 'tiles', label: 'Tiles', hint: 'Three or so features with optional images' },
  { key: 'gallery', label: 'Gallery', hint: 'Editorial grid with a lightbox' },
  { key: 'hero', label: 'Image band', hint: 'Full-bleed photograph with a line of copy' },
  { key: 'cta', label: 'Call to action', hint: 'Invitation with an enquiry button' },
  { key: 'custom', label: 'Custom', hint: 'Heading, text, image and caption' },
]

const PRESET_LABEL = Object.fromEntries(PRESETS.map((p) => [p.key, p.label])) as Record<SectionPreset, string>

const DEFAULTS: Record<SectionPreset, { title: string; layout: SectionLayout; content: SectionContent; style: SectionStyle }> = {
  text: { title: 'A new chapter', layout: 'default', content: {}, style: { tone: 'light' } },
  specs: { title: 'At a glance', layout: 'tiles', content: { items: [{ label: 'Bedrooms', value: '' }, { label: 'Bathrooms', value: '' }] }, style: {} },
  tiles: { title: 'Spaces', layout: 'tiles', content: { items: [{ title: '', body: '' }] }, style: {} },
  gallery: { title: 'Inside', layout: 'full', content: {}, style: {} },
  hero: { title: '', layout: 'full', content: {}, style: { tone: 'dark' } },
  cta: { title: 'Arrange a private viewing.', layout: 'default', content: { ctaLabel: 'Enquire', ctaAction: 'enquiry' }, style: { tone: 'dark' } },
  custom: { title: '', layout: 'default', content: {}, style: {} },
}

type Props = {
  data: EditorData
  setSections: (fn: (s: PageSectionRow[]) => PageSectionRow[]) => void
}

export function SectionsTab({ data, setSections }: Props) {
  const toast = useToast()
  const { listing, sections, media } = data
  const [openId, setOpenId] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)

  const add = async (preset: SectionPreset) => {
    setAdding(false)
    try {
      const d = DEFAULTS[preset]
      const row = await createSection({
        listing_id: listing.id,
        preset,
        title: d.title || null,
        layout: d.layout,
        content: d.content as Json,
        style: d.style as Json,
        sort_order: sections.length ? Math.max(...sections.map((s) => s.sort_order)) + 1 : 0,
      })
      setSections((s) => [...s, row])
      setOpenId(row.id)
    } catch (err) {
      toast(errorMessage(err), 'error')
    }
  }

  const move = async (index: number, delta: number) => {
    const next = [...sections]
    const target = index + delta
    if (target < 0 || target >= next.length) return
    ;[next[index], next[target]] = [next[target], next[index]]
    const reordered = next.map((s, i) => ({ ...s, sort_order: i }))
    setSections(() => reordered)
    try {
      await reorderRows('page_sections', reordered.map((s) => s.id))
    } catch (err) {
      toast(errorMessage(err), 'error')
    }
  }

  const toggle = async (row: PageSectionRow) => {
    try {
      const saved = await updateSection(row.id, { is_visible: !row.is_visible })
      setSections((s) => s.map((x) => (x.id === saved.id ? saved : x)))
    } catch (err) {
      toast(errorMessage(err), 'error')
    }
  }

  const remove = async (row: PageSectionRow) => {
    try {
      await deleteSection(row.id)
      setSections((s) => s.filter((x) => x.id !== row.id))
      toast('Section deleted')
    } catch (err) {
      toast(errorMessage(err), 'error')
    }
  }

  return (
    <div className="a-stack">
      <div className="a-card a-card--flat">
        <div className="a-card__head">
          <div>
            <h2 className="a-card__title">Page sections</h2>
            <p className="a-muted">
              These follow the {listing.experience_type === 'immersive' ? 'walkthrough' : 'cover image'} and the overview. The enquiry form always closes the page.
            </p>
          </div>
          <div className="a-menu">
            <button type="button" className="a-btn a-btn--primary" aria-expanded={adding} onClick={() => setAdding((v) => !v)}>
              Add section
            </button>
            {adding && (
              <div className="a-menu__panel" role="menu">
                {PRESETS.map((p) => (
                  <button key={p.key} type="button" role="menuitem" className="a-menu__item" onClick={() => void add(p.key)}>
                    <strong>{p.label}</strong>
                    <span>{p.hint}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {sections.length === 0 ? (
        <EmptyState title="No sections yet">
          <p>Add a Text section to introduce the home, then Specs and a Gallery.</p>
        </EmptyState>
      ) : (
        <ol className="a-sections">
          {sections.map((s, i) => (
            <li key={s.id} className={`a-section ${openId === s.id ? 'is-open' : ''} ${s.is_visible ? '' : 'is-hidden'}`}>
              <div className="a-section__bar">
                <span className="a-section__num">{String(i + 1).padStart(2, '0')}</span>
                <button type="button" className="a-section__summary" onClick={() => setOpenId(openId === s.id ? null : s.id)} aria-expanded={openId === s.id}>
                  <span className="a-section__preset">{PRESET_LABEL[s.preset]}</span>
                  <span className="a-section__title">{s.title || <em>Untitled</em>}</span>
                </button>
                <div className="a-section__tools">
                  <button type="button" className="a-icon-btn" onClick={() => void move(i, -1)} disabled={i === 0} aria-label="Move up">
                    ↑
                  </button>
                  <button type="button" className="a-icon-btn" onClick={() => void move(i, 1)} disabled={i === sections.length - 1} aria-label="Move down">
                    ↓
                  </button>
                  <button type="button" className="a-link" onClick={() => void toggle(s)}>
                    {s.is_visible ? 'Hide' : 'Show'}
                  </button>
                  <ConfirmButton onConfirm={() => void remove(s)} className="a-link a-link--danger" confirmLabel="Delete?">
                    Delete
                  </ConfirmButton>
                </div>
              </div>
              {openId === s.id && (
                <SectionEditor
                  row={s}
                  media={media}
                  onSaved={(saved) => setSections((all) => all.map((x) => (x.id === saved.id ? saved : x)))}
                  onClose={() => setOpenId(null)}
                />
              )}
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}

// Editor ---------------------------------------------------------------------

type Draft = {
  preset: SectionPreset
  title: string
  body: string
  layout: SectionLayout
  content: SectionContent
  style: SectionStyle
}

function SectionEditor({
  row,
  media,
  onSaved,
  onClose,
}: {
  row: PageSectionRow
  media: ListingMediaRow[]
  onSaved: (r: PageSectionRow) => void
  onClose: () => void
}) {
  const toast = useToast()
  const initial = useMemo<Draft>(
    () => ({
      preset: row.preset,
      title: row.title ?? '',
      body: row.body ?? '',
      layout: row.layout,
      content: asObject<SectionContent>(row.content),
      style: asObject<SectionStyle>(row.style),
    }),
    [row],
  )
  const [draft, setDraft] = useState<Draft>(initial)
  const [saving, setSaving] = useState(false)
  const [advanced, setAdvanced] = useState(false)
  const [json, setJson] = useState(() => JSON.stringify(initial.content, null, 2))
  const [jsonError, setJsonError] = useState<string | null>(null)
  const dirty = JSON.stringify(draft) !== JSON.stringify(initial)

  const setContent = (patch: Partial<SectionContent>) => {
    const content = { ...draft.content, ...patch }
    setJson(JSON.stringify(content, null, 2))
    setDraft({ ...draft, content })
  }
  const setStyle = (patch: Partial<SectionStyle>) => setDraft((d) => ({ ...d, style: { ...d.style, ...patch } }))

  const save = async () => {
    if (saving || jsonError) return
    setSaving(true)
    try {
      const style = Object.fromEntries(Object.entries(draft.style).filter(([, v]) => v !== '' && v !== undefined))
      const saved = await updateSection(row.id, {
        title: draft.title.trim() || null,
        body: draft.body.trim() || null,
        layout: draft.layout,
        content: draft.content as Json,
        style: style as Json,
      })
      onSaved(saved)
      toast('Section saved')
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setSaving(false)
    }
  }
  useSaveShortcut(() => void save())

  const images = media.filter((m) => (m.kind === 'gallery' || m.kind === 'cover') && m.public_url).map((m) => m.public_url!)
  const items = draft.content.items ?? []
  const setItems = (next: SectionContent['items']) => setContent({ items: next })

  return (
    <div className="a-section__editor">
      <div className="a-grid">
        <Field label={draft.preset === 'hero' ? 'Line over the image' : 'Heading'} wide>
          {(id) => <input id={id} className="a-input a-input--lg" value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} />}
        </Field>
        {draft.preset !== 'gallery' && draft.preset !== 'specs' && (
          <Field label="Body" wide hint="Leave a blank line between paragraphs.">
            {(id) => <textarea id={id} className="a-input" rows={4} value={draft.body} onChange={(e) => setDraft({ ...draft, body: e.target.value })} />}
          </Field>
        )}
        <Field label="Eyebrow" hint="Small label above the heading">
          {(id) => <input id={id} className="a-input" value={draft.content.eyebrow ?? ''} onChange={(e) => setContent({ eyebrow: e.target.value || undefined })} />}
        </Field>
        <Field label="Layout">
          {(id) => (
            <select id={id} className="a-input" value={draft.layout} onChange={(e) => setDraft({ ...draft, layout: e.target.value as SectionLayout })}>
              <option value="default">Default</option>
              <option value="split">Split</option>
              <option value="tiles">Tiles</option>
              <option value="full">Full width</option>
            </select>
          )}
        </Field>
      </div>

      {(draft.preset === 'hero' || draft.preset === 'custom') && (
        <ImagePicker label="Image" value={draft.content.image ?? ''} images={images} onChange={(v) => setContent({ image: v || undefined })} />
      )}
      {draft.preset === 'custom' && (
        <Field label="Caption">
          {(id) => <input id={id} className="a-input" value={draft.content.caption ?? ''} onChange={(e) => setContent({ caption: e.target.value || undefined })} />}
        </Field>
      )}

      {draft.preset === 'specs' && (
        <ItemsEditor
          title="Figures"
          items={items}
          onChange={setItems}
          blank={{ label: '', value: '' }}
          render={(item, update) => (
            <>
              <input className="a-input" placeholder="Label (Bedrooms)" value={item.label ?? ''} onChange={(e) => update({ label: e.target.value })} aria-label="Label" />
              <input className="a-input" placeholder="Value (4)" value={item.value ?? ''} onChange={(e) => update({ value: e.target.value })} aria-label="Value" />
            </>
          )}
        />
      )}

      {draft.preset === 'tiles' && (
        <ItemsEditor
          title="Tiles"
          items={items}
          onChange={setItems}
          blank={{ title: '', body: '' }}
          render={(item, update) => (
            <div className="a-tile-edit">
              <input className="a-input" placeholder="Title" value={item.title ?? ''} onChange={(e) => update({ title: e.target.value })} aria-label="Tile title" />
              <textarea className="a-input" rows={2} placeholder="Short description" value={item.body ?? ''} onChange={(e) => update({ body: e.target.value })} aria-label="Tile body" />
              <select className="a-input" value={item.image ?? ''} onChange={(e) => update({ image: e.target.value || undefined })} aria-label="Tile image">
                <option value="">No image</option>
                {images.map((src, i) => (
                  <option key={src} value={src}>
                    Image {i + 1}
                  </option>
                ))}
              </select>
            </div>
          )}
        />
      )}

      {draft.preset === 'gallery' && (
        <p className="a-note">Shows this listing's gallery images in the order set on the Media tab.</p>
      )}

      {draft.preset === 'cta' && (
        <div className="a-grid">
          <Field label="Button label">
            {(id) => <input id={id} className="a-input" value={draft.content.ctaLabel ?? ''} onChange={(e) => setContent({ ctaLabel: e.target.value })} />}
          </Field>
          <Field label="Button action">
            {(id) => (
              <select id={id} className="a-input" value={draft.content.ctaAction ?? 'enquiry'} onChange={(e) => setContent({ ctaAction: e.target.value as 'enquiry' | 'link' })}>
                <option value="enquiry">Scroll to enquiry form</option>
                <option value="link">Open a link</option>
              </select>
            )}
          </Field>
          {draft.content.ctaAction === 'link' && (
            <Field label="Link" wide hint="https://…, /path, mailto: or tel:">
              {(id) => <input id={id} className="a-input a-input--mono" value={draft.content.href ?? ''} onChange={(e) => setContent({ href: e.target.value })} />}
            </Field>
          )}
        </div>
      )}

      <fieldset className="a-fieldset">
        <legend>Style</legend>
        <div className="a-grid a-grid--4">
          <Field label="Tone">
            {(id) => (
              <select id={id} className="a-input" value={draft.style.tone ?? ''} onChange={(e) => setStyle({ tone: (e.target.value || undefined) as SectionTone | undefined })}>
                <option value="">Automatic</option>
                <option value="light">Paper</option>
                <option value="stone">Stone</option>
                <option value="dark">Charcoal</option>
              </select>
            )}
          </Field>
          <ColorField label="Background" value={draft.style.background ?? ''} onChange={(v) => setStyle({ background: v || undefined })} />
          <ColorField label="Text" value={draft.style.text ?? ''} onChange={(v) => setStyle({ text: v || undefined })} />
          <ColorField label="Accent" value={draft.style.accent ?? ''} onChange={(v) => setStyle({ accent: v || undefined })} />
        </div>
      </fieldset>

      <details className="a-details" open={advanced} onToggle={(e) => setAdvanced((e.target as HTMLDetailsElement).open)}>
        <summary>Advanced · content JSON</summary>
        <textarea
          className="a-input a-input--mono a-json"
          rows={8}
          spellCheck={false}
          value={json}
          onChange={(e) => {
            setJson(e.target.value)
            try {
              const parsed = JSON.parse(e.target.value || '{}')
              if (typeof parsed !== 'object' || Array.isArray(parsed) || parsed === null) throw new Error('Must be an object')
              setDraft((d) => ({ ...d, content: parsed }))
              setJsonError(null)
            } catch (err) {
              setJsonError(errorMessage(err))
            }
          }}
        />
        {jsonError && <p className="a-field__error">{jsonError}</p>}
      </details>

      <div className="a-section__actions">
        <button type="button" className="a-btn a-btn--primary" onClick={() => void save()} disabled={saving || !dirty || Boolean(jsonError)}>
          {saving ? 'Saving…' : dirty ? 'Save section' : 'Saved'}
          <Kbd>{isMac ? '⌘' : 'Ctrl'} S</Kbd>
        </button>
        <button type="button" className="a-btn a-btn--ghost" onClick={onClose}>
          Close
        </button>
      </div>
    </div>
  )
}

type Item = NonNullable<SectionContent['items']>[number]

function ItemsEditor({
  title,
  items,
  onChange,
  blank,
  render,
}: {
  title: string
  items: Item[]
  onChange: (items: Item[]) => void
  blank: Item
  render: (item: Item, update: (patch: Partial<Item>) => void) => ReactNode
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
      <button type="button" className="a-btn a-btn--ghost a-btn--sm" onClick={() => onChange([...items, { ...blank }])}>
        Add {title.toLowerCase().replace(/s$/, '')}
      </button>
    </fieldset>
  )
}

function ImagePicker({ label, value, images, onChange }: { label: string; value: string; images: string[]; onChange: (v: string) => void }) {
  return (
    <div className="a-field a-field--wide">
      <span className="a-field__label">{label}</span>
      <div className="a-pick">
        <button type="button" className={`a-pick__item a-pick__item--none ${!value ? 'is-on' : ''}`} onClick={() => onChange('')} aria-pressed={!value}>
          Cover
        </button>
        {images.map((src) => (
          <button key={src} type="button" className={`a-pick__item ${value === src ? 'is-on' : ''}`} onClick={() => onChange(src)} aria-pressed={value === src}>
            <img src={src} alt="" loading="lazy" />
          </button>
        ))}
      </div>
      <input className="a-input a-input--mono" value={value} onChange={(e) => onChange(e.target.value)} placeholder="Or paste an image URL" aria-label={`${label} URL`} />
    </div>
  )
}

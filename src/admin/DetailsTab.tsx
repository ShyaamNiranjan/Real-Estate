import { useMemo, useState } from 'react'
import { slugify } from '../lib/format'
import type { ExperienceType, ListingRow, ListingStatus } from '../types/database'
import { isSlugTaken, updateListing, uploadImage, type ListingUpdate } from './api'
import type { EditorData } from './ListingEditor'
import { Field, Kbd, STATUS_LABEL, errorMessage, isMac, useSaveShortcut, useToast, useUnsavedGuard } from './ui'

type Draft = {
  title: string
  slug: string
  subtitle: string
  summary: string
  price_label: string
  location: string
  bedrooms: string
  bathrooms: string
  area_sqft: string
  experience_type: ExperienceType
  cover_image_url: string
  status: ListingStatus
  sort_order: string
}

function toDraft(l: ListingRow): Draft {
  return {
    title: l.title,
    slug: l.slug,
    subtitle: l.subtitle ?? '',
    summary: l.summary ?? '',
    price_label: l.price_label ?? '',
    location: l.location ?? '',
    bedrooms: l.bedrooms?.toString() ?? '',
    bathrooms: l.bathrooms?.toString() ?? '',
    area_sqft: l.area_sqft?.toString() ?? '',
    experience_type: l.experience_type,
    cover_image_url: l.cover_image_url ?? '',
    status: l.status,
    sort_order: String(l.sort_order),
  }
}

const num = (v: string) => (v.trim() === '' ? null : Number(v))
const text = (v: string) => (v.trim() === '' ? null : v.trim())

export function DetailsTab({ data, onSaved }: { data: EditorData; onSaved: (l: ListingRow) => void }) {
  const toast = useToast()
  const { listing, media } = data
  const [draft, setDraft] = useState<Draft>(() => toDraft(listing))
  const [saving, setSaving] = useState(false)
  const [errors, setErrors] = useState<Partial<Record<keyof Draft, string>>>({})
  const [uploading, setUploading] = useState(false)

  const initial = useMemo(() => JSON.stringify(toDraft(listing)), [listing])
  const dirty = JSON.stringify(draft) !== initial
  useUnsavedGuard(dirty)

  const set = <K extends keyof Draft>(key: K, value: Draft[K]) => setDraft((d) => ({ ...d, [key]: value }))

  const validate = () => {
    const e: typeof errors = {}
    if (!draft.title.trim()) e.title = 'Required'
    if (!slugify(draft.slug)) e.slug = 'Required'
    for (const k of ['bedrooms', 'bathrooms', 'area_sqft', 'sort_order'] as const) {
      if (draft[k].trim() && !Number.isFinite(Number(draft[k]))) e[k] = 'Must be a number'
    }
    setErrors(e)
    return Object.keys(e).length === 0
  }

  const save = async () => {
    if (saving || !validate()) return
    setSaving(true)
    try {
      const slug = slugify(draft.slug)
      if (slug !== listing.slug && (await isSlugTaken(slug, listing.id))) {
        setErrors({ slug: 'Already used by another listing' })
        return
      }
      const patch: ListingUpdate = {
        title: draft.title.trim(),
        slug,
        subtitle: text(draft.subtitle),
        summary: text(draft.summary),
        price_label: text(draft.price_label),
        location: text(draft.location),
        bedrooms: num(draft.bedrooms),
        bathrooms: num(draft.bathrooms),
        area_sqft: num(draft.area_sqft) === null ? null : Math.round(Number(draft.area_sqft)),
        experience_type: draft.experience_type,
        cover_image_url: text(draft.cover_image_url),
        status: draft.status,
        sort_order: Number(draft.sort_order) || 0,
      }
      if (draft.status === 'published' && !listing.published_at) patch.published_at = new Date().toISOString()
      const saved = await updateListing(listing.id, patch)
      onSaved(saved)
      setDraft(toDraft(saved))
      toast(draft.status !== listing.status ? `Saved · now ${STATUS_LABEL[saved.status]}` : 'Saved')
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setSaving(false)
    }
  }

  useSaveShortcut(() => void save())

  const gallery = media.filter((m) => (m.kind === 'gallery' || m.kind === 'cover') && m.public_url)

  const uploadCover = async (file: File | undefined) => {
    if (!file) return
    setUploading(true)
    try {
      const { url } = await uploadImage(file, `${listing.id}/cover`)
      set('cover_image_url', url)
      toast('Cover uploaded — save to apply')
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setUploading(false)
    }
  }

  return (
    <form
      className="a-editor"
      onSubmit={(e) => {
        e.preventDefault()
        void save()
      }}
    >
      <div className="a-editor__main">
        <section className="a-card">
          <h2 className="a-card__title">Identity</h2>
          <div className="a-grid">
            <Field label="Title" error={errors.title} wide>
              {(id) => <input id={id} className="a-input a-input--lg" value={draft.title} onChange={(e) => set('title', e.target.value)} />}
            </Field>
            <Field label="URL slug" error={errors.slug} hint={`/listing/${slugify(draft.slug) || '…'}`}>
              {(id) => (
                <input
                  id={id}
                  className="a-input a-input--mono"
                  value={draft.slug}
                  onChange={(e) => set('slug', e.target.value.toLowerCase())}
                  onBlur={() => set('slug', slugify(draft.slug))}
                />
              )}
            </Field>
            <Field label="Price label" hint="Shown as written, e.g. “From $4.9M” or “By appointment”">
              {(id) => <input id={id} className="a-input" value={draft.price_label} onChange={(e) => set('price_label', e.target.value)} />}
            </Field>
            <Field label="Subtitle" wide>
              {(id) => <input id={id} className="a-input" value={draft.subtitle} onChange={(e) => set('subtitle', e.target.value)} />}
            </Field>
            <Field label="Summary" wide hint="One or two sentences. Appears under the title on the listing page.">
              {(id) => <textarea id={id} className="a-input" rows={4} value={draft.summary} onChange={(e) => set('summary', e.target.value)} />}
            </Field>
          </div>
        </section>

        <section className="a-card">
          <h2 className="a-card__title">Property</h2>
          <div className="a-grid a-grid--4">
            <Field label="Location" wide>
              {(id) => <input id={id} className="a-input" value={draft.location} onChange={(e) => set('location', e.target.value)} />}
            </Field>
            <Field label="Bedrooms" error={errors.bedrooms}>
              {(id) => <input id={id} className="a-input" inputMode="decimal" value={draft.bedrooms} onChange={(e) => set('bedrooms', e.target.value)} />}
            </Field>
            <Field label="Bathrooms" error={errors.bathrooms}>
              {(id) => <input id={id} className="a-input" inputMode="decimal" value={draft.bathrooms} onChange={(e) => set('bathrooms', e.target.value)} />}
            </Field>
            <Field label="Interior (sq ft)" error={errors.area_sqft}>
              {(id) => <input id={id} className="a-input" inputMode="numeric" value={draft.area_sqft} onChange={(e) => set('area_sqft', e.target.value)} />}
            </Field>
            <Field label="Sort order" error={errors.sort_order} hint="Lower shows first">
              {(id) => <input id={id} className="a-input" inputMode="numeric" value={draft.sort_order} onChange={(e) => set('sort_order', e.target.value)} />}
            </Field>
          </div>
        </section>

        <section className="a-card">
          <h2 className="a-card__title">Cover image</h2>
          <div className="a-cover">
            <div className="a-cover__preview">
              {draft.cover_image_url ? <img src={draft.cover_image_url} alt="Cover preview" /> : <span>No cover</span>}
            </div>
            <div className="a-cover__controls">
              <Field label="Image URL" wide hint="Pick from this listing's media, upload, or paste a URL.">
                {(id) => (
                  <input id={id} className="a-input a-input--mono" value={draft.cover_image_url} onChange={(e) => set('cover_image_url', e.target.value)} />
                )}
              </Field>
              <label className="a-btn a-btn--ghost a-file">
                {uploading ? 'Uploading…' : 'Upload cover'}
                <input type="file" accept="image/jpeg,image/png,image/webp,image/avif" onChange={(e) => void uploadCover(e.target.files?.[0])} />
              </label>
              {gallery.length > 0 && (
                <div className="a-pick" role="listbox" aria-label="Choose from media">
                  {gallery.map((m) => (
                    <button
                      key={m.id}
                      type="button"
                      role="option"
                      aria-selected={draft.cover_image_url === m.public_url}
                      className="a-pick__item"
                      onClick={() => set('cover_image_url', m.public_url!)}
                    >
                      <img src={m.public_url!} alt={m.label ?? ''} loading="lazy" />
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        </section>
      </div>

      <aside className="a-editor__side">
        <section className="a-card a-card--sticky">
          <h2 className="a-card__title">Publishing</h2>
          <fieldset className="a-radio-list">
            <legend className="visually-hidden">Status</legend>
            {(['draft', 'preview', 'published'] as ListingStatus[]).map((s) => (
              <label key={s} className={`a-radio ${draft.status === s ? 'is-on' : ''}`}>
                <input type="radio" name="status" checked={draft.status === s} onChange={() => set('status', s)} />
                <span className={`a-status__dot a-status--${s}`} aria-hidden />
                <span>
                  <strong>{STATUS_LABEL[s]}</strong>
                  <small>
                    {s === 'draft' && 'Work in progress. Admins only.'}
                    {s === 'preview' && 'Ready for review. Admins only.'}
                    {s === 'published' && 'Live in the public collection.'}
                  </small>
                </span>
              </label>
            ))}
          </fieldset>

          <h3 className="a-card__subtitle">Experience</h3>
          <div className="a-seg" role="radiogroup" aria-label="Experience type">
            {(['photo', 'immersive'] as ExperienceType[]).map((t) => (
              <label key={t} className={`a-seg__opt ${draft.experience_type === t ? 'is-on' : ''}`}>
                <input type="radio" name="exp" checked={draft.experience_type === t} onChange={() => set('experience_type', t)} />
                {t === 'photo' ? 'Photo' : 'Immersive'}
              </label>
            ))}
          </div>
          {draft.experience_type === 'immersive' && !media.some((m) => m.kind === 'frame_sequence') && (
            <p className="a-note a-note--warn">Add a frame sequence in the Walkthrough tab, or visitors will see the photo layout.</p>
          )}

          <div className="a-card__actions">
            <button type="submit" className="a-btn a-btn--primary a-btn--block" disabled={saving || !dirty}>
              {saving ? 'Saving…' : dirty ? 'Save changes' : 'Saved'}
              <Kbd>{isMac ? '⌘' : 'Ctrl'} S</Kbd>
            </button>
            <a className="a-btn a-btn--ghost a-btn--block" href={`/listing/${listing.slug}`} target="_blank" rel="noreferrer">
              Open preview ↗
            </a>
          </div>
        </section>
      </aside>
    </form>
  )
}

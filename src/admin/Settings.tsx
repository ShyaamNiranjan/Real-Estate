import { useEffect, useMemo, useState } from 'react'
import { useDocumentTitle, useSite } from '../lib/site'
import type { SiteSettingsRow } from '../types/database'
import { getSettings, saveSettings, uploadImage } from './api'
import { ColorField, Field, Kbd, Spinner, errorMessage, isMac, useSaveShortcut, useToast, useUnsavedGuard } from './ui'

const KEYS = [
  'brand_name',
  'tagline',
  'hero_headline',
  'hero_body',
  'hero_image_url',
  'hero_cta_label',
  'primary_color',
  'accent_color',
  'background_color',
  'contact_email',
  'contact_phone',
  'footer_note',
] as const

type Draft = Record<(typeof KEYS)[number], string>

function toDraft(row: SiteSettingsRow | null): Draft {
  const d = {} as Draft
  for (const k of KEYS) d[k] = (row?.[k] as string | null | undefined) ?? ''
  if (!d.primary_color) d.primary_color = '#c4a574'
  if (!d.accent_color) d.accent_color = '#0c0e0d'
  if (!d.background_color) d.background_color = '#f5f0e8'
  if (!d.brand_name) d.brand_name = 'AURELIA'
  return d
}

const HEX = /^#[0-9a-f]{6}$/i

export function Settings() {
  useDocumentTitle('Site settings')
  const toast = useToast()
  const { reload } = useSite()
  const [row, setRow] = useState<SiteSettingsRow | null | undefined>(undefined)
  const [draft, setDraft] = useState<Draft>(() => toDraft(null))
  const [saving, setSaving] = useState(false)
  const [uploading, setUploading] = useState(false)

  useEffect(() => {
    getSettings()
      .then((r) => {
        setRow(r)
        setDraft(toDraft(r))
      })
      .catch((err) => {
        toast(errorMessage(err), 'error')
        setRow(null)
      })
  }, [toast])

  const initial = useMemo(() => JSON.stringify(toDraft(row ?? null)), [row])
  const dirty = row !== undefined && JSON.stringify(draft) !== initial
  useUnsavedGuard(dirty)

  const set = (k: keyof Draft, v: string) => setDraft((d) => ({ ...d, [k]: v }))

  const save = async () => {
    if (saving || !dirty) return
    if (!draft.brand_name.trim()) return toast('Brand name is required', 'error')
    for (const k of ['primary_color', 'accent_color', 'background_color'] as const) {
      if (!HEX.test(draft[k])) return toast('Colours must be 6-digit hex values', 'error')
    }
    setSaving(true)
    try {
      const patch: Record<string, string | null> = {}
      for (const k of KEYS) patch[k] = draft[k].trim() || null
      const saved = await saveSettings(row?.id ?? null, {
        ...patch,
        brand_name: draft.brand_name.trim(),
        primary_color: draft.primary_color,
        accent_color: draft.accent_color,
        background_color: draft.background_color,
      })
      setRow(saved)
      setDraft(toDraft(saved))
      await reload()
      toast('Settings saved')
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setSaving(false)
    }
  }
  useSaveShortcut(() => void save())

  const uploadHero = async (file: File | undefined) => {
    if (!file) return
    setUploading(true)
    try {
      const { url } = await uploadImage(file, 'site')
      set('hero_image_url', url)
      toast('Image uploaded — save to apply')
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setUploading(false)
    }
  }

  if (row === undefined) return <Spinner />

  return (
    <form
      className="a-page"
      onSubmit={(e) => {
        e.preventDefault()
        void save()
      }}
    >
      <header className="a-page__head">
        <div>
          <p className="a-eyebrow">Brand</p>
          <h1 className="a-title">Site settings</h1>
        </div>
        <button type="submit" className="a-btn a-btn--primary" disabled={saving || !dirty}>
          {saving ? 'Saving…' : dirty ? 'Save changes' : 'Saved'}
          <Kbd>{isMac ? '⌘' : 'Ctrl'} S</Kbd>
        </button>
      </header>

      <div className="a-editor">
        <div className="a-editor__main">
          <section className="a-card">
            <h2 className="a-card__title">Identity</h2>
            <div className="a-grid">
              <Field label="Brand name">
                {(id) => <input id={id} className="a-input a-input--lg" value={draft.brand_name} onChange={(e) => set('brand_name', e.target.value)} />}
              </Field>
              <Field label="Tagline" hint="Used in the browser title">
                {(id) => <input id={id} className="a-input" value={draft.tagline} onChange={(e) => set('tagline', e.target.value)} />}
              </Field>
            </div>
          </section>

          <section className="a-card">
            <h2 className="a-card__title">Home hero</h2>
            <div className="a-grid">
              <Field label="Headline" wide>
                {(id) => <input id={id} className="a-input" value={draft.hero_headline} onChange={(e) => set('hero_headline', e.target.value)} />}
              </Field>
              <Field label="One sentence" wide>
                {(id) => <textarea id={id} className="a-input" rows={2} value={draft.hero_body} onChange={(e) => set('hero_body', e.target.value)} />}
              </Field>
              <Field label="Button label">
                {(id) => <input id={id} className="a-input" value={draft.hero_cta_label} onChange={(e) => set('hero_cta_label', e.target.value)} />}
              </Field>
            </div>
            <div className="a-cover">
              <div className="a-cover__preview a-cover__preview--wide">
                {draft.hero_image_url ? <img src={draft.hero_image_url} alt="Hero preview" /> : <span>No image</span>}
              </div>
              <div className="a-cover__controls">
                <Field label="Hero image URL" wide>
                  {(id) => <input id={id} className="a-input a-input--mono" value={draft.hero_image_url} onChange={(e) => set('hero_image_url', e.target.value)} />}
                </Field>
                <label className="a-btn a-btn--ghost a-file">
                  {uploading ? 'Uploading…' : 'Upload image'}
                  <input type="file" accept="image/jpeg,image/png,image/webp,image/avif" onChange={(e) => void uploadHero(e.target.files?.[0])} />
                </label>
              </div>
            </div>
          </section>

          <section className="a-card">
            <h2 className="a-card__title">Contact</h2>
            <div className="a-grid">
              <Field label="Email">
                {(id) => <input id={id} className="a-input" type="email" value={draft.contact_email} onChange={(e) => set('contact_email', e.target.value)} />}
              </Field>
              <Field label="Phone">
                {(id) => <input id={id} className="a-input" type="tel" value={draft.contact_phone} onChange={(e) => set('contact_phone', e.target.value)} />}
              </Field>
              <Field label="Footer note" wide>
                {(id) => <input id={id} className="a-input" value={draft.footer_note} onChange={(e) => set('footer_note', e.target.value)} />}
              </Field>
            </div>
          </section>
        </div>

        <aside className="a-editor__side">
          <section className="a-card a-card--sticky">
            <h2 className="a-card__title">Colours</h2>
            <div className="a-form">
              <ColorField label="Accent (gold)" value={draft.primary_color} onChange={(v) => set('primary_color', v)} />
              <ColorField label="Base (charcoal)" value={draft.accent_color} onChange={(v) => set('accent_color', v)} />
              <ColorField label="Paper" value={draft.background_color} onChange={(v) => set('background_color', v)} />
            </div>
            <div
              className="a-swatch"
              style={{ background: HEX.test(draft.accent_color) ? draft.accent_color : undefined }}
              aria-label="Colour preview"
            >
              <span style={{ color: HEX.test(draft.primary_color) ? draft.primary_color : undefined }}>{draft.brand_name || 'AURELIA'}</span>
              <i style={{ background: HEX.test(draft.background_color) ? draft.background_color : undefined }} />
            </div>
          </section>
        </aside>
      </div>
    </form>
  )
}

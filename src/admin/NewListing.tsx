import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../lib/auth'
import { slugify } from '../lib/format'
import { useDocumentTitle } from '../lib/site'
import type { ExperienceType } from '../types/database'
import { createListing, createSection, isSlugTaken } from './api'
import { Field, errorMessage, useToast } from './ui'

export function NewListing() {
  useDocumentTitle('New listing')
  const navigate = useNavigate()
  const toast = useToast()
  const { profile } = useAuth()
  const [title, setTitle] = useState('')
  const [slug, setSlug] = useState('')
  const [slugTouched, setSlugTouched] = useState(false)
  const [type, setType] = useState<ExperienceType>('photo')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const effectiveSlug = slugTouched ? slug : slugify(title)

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault()
    const s = slugify(effectiveSlug)
    if (!title.trim() || !s) return setError('A title and slug are required')
    setBusy(true)
    setError(null)
    try {
      if (await isSlugTaken(s)) {
        setError('That slug is already used by another listing')
        return
      }
      const listing = await createListing({
        title: title.trim(),
        slug: s,
        experience_type: type,
        status: 'draft',
        created_by: profile?.id ?? null,
      })
      // Sensible starting structure so the page is never blank.
      await Promise.all([
        createSection({ listing_id: listing.id, preset: 'text', title: 'Overview', body: '', layout: 'default', sort_order: 0, style: { tone: 'light' } }),
        createSection({ listing_id: listing.id, preset: 'specs', title: 'At a glance', layout: 'tiles', sort_order: 1, content: { items: [] } }),
        createSection({ listing_id: listing.id, preset: 'gallery', title: 'Inside', layout: 'full', sort_order: 2 }),
        createSection({
          listing_id: listing.id,
          preset: 'cta',
          title: 'Arrange a private viewing.',
          layout: 'default',
          sort_order: 3,
          content: { ctaLabel: 'Enquire', ctaAction: 'enquiry' },
          style: { tone: 'dark' },
        }),
      ])
      toast('Listing created')
      navigate(`/admin/listings/${listing.id}`, { replace: true })
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="a-page a-page--narrow">
      <header className="a-page__head">
        <div>
          <Link to="/admin" className="a-crumb">
            ← Listings
          </Link>
          <h1 className="a-title">New listing</h1>
        </div>
      </header>

      <form className="a-card a-form" onSubmit={onSubmit}>
        <Field label="Title">
          {(id) => (
            <input
              id={id}
              className="a-input a-input--lg"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="The Garden House"
              autoFocus
              required
            />
          )}
        </Field>
        <Field label="URL slug" hint={<>Public address: /listing/{effectiveSlug || '…'}</>}>
          {(id) => (
            <input
              id={id}
              className="a-input a-input--mono"
              value={effectiveSlug}
              onChange={(e) => {
                setSlugTouched(true)
                setSlug(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, '-'))
              }}
            />
          )}
        </Field>

        <fieldset className="a-choice">
          <legend className="a-field__label">Experience</legend>
          <label className={`a-choice__opt ${type === 'photo' ? 'is-on' : ''}`}>
            <input type="radio" name="type" checked={type === 'photo'} onChange={() => setType('photo')} />
            <strong>Photo</strong>
            <span>Full-bleed cover and an editorial gallery.</span>
          </label>
          <label className={`a-choice__opt ${type === 'immersive' ? 'is-on' : ''}`}>
            <input type="radio" name="type" checked={type === 'immersive'} onChange={() => setType('immersive')} />
            <strong>Immersive</strong>
            <span>Scroll-driven walkthrough from frame sequences.</span>
          </label>
        </fieldset>

        {error && <p className="a-form__error">{error}</p>}
        <div className="a-form__actions">
          <button type="submit" className="a-btn a-btn--primary" disabled={busy}>
            {busy ? 'Creating…' : 'Create draft'}
          </button>
          <Link to="/admin" className="a-btn a-btn--ghost">
            Cancel
          </Link>
        </div>
      </form>
    </div>
  )
}

import { useCallback, useEffect, useState } from 'react'
import { Link, NavLink, useNavigate, useParams } from 'react-router-dom'
import { useDocumentTitle } from '../lib/site'
import type { ListingMediaRow, ListingRow, PageSectionRow } from '../types/database'
import { deleteListing, getListing, listMedia, listSections } from './api'
import { DetailsTab } from './DetailsTab'
import { ExperienceTab } from './ExperienceTab'
import { MediaTab } from './MediaTab'
import { SectionsTab } from './SectionsTab'
import { ConfirmButton, Spinner, StatusMark, errorMessage, useToast } from './ui'

export type EditorData = {
  listing: ListingRow
  media: ListingMediaRow[]
  sections: PageSectionRow[]
}

const TABS = [
  { key: 'details', label: 'Details' },
  { key: 'media', label: 'Media' },
  { key: 'sections', label: 'Sections' },
  { key: 'experience', label: 'Walkthrough' },
] as const

type TabKey = (typeof TABS)[number]['key']

export function ListingEditor() {
  const { id = '', tab = 'details' } = useParams()
  const navigate = useNavigate()
  const toast = useToast()
  const [data, setData] = useState<EditorData | null>(null)
  const [failed, setFailed] = useState<string | null>(null)

  useDocumentTitle(data ? `Edit · ${data.listing.title}` : 'Edit listing')

  const load = useCallback(async () => {
    try {
      const [listing, media, sections] = await Promise.all([getListing(id), listMedia(id), listSections(id)])
      setData({ listing, media, sections })
    } catch (err) {
      setFailed(errorMessage(err))
    }
  }, [id])

  useEffect(() => {
    setData(null)
    setFailed(null)
    void load()
  }, [load])

  const setListing = useCallback((listing: ListingRow) => setData((d) => (d ? { ...d, listing } : d)), [])
  const setMedia = useCallback(
    (fn: (m: ListingMediaRow[]) => ListingMediaRow[]) => setData((d) => (d ? { ...d, media: fn(d.media) } : d)),
    [],
  )
  const setSections = useCallback(
    (fn: (s: PageSectionRow[]) => PageSectionRow[]) => setData((d) => (d ? { ...d, sections: fn(d.sections) } : d)),
    [],
  )

  if (failed)
    return (
      <div className="a-page">
        <Link to="/admin" className="a-crumb">
          ← Listings
        </Link>
        <h1 className="a-title">Listing unavailable</h1>
        <p className="a-muted">{failed}</p>
      </div>
    )
  if (!data) return <Spinner />

  const { listing } = data
  const activeTab: TabKey = (TABS.some((t) => t.key === tab) ? tab : 'details') as TabKey
  const tabs = TABS.filter((t) => t.key !== 'experience' || listing.experience_type === 'immersive')

  const remove = async () => {
    try {
      await deleteListing(listing.id)
      toast('Listing deleted')
      navigate('/admin', { replace: true })
    } catch (err) {
      toast(errorMessage(err), 'error')
    }
  }

  return (
    <div className="a-page a-page--editor">
      <header className="a-page__head a-page__head--editor">
        <div className="a-page__head-main">
          <Link to="/admin" className="a-crumb">
            ← Listings
          </Link>
          <h1 className="a-title">{listing.title}</h1>
          <p className="a-page__sub">
            <StatusMark status={listing.status} />
            <code>/listing/{listing.slug}</code>
            <span>{listing.experience_type === 'immersive' ? 'Immersive walkthrough' : 'Photo experience'}</span>
          </p>
        </div>
        <div className="a-page__head-actions">
          <a className="a-btn a-btn--ghost" href={`/listing/${listing.slug}`} target="_blank" rel="noreferrer">
            {listing.status === 'published' ? 'View live ↗' : 'Preview ↗'}
          </a>
          <ConfirmButton onConfirm={remove} confirmLabel="Delete permanently?">
            Delete
          </ConfirmButton>
        </div>
      </header>

      <nav className="a-subnav" aria-label="Listing sections">
        {tabs.map((t) => (
          <NavLink
            key={t.key}
            to={`/admin/listings/${listing.id}/${t.key}`}
            className={() => `a-subnav__link ${activeTab === t.key ? 'active' : ''}`}
            replace
          >
            {t.label}
            {t.key === 'media' && <span className="a-tab__count">{data.media.length}</span>}
            {t.key === 'sections' && <span className="a-tab__count">{data.sections.length}</span>}
          </NavLink>
        ))}
      </nav>

      {activeTab === 'details' && <DetailsTab data={data} onSaved={setListing} />}
      {activeTab === 'media' && <MediaTab data={data} setMedia={setMedia} onListing={setListing} />}
      {activeTab === 'sections' && <SectionsTab data={data} setSections={setSections} />}
      {activeTab === 'experience' && <ExperienceTab data={data} onListing={setListing} setMedia={setMedia} />}
    </div>
  )
}

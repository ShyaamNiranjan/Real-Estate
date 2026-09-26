import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { formatDate, listingFacts } from '../lib/format'
import { useDocumentTitle } from '../lib/site'
import type { ListingRow, ListingStatus } from '../types/database'
import { listListings } from './api'
import { EmptyState, Kbd, Spinner, StatusMark, errorMessage, useToast } from './ui'

type Filter = 'all' | ListingStatus
const FILTERS: { key: Filter; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'published', label: 'Published' },
  { key: 'preview', label: 'Preview' },
  { key: 'draft', label: 'Draft' },
]

export function Dashboard() {
  useDocumentTitle('Listings')
  const toast = useToast()
  const navigate = useNavigate()
  const [rows, setRows] = useState<ListingRow[] | null>(null)
  const [filter, setFilter] = useState<Filter>('all')
  const [query, setQuery] = useState('')

  useEffect(() => {
    listListings()
      .then(setRows)
      .catch((err) => {
        toast(errorMessage(err), 'error')
        setRows([])
      })
  }, [toast])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement
      if (target.closest('input, textarea, select, [contenteditable]')) return
      if (e.key === 'n' && !e.metaKey && !e.ctrlKey) {
        e.preventDefault()
        navigate('/admin/listings/new')
      }
      if (e.key === '/') {
        e.preventDefault()
        document.getElementById('listing-search')?.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [navigate])

  const counts = useMemo(() => {
    const c: Record<Filter, number> = { all: 0, draft: 0, preview: 0, published: 0 }
    for (const r of rows ?? []) {
      c.all += 1
      c[r.status] += 1
    }
    return c
  }, [rows])

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    return (rows ?? []).filter(
      (r) =>
        (filter === 'all' || r.status === filter) &&
        (!q || r.title.toLowerCase().includes(q) || r.slug.includes(q) || (r.location ?? '').toLowerCase().includes(q)),
    )
  }, [rows, filter, query])

  return (
    <div className="a-page">
      <header className="a-page__head">
        <div>
          <p className="a-eyebrow">Collection</p>
          <h1 className="a-title">Listings</h1>
        </div>
        <Link to="/admin/listings/new" className="a-btn a-btn--primary">
          New listing <Kbd>N</Kbd>
        </Link>
      </header>

      <div className="a-toolbar">
        <div className="a-tabs" role="tablist" aria-label="Filter by status">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              type="button"
              role="tab"
              aria-selected={filter === f.key}
              className="a-tab"
              onClick={() => setFilter(f.key)}
            >
              {f.label}
              <span className="a-tab__count">{counts[f.key]}</span>
            </button>
          ))}
        </div>
        <label className="a-search">
          <span className="visually-hidden">Search listings</span>
          <input
            id="listing-search"
            className="a-input"
            type="search"
            placeholder="Search title, slug, location"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <Kbd>/</Kbd>
        </label>
      </div>

      {rows === null ? (
        <Spinner />
      ) : visible.length === 0 ? (
        <EmptyState title={rows.length === 0 ? 'No listings yet' : 'Nothing matches'}>
          {rows.length === 0 ? (
            <Link to="/admin/listings/new" className="a-btn a-btn--primary">
              Create the first listing
            </Link>
          ) : (
            <p>Try another status or clear the search.</p>
          )}
        </EmptyState>
      ) : (
        <div className="a-table-wrap">
          <table className="a-table">
            <thead>
              <tr>
                <th className="a-table__thumb-col a-hide-sm" aria-label="Cover" />
                <th>Listing</th>
                <th className="a-hide-sm">Experience</th>
                <th>Status</th>
                <th className="a-hide-sm">Updated</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {visible.map((r) => (
                <tr key={r.id}>
                  <td className="a-hide-sm">
                    <Link to={`/admin/listings/${r.id}`} className="a-thumb" tabIndex={-1} aria-hidden>
                      {r.cover_image_url ? <img src={r.cover_image_url} alt="" loading="lazy" /> : <span />}
                    </Link>
                  </td>
                  <td>
                    <Link to={`/admin/listings/${r.id}`} className="a-table__title">
                      {r.title}
                    </Link>
                    <p className="a-table__meta">
                      <code>/{r.slug}</code>
                      {[r.location, ...listingFacts(r)].filter(Boolean).map((f) => (
                        <span key={f}>{f}</span>
                      ))}
                    </p>
                  </td>
                  <td className="a-table__muted a-hide-sm">{r.experience_type === 'immersive' ? 'Immersive' : 'Photo'}</td>
                  <td>
                    <StatusMark status={r.status} />
                  </td>
                  <td className="a-table__muted a-hide-sm">{formatDate(r.updated_at)}</td>
                  <td className="a-table__actions">
                    <Link to={`/admin/listings/${r.id}`} className="a-link">
                      Edit
                    </Link>
                    <a href={`/listing/${r.slug}`} target="_blank" rel="noreferrer" className="a-link">
                      {r.status === 'published' ? 'View' : 'Preview'} ↗
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

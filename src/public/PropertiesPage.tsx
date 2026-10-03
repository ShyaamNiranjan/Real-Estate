import { useEffect, useMemo, useState } from 'react'
import { fetchPublishedListings, homeCache, type ListingCard } from '../lib/api'
import { useDocumentTitle, useSite } from '../lib/site'
import { SiteDraftBar } from './DraftBar'
import { ListingTile } from './HomeSections'
import { SiteFooter } from './SiteFooter'
import { SiteHeader } from './SiteHeader'

type Beds = 0 | 2 | 3 | 4
type Kind = 'all' | 'immersive' | 'photo'

export function PropertiesPage() {
  useDocumentTitle('Properties')
  const { settings } = useSite()
  const [listings, setListings] = useState<ListingCard[] | null>(homeCache.listings)
  const [failed, setFailed] = useState(false)
  const [query, setQuery] = useState('')
  const [beds, setBeds] = useState<Beds>(0)
  const [kind, setKind] = useState<Kind>('all')

  useEffect(() => {
    let active = true
    fetchPublishedListings()
      .then((rows) => active && setListings(rows))
      .catch((err) => {
        console.error(err)
        if (active) {
          setFailed(true)
          setListings([])
        }
      })
    return () => {
      active = false
    }
  }, [])

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    return (listings ?? []).filter(
      (l) =>
        (!q || l.title.toLowerCase().includes(q) || (l.location ?? '').toLowerCase().includes(q)) &&
        (!beds || (l.bedrooms ?? 0) >= beds) &&
        (kind === 'all' || l.experience_type === kind),
    )
  }, [listings, query, beds, kind])

  const filtered = Boolean(query.trim()) || beds !== 0 || kind !== 'all'

  return (
    <div className="page page--properties">
      <SiteHeader variant="page" />
      <SiteDraftBar />
      <main className="props">
        <div className="props__inner">
          <header className="props__head">
            <p className="eyebrow">{settings.brand_name}</p>
            <h1 className="props__title">All properties</h1>
            <p className="props__count">
              {listings === null ? '—' : `${visible.length} of ${listings.length}`} {listings?.length === 1 ? 'residence' : 'residences'}
            </p>
          </header>

          <div className="props__filters" role="search">
            <label className="props__search">
              <span className="visually-hidden">Search by name or location</span>
              <input type="search" placeholder="Search by name or location" value={query} onChange={(e) => setQuery(e.target.value)} />
            </label>
            <div className="props__group" role="group" aria-label="Bedrooms">
              {([0, 2, 3, 4] as Beds[]).map((b) => (
                <button key={b} type="button" className={`props__chip ${beds === b ? 'is-on' : ''}`} onClick={() => setBeds(b)}>
                  {b === 0 ? 'Any beds' : `${b}+ beds`}
                </button>
              ))}
            </div>
            <div className="props__group" role="group" aria-label="Experience">
              {(
                [
                  ['all', 'All'],
                  ['immersive', 'Walkthrough'],
                  ['photo', 'Photography'],
                ] as [Kind, string][]
              ).map(([k, label]) => (
                <button key={k} type="button" className={`props__chip ${kind === k ? 'is-on' : ''}`} onClick={() => setKind(k)}>
                  {label}
                </button>
              ))}
            </div>
          </div>

          {listings === null ? (
            <div className="collection__grid" aria-busy>
              {[0, 1].map((i) => (
                <div key={i} className="tile tile--skeleton">
                  <div className="tile__media" />
                </div>
              ))}
            </div>
          ) : visible.length === 0 ? (
            <p className="props__empty">
              {failed
                ? 'The properties could not be loaded. Please refresh in a moment.'
                : filtered
                  ? 'Nothing matches those filters.'
                  : 'New residences are being prepared.'}
            </p>
          ) : (
            <div className={`collection__grid ${visible.length === 1 ? 'is-single' : ''}`}>
              {visible.map((listing, i) => (
                <ListingTile key={listing.id} listing={listing} index={i} />
              ))}
            </div>
          )}
        </div>
      </main>
      <SiteFooter />
    </div>
  )
}

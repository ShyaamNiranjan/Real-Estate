import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { ScrollExperience } from '../components/ScrollExperience'
import { reportDepth, track, usePageview } from '../lib/analytics'
import { fetchListingBySlug } from '../lib/api'
import { useAuth } from '../lib/auth'
import { expandFramePattern, joinUrl, listingFacts } from '../lib/format'
import { applyEdit, draftToRows, factsFromListing, listingJsonLd, loadDraft, saveDraft, type ListingDraft } from '../lib/listingCopy'
import { useProto } from '../lib/prototype'
import { useRealtor } from '../lib/realtor'
import { useDocumentTitle } from '../lib/site'
import { asMobileMode, asObject, type ExperienceConfig, type FrameSequence, type ListingWithRelations } from '../types/content'
import type { ListingMediaRow } from '../types/database'
import { EnquiryForm } from './EnquiryForm'
import { NotFound } from './NotFound'
import { FloorPlans } from './FloorPlans'
import { EditContext, Editable, Sections, type EditCommit } from './Sections'
import { SiteFooter } from './SiteFooter'
import { SiteHeader } from './SiteHeader'
import { useReveal } from './useReveal'
import '../styles/experience.css'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'missing' }
  | { kind: 'error' }
  | { kind: 'ready'; listing: ListingWithRelations }

function toSequence(m: ListingMediaRow): FrameSequence | null {
  if (!m.public_url || !m.frame_count || !m.frame_pattern) return null
  const meta = asObject<{ px_per_frame?: number }>(m.metadata)
  return {
    baseUrl: m.public_url,
    frameCount: m.frame_count,
    pattern: m.frame_pattern,
    pxPerFrame: typeof meta.px_per_frame === 'number' ? meta.px_per_frame : undefined,
  }
}

export function ListingPage() {
  const { slug = '' } = useParams()
  const { loading: authLoading, isAdmin } = useAuth()
  const { base } = useRealtor()
  const [state, setState] = useState<LoadState>({ kind: 'loading' })

  useEffect(() => {
    // Wait for auth so admins previewing drafts get their session applied to the query.
    if (authLoading) return
    let active = true
    setState({ kind: 'loading' })
    fetchListingBySlug(slug)
      .then((listing) => active && setState(listing ? { kind: 'ready', listing } : { kind: 'missing' }))
      .catch((err) => {
        console.error(err)
        if (active) setState({ kind: 'error' })
      })
    return () => {
      active = false
    }
  }, [slug, authLoading, isAdmin])

  useDocumentTitle(state.kind === 'ready' ? state.listing.title : null)

  if (state.kind === 'loading') return <div className="page page--loading" aria-busy aria-label="Loading residence" />
  if (state.kind === 'missing') return <NotFound href={base} />
  if (state.kind === 'error')
    return (
      <NotFound
        title="This residence is taking a moment."
        body="We could not load it just now. Please refresh, or return to the collection."
        href={base}
      />
    )
  return <ListingOrDraft listing={state.listing} />
}

/**
 * `?draft=1` renders the Studio's AI draft (kept in this browser) inside the real page, with a still
 * frame instead of the walkthrough; `&edit=1` makes the text editable in place.
 */
/** Prototype: `?stage=portrait` swaps in a phone-recorded (9:16 only) walkthrough to show the desktop side layout. */
const PORTRAIT_DEMO: FrameSequence = { baseUrl: '/media/sequence-portrait', pattern: 'frame-{###}.jpg', frameCount: 240 }

function ListingOrDraft({ listing }: { listing: ListingWithRelations }) {
  const [params] = useSearchParams()
  const draftMode = params.get('draft') === '1'
  const editing = draftMode && params.get('edit') === '1'
  const [draft, setDraft] = useState<ListingDraft | null>(() => (draftMode ? loadDraft(listing.id) : null))

  useEffect(() => {
    if (!draftMode) return
    const sync = () => setDraft(loadDraft(listing.id))
    sync()
    window.addEventListener('storage', sync)
    return () => window.removeEventListener('storage', sync)
  }, [draftMode, listing.id])

  const commit = useCallback<EditCommit>(
    (sectionId, path, value) => {
      setDraft((d) => {
        if (!d) return d
        const next = applyEdit(d, sectionId, path, value)
        saveDraft(next)
        window.parent?.postMessage({ type: 'ye:draft-edited', listingId: listing.id }, window.location.origin)
        return next
      })
    },
    [listing.id],
  )

  if (!draftMode || !draft) return <Listing listing={listing} />
  const view: ListingWithRelations = {
    ...listing,
    subtitle: draft.intro.tagline || listing.subtitle,
    summary: draft.intro.summary || listing.summary,
    page_sections: draftToRows(draft),
  }
  return (
    <EditContext.Provider value={editing ? commit : null}>
      <Listing listing={view} draft={draft} />
    </EditContext.Provider>
  )
}

function DraftSeo({ draft, listing }: { draft: ListingDraft; listing: ListingWithRelations }) {
  useEffect(() => {
    const previous = document.title
    if (draft.seo.title) document.title = draft.seo.title
    let meta = document.querySelector<HTMLMetaElement>('meta[name="description"]')
    const created = !meta
    if (!meta) {
      meta = document.createElement('meta')
      meta.name = 'description'
      document.head.appendChild(meta)
    }
    const prevDescription = meta.content
    meta.content = draft.seo.description
    return () => {
      document.title = previous
      if (created) meta.remove()
      else meta.content = prevDescription
    }
  }, [draft.seo.title, draft.seo.description])
  const ld = listingJsonLd(draft, factsFromListing(listing), window.location.href.split('?')[0])
  return <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(ld) }} />
}

function DraftStill({ listing, cover, firstFrame }: { listing: ListingWithRelations; cover: string | null; firstFrame: string | null }) {
  const image = firstFrame ?? cover
  return (
    <section className="draft-still" aria-label="Walkthrough">
      {image && <img src={image} alt="" decoding="async" />}
      <div className="draft-still__veil" aria-hidden />
      <div className="draft-still__copy">
        <h1>{listing.title}</h1>
        <span className="draft-still__tag">Walkthrough plays here on the live page</span>
      </div>
    </section>
  )
}

function Listing({ listing, draft }: { listing: ListingWithRelations; draft?: ListingDraft }) {
  const { slug: realtor } = useRealtor()
  const enquire = useCallback(() => {
    track('enquiry_click')
    document.getElementById('enquire')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [])

  const sequences = useMemo(() => {
    const out: Partial<Record<'landscape' | 'portrait', FrameSequence>> = {}
    for (const m of listing.listing_media) {
      if (m.kind !== 'frame_sequence') continue
      const seq = toSequence(m)
      if (!seq) continue
      const key = m.aspect === 'portrait' ? 'portrait' : 'landscape'
      out[key] ??= seq
    }
    return out
  }, [listing.listing_media])

  const gallery = useMemo(
    () =>
      listing.listing_media
        .filter((m) => m.kind === 'gallery' && m.public_url)
        .map((m) => ({ src: m.public_url!, alt: m.label ?? listing.title })),
    [listing.listing_media, listing.title],
  )

  const experience = asObject<ExperienceConfig>(listing.experience)
  const immersive = listing.experience_type === 'immersive' && Boolean(sequences.landscape || sequences.portrait)
  const beats = useMemo(
    () => [...(experience.beats ?? [])].filter((b) => b && b.text).sort((a, b) => a.at - b.at),
    [experience.beats],
  )

  const sections = listing.page_sections
  const hasSpecs = sections.some((s) => s.preset === 'specs')
  const hasGallery = sections.some((s) => s.preset === 'gallery')
  const cover = listing.cover_image_url ?? gallery[0]?.src ?? null

  const portraitDemo = new URLSearchParams(window.location.search).get('stage') === 'portrait'
  usePageview(draft || listing.status !== 'published' ? null : { realtor, listingId: listing.id, walk: immersive })

  const firstFrame = useMemo(() => {
    const seq = sequences.landscape ?? sequences.portrait
    return seq ? joinUrl(seq.baseUrl, expandFramePattern(seq.pattern, 1)) : null
  }, [sequences])

  return (
    <div className={`page page--listing ${immersive && !draft ? 'is-immersive' : 'is-photo'}${draft ? ' page--draft' : ''}`}>
      <SiteHeader variant="listing" onEnquire={enquire} />
      {draft ? <DraftSeo draft={draft} listing={listing} /> : <PreviewBar listing={listing} />}

      {draft ? (
        <DraftStill listing={listing} cover={cover} firstFrame={immersive ? firstFrame : null} />
      ) : immersive ? (
        <ScrollExperience
          key={`${listing.id}${portraitDemo ? ':portrait' : ''}`}
          sequences={portraitDemo ? { portrait: PORTRAIT_DEMO } : sequences}
          label={`${listing.title} walkthrough`}
          hero={{
            brand: experience.hero?.brand ?? listing.title,
            line: experience.hero?.line ?? listing.subtitle ?? undefined,
            support: experience.hero?.support ?? undefined,
            scrollHint: experience.hero?.scrollHint ?? 'Scroll to enter',
          }}
          beats={beats}
          mobileMode={asMobileMode(experience.mobile_mode)}
          onProgress={reportDepth}
        />
      ) : (
        <PhotoHero listing={listing} cover={cover} />
      )}

      <main className="listing-body">
        <ListingIntro listing={listing} showFacts={!hasSpecs} immersive={immersive} />
        <Sections sections={sections} gallery={gallery} fallbackImage={cover} onEnquire={enquire} />
        {!hasGallery && gallery.length > 0 && (
          <Sections
            sections={[
              {
                id: 'auto-gallery',
                listing_id: listing.id,
                preset: 'gallery',
                title: 'Inside',
                body: null,
                layout: 'full',
                style: {},
                content: {},
                sort_order: 999,
                is_visible: true,
                created_at: listing.created_at,
                updated_at: listing.updated_at,
              },
            ]}
            gallery={gallery}
            fallbackImage={cover}
            onEnquire={enquire}
          />
        )}
        <FloorPlans listing={listing} />
        <ListingEnquiry listing={listing} />
      </main>
      <SiteFooter />
    </div>
  )
}

function PhotoHero({ listing, cover }: { listing: ListingWithRelations; cover: string | null }) {
  const facts = [listing.location, ...listingFacts(listing)].filter(Boolean)
  return (
    <section className="photo-hero" aria-labelledby="listing-title">
      {cover && <img className="photo-hero__img" src={cover} alt="" fetchPriority="high" decoding="async" />}
      <div className="photo-hero__veil" aria-hidden />
      <div className="hero__grain" aria-hidden />
      <div className="photo-hero__content">
        {facts.length > 0 && <p className="photo-hero__facts">{facts.join('  ·  ')}</p>}
        <h1 id="listing-title" className="photo-hero__title">
          {listing.title}
        </h1>
        {listing.subtitle && <p className="photo-hero__subtitle">{listing.subtitle}</p>}
      </div>
    </section>
  )
}

function ListingIntro({
  listing,
  showFacts,
  immersive,
}: {
  listing: ListingWithRelations
  showFacts: boolean
  immersive: boolean
}) {
  const ref = useReveal<HTMLDivElement>()
  const facts: { label: string; value: string }[] = []
  if (listing.location) facts.push({ label: 'Location', value: listing.location })
  if (listing.bedrooms) facts.push({ label: 'Bedrooms', value: String(listing.bedrooms) })
  if (listing.bathrooms) facts.push({ label: 'Bathrooms', value: String(listing.bathrooms) })
  if (listing.area_sqft) facts.push({ label: 'Interior', value: `${listing.area_sqft.toLocaleString('en-US')} sq ft` })

  return (
    <section className="listing-intro" aria-label="Overview">
      <div className="listing-intro__inner reveal" ref={ref}>
        <div className="listing-intro__main">
          {immersive ? (
            <h1 className="listing-intro__title">{listing.title}</h1>
          ) : (
            <p className="eyebrow">Overview</p>
          )}
          {immersive && (
            <Editable sectionId="intro" path="tagline" value={listing.subtitle} className="listing-intro__subtitle" placeholder="Add a tagline" />
          )}
          <Editable sectionId="intro" path="summary" value={listing.summary} className="listing-intro__summary" placeholder="Add a short summary" />

        </div>
        <div className="listing-intro__aside">
          {listing.price_label && (
            <div className="listing-intro__price">
              <span>Guide</span>
              <strong>{listing.price_label}</strong>
            </div>
          )}
          {showFacts && facts.length > 0 && (
            <dl className="listing-intro__facts">
              {facts.map((f) => (
                <div key={f.label}>
                  <dt>{f.label}</dt>
                  <dd>{f.value}</dd>
                </div>
              ))}
            </dl>
          )}
          {!showFacts && listing.location && <p className="listing-intro__location">{listing.location}</p>}
        </div>
      </div>
    </section>
  )
}

function ListingEnquiry({ listing }: { listing: ListingWithRelations }) {
  const ref = useReveal<HTMLDivElement>()
  return (
    <section className="listing-enquiry" id="enquire" aria-labelledby="enquire-title">
      <div className="listing-enquiry__inner reveal" ref={ref}>
        <div>
          <p className="eyebrow">Private viewing</p>
          <h2 id="enquire-title" className="listing-enquiry__title">
            Arrange a visit to {listing.title}.
          </h2>
          <p className="listing-enquiry__body">
            One party at a time, with the drawings on the table. We reply within one working day.
          </p>
        </div>
        <EnquiryForm listingId={listing.id} listingTitle={listing.title} tone="dark" />
      </div>
    </section>
  )
}

function PreviewBar({ listing }: { listing: ListingWithRelations }) {
  const proto = useProto()
  if (proto.plan === 'free')
    return (
      <div className="preview-bar" role="status">
        <span>
          <strong>Private preview</strong> — only you can see this listing. Subscribe to publish and share it.
        </span>
        <Link to="/studio/plan">See plans</Link>
      </div>
    )
  if (listing.status === 'published') return null
  return (
    <div className="preview-bar" role="status">
      <span>
        <strong>{listing.status === 'draft' ? 'Draft' : 'Preview'}</strong> — only your team can see this page.
      </span>
      <Link to={`/studio/listings/${listing.id}`}>Edit listing</Link>
    </div>
  )
}

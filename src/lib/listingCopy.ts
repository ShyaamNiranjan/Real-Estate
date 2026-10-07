import type { SectionContent } from '../types/content'
import type { Json, ListingRow, PageSectionRow } from '../types/database'

/** Shared between the dev AI endpoint (server/listingAi.ts) and the Studio. Only text crosses the wire. */

export const TONES = [
  { key: 'luxury', label: 'Luxury', hint: 'Elevated, unhurried, editorial' },
  { key: 'modern', label: 'Modern', hint: 'Clean, confident, design-led' },
  { key: 'warm', label: 'Warm', hint: 'Inviting, lived-in, human' },
  { key: 'minimal', label: 'Minimal', hint: 'Short sentences, just the facts' },
] as const
export type Tone = (typeof TONES)[number]['key']

export const MIN_SUMMARY_WORDS = 40
export const MAX_SUMMARY_CHARS = 4000

export type ListingFacts = {
  title: string
  location: string | null
  price: string | null
  bedrooms: number | null
  bathrooms: number | null
  areaSqft: number | null
  experience: 'immersive walkthrough' | 'photography'
}

export type GenerateRequest = {
  listingId: string
  facts: ListingFacts
  summary: string
  tone: Tone
  country: string
}

/** What the model returns. Mirrors LISTING_COPY_SCHEMA below. */
export type ListingCopy = {
  seo: { title: string; description: string }
  intro: { tagline: string; summary: string }
  story: { eyebrow: string; heading: string; body: string }
  glanceExtras: { label: string; value: string }[]
  spaces: { eyebrow: string; heading: string; intro: string; items: { title: string; body: string }[] }
  location: { eyebrow: string; heading: string; body: string }
  faq: { heading: string; items: { question: string; answer: string }[] }
  cta: { heading: string; body: string; button: string }
  missing: string[]
}

const str = { type: 'string' } as const
const obj = (properties: Record<string, unknown>) => ({
  type: 'object',
  properties,
  required: Object.keys(properties),
  additionalProperties: false,
})

export const LISTING_COPY_SCHEMA = obj({
  seo: obj({ title: str, description: str }),
  intro: obj({ tagline: str, summary: str }),
  story: obj({ eyebrow: str, heading: str, body: str }),
  glanceExtras: { type: 'array', items: obj({ label: str, value: str }) },
  spaces: obj({ eyebrow: str, heading: str, intro: str, items: { type: 'array', items: obj({ title: str, body: str }) } }),
  location: obj({ eyebrow: str, heading: str, body: str }),
  faq: obj({ heading: str, items: { type: 'array', items: obj({ question: str, answer: str }) } }),
  cta: obj({ heading: str, body: str, button: str }),
  missing: { type: 'array', items: str },
})

export function factsFromListing(listing: ListingRow): ListingFacts {
  return {
    title: listing.title,
    location: listing.location,
    price: listing.price_label,
    bedrooms: listing.bedrooms,
    bathrooms: listing.bathrooms,
    areaSqft: listing.area_sqft,
    experience: listing.experience_type === 'immersive' ? 'immersive walkthrough' : 'photography',
  }
}

export function wordCount(text: string) {
  return text.trim().split(/\s+/).filter(Boolean).length
}

// Parsing -----------------------------------------------------------------------------------------

const s = (v: unknown, max = 2000) => (typeof v === 'string' ? v.trim().slice(0, max) : '')
const arr = (v: unknown) => (Array.isArray(v) ? v : [])

/** Tolerates code fences and missing fields; anything absent becomes empty and is hidden on the page. */
export function parseListingCopy(raw: string): ListingCopy {
  const start = raw.indexOf('{')
  const end = raw.lastIndexOf('}')
  if (start < 0 || end <= start) throw new Error('The writer returned no content')
  const j = JSON.parse(raw.slice(start, end + 1)) as Record<string, Record<string, unknown>>
  return {
    seo: { title: s(j.seo?.title, 70), description: s(j.seo?.description, 170) },
    intro: { tagline: s(j.intro?.tagline, 140), summary: s(j.intro?.summary, 600) },
    story: { eyebrow: s(j.story?.eyebrow, 40), heading: s(j.story?.heading, 120), body: s(j.story?.body) },
    glanceExtras: arr(j.glanceExtras)
      .map((x) => ({ label: s(x?.label, 30), value: s(x?.value, 40) }))
      .filter((x) => x.label && x.value)
      .slice(0, 2),
    spaces: {
      eyebrow: s(j.spaces?.eyebrow, 40),
      heading: s(j.spaces?.heading, 120),
      intro: s(j.spaces?.intro, 400),
      items: arr(j.spaces?.items)
        .map((x) => ({ title: s(x?.title, 60), body: s(x?.body, 300) }))
        .filter((x) => x.title)
        .slice(0, 4),
    },
    location: { eyebrow: s(j.location?.eyebrow, 40), heading: s(j.location?.heading, 120), body: s(j.location?.body) },
    faq: {
      heading: s(j.faq?.heading, 80),
      items: arr(j.faq?.items)
        .map((x) => ({ question: s(x?.question, 160), answer: s(x?.answer, 600) }))
        .filter((x) => x.question && x.answer)
        .slice(0, 6),
    },
    cta: { heading: s(j.cta?.heading, 100), body: s(j.cta?.body, 300), button: s(j.cta?.button, 30) },
    missing: arr(j.missing).map((x) => s(x, 80)).filter(Boolean).slice(0, 6),
  }
}

/**
 * Turns the partial JSON stream into readable prose for the "writing" animation: every string value
 * written so far, including the one still being typed.
 */
export function streamedProse(raw: string): string {
  const out: string[] = []
  const re = /:\s*"((?:[^"\\]|\\.)*)("?)/g
  let m: RegExpExecArray | null
  while ((m = re.exec(raw))) {
    const text = m[1].replace(/\\n/g, '\n').replace(/\\"/g, '"').replace(/\\\\/g, '\\')
    if (text.trim()) out.push(text)
  }
  return out.join('\n\n')
}

// Fair housing ------------------------------------------------------------------------------------

/** US fair-housing phrases the prompt forbids; re-checked on the output so the agent sees anything that slipped. */
export const FAIR_HOUSING_PHRASES = [
  'perfect for families',
  'ideal for families',
  'family neighborhood',
  'family neighbourhood',
  'great for kids',
  'no children',
  'adults only',
  'mature couple',
  'young professionals',
  'perfect for singles',
  'bachelor pad',
  'exclusive neighborhood',
  'exclusive neighbourhood',
  'exclusive community',
  'safe neighborhood',
  'safe neighbourhood',
  'walking distance to church',
  'near church',
  'near mosque',
  'near synagogue',
  'christian',
  'muslim',
  'jewish',
  'hispanic',
  'integrated',
  'able-bodied',
  'no wheelchairs',
  'handicap',
  'master bedroom',
  'his and hers',
  'man cave',
  'traditional neighborhood',
]

export function fairHousingFlags(copy: ListingCopy): string[] {
  const text = JSON.stringify(copy).toLowerCase()
  return FAIR_HOUSING_PHRASES.filter((p) => text.includes(p))
}

// Sections ----------------------------------------------------------------------------------------

export type DraftSection = Pick<PageSectionRow, 'id' | 'preset' | 'title' | 'body' | 'layout' | 'style' | 'content' | 'is_visible'>

export type ListingDraft = {
  listingId: string
  summary: string
  tone: Tone
  source: 'ai' | 'template'
  model?: string
  generatedAt: string
  editedAt?: string
  seo: ListingCopy['seo']
  intro: ListingCopy['intro']
  sections: DraftSection[]
  missing: string[]
  flags: string[]
}

let seq = 0
const sid = (preset: string) => `draft-${preset}-${Date.now().toString(36)}-${seq++}`

function section(preset: DraftSection['preset'], title: string, body: string, content: SectionContent, layout: DraftSection['layout'] = 'default'): DraftSection {
  return { id: sid(preset), preset, title: title || null, body: body || null, layout, style: {} as Json, content: content as Json, is_visible: true }
}

/** "At a glance" is built from the Details tab, never from the model, so the figures can't drift. */
export function glanceItems(facts: ListingFacts, extras: ListingCopy['glanceExtras'] = []) {
  const items: { label: string; value: string }[] = []
  if (facts.bedrooms) items.push({ label: 'Bedrooms', value: String(facts.bedrooms) })
  if (facts.bathrooms) items.push({ label: 'Bathrooms', value: String(facts.bathrooms) })
  if (facts.areaSqft) items.push({ label: 'Area', value: `${facts.areaSqft.toLocaleString('en-US')} sq ft` })
  items.push({ label: 'Experience', value: facts.experience === 'immersive walkthrough' ? 'Immersive' : 'Photography' })
  return [...items, ...extras].slice(0, 6)
}

export function draftFromCopy(req: GenerateRequest, copy: ListingCopy, model?: string): ListingDraft {
  const sections: DraftSection[] = [
    section('text', copy.story.heading, copy.story.body, { eyebrow: copy.story.eyebrow || undefined }),
    section('specs', 'At a glance', '', { items: glanceItems(req.facts, copy.glanceExtras) }, 'tiles'),
  ]
  if (copy.spaces.items.length)
    sections.push(section('tiles', copy.spaces.heading, copy.spaces.intro, { eyebrow: copy.spaces.eyebrow || undefined, items: copy.spaces.items }, 'tiles'))
  if (copy.location.body) sections.push(section('text', copy.location.heading, copy.location.body, { eyebrow: copy.location.eyebrow || undefined }))
  if (copy.faq.items.length)
    sections.push(
      section('faq', copy.faq.heading || 'Questions buyers ask', '', {
        items: copy.faq.items.map((f) => ({ title: f.question, body: f.answer })),
      }),
    )
  sections.push(
    section('cta', copy.cta.heading || 'Arrange a private viewing.', copy.cta.body, { ctaLabel: copy.cta.button || 'Enquire', ctaAction: 'enquiry' }),
  )
  return {
    listingId: req.listingId,
    summary: req.summary,
    tone: req.tone,
    source: 'ai',
    model,
    generatedAt: new Date().toISOString(),
    seo: copy.seo,
    intro: copy.intro,
    sections,
    missing: copy.missing,
    flags: fairHousingFlags(copy),
  }
}

/** Used when the writer is unavailable: the agent still gets a complete, editable page. */
export function templateDraft(req: GenerateRequest): ListingDraft {
  const { facts, summary } = req
  const paragraphs = summary.split(/\n+/).map((p) => p.trim()).filter(Boolean)
  const place = facts.location ? ` in ${facts.location}` : ''
  return {
    listingId: req.listingId,
    summary,
    tone: req.tone,
    source: 'template',
    generatedAt: new Date().toISOString(),
    seo: {
      title: `${facts.title}${place}`.slice(0, 60),
      description: summary.replace(/\s+/g, ' ').slice(0, 155),
    },
    intro: { tagline: '', summary: paragraphs[0] ?? '' },
    sections: [
      section('text', `About ${facts.title}`, paragraphs.join('\n\n'), {}),
      section('specs', 'At a glance', '', { items: glanceItems(facts) }, 'tiles'),
      section('cta', 'Arrange a private viewing.', '', { ctaLabel: 'Enquire', ctaAction: 'enquiry' }),
    ],
    missing: [],
    flags: [],
  }
}

// Draft storage (prototype: the browser, so the shared production database is never touched) -----

const key = (listingId: string) => `ye:listing-draft:${listingId}`

export function loadDraft(listingId: string): ListingDraft | null {
  try {
    const raw = localStorage.getItem(key(listingId))
    return raw ? (JSON.parse(raw) as ListingDraft) : null
  } catch {
    return null
  }
}

export function saveDraft(draft: ListingDraft) {
  localStorage.setItem(key(draft.listingId), JSON.stringify(draft))
}

export function clearDraft(listingId: string) {
  localStorage.removeItem(key(listingId))
}

/** Applies one in-place edit. `sectionId` "intro" targets the overview; paths look like "content.items.2.body". */
export function applyEdit(draft: ListingDraft, sectionId: string, path: string, value: string): ListingDraft {
  const editedAt = new Date().toISOString()
  if (sectionId === 'intro') {
    return { ...draft, editedAt, intro: { ...draft.intro, [path]: value } }
  }
  const sections = draft.sections.map((s) => {
    if (s.id !== sectionId) return s
    const next = structuredClone(s) as DraftSection & Record<string, unknown>
    const parts = path.split('.')
    let target = next as Record<string, unknown>
    for (const part of parts.slice(0, -1)) {
      const child = target[part]
      target = (child && typeof child === 'object' ? child : (target[part] = {})) as Record<string, unknown>
    }
    const last = parts[parts.length - 1]
    if (path === 'title' || path === 'body') target[last] = value || null
    else target[last] = value || undefined
    return next
  })
  return { ...draft, editedAt, sections }
}

export function draftToRows(draft: ListingDraft): PageSectionRow[] {
  const now = draft.editedAt ?? draft.generatedAt
  return draft.sections
    .filter((s) => s.is_visible)
    .map((s, i) => ({ ...s, listing_id: draft.listingId, sort_order: i, created_at: now, updated_at: now }))
}

/** schema.org markup for the listing and its FAQ — what search and answer engines read. */
export function listingJsonLd(draft: ListingDraft, facts: ListingFacts, url: string) {
  const faq = draft.sections.find((s) => s.preset === 'faq')
  const faqItems = ((faq?.content as SectionContent | undefined)?.items ?? []).filter((i) => i.title && i.body)
  const graph: Record<string, unknown>[] = [
    {
      '@type': 'RealEstateListing',
      name: facts.title,
      description: draft.seo.description,
      url,
      ...(facts.location ? { contentLocation: { '@type': 'Place', name: facts.location } } : {}),
      ...(facts.price ? { offers: { '@type': 'Offer', description: facts.price } } : {}),
      about: {
        '@type': 'SingleFamilyResidence',
        ...(facts.bedrooms ? { numberOfBedrooms: facts.bedrooms } : {}),
        ...(facts.bathrooms ? { numberOfBathroomsTotal: facts.bathrooms } : {}),
        ...(facts.areaSqft ? { floorSize: { '@type': 'QuantitativeValue', value: facts.areaSqft, unitCode: 'FTK' } } : {}),
      },
    },
  ]
  if (faqItems.length)
    graph.push({
      '@type': 'FAQPage',
      mainEntity: faqItems.map((i) => ({ '@type': 'Question', name: i.title, acceptedAnswer: { '@type': 'Answer', text: i.body } })),
    })
  return { '@context': 'https://schema.org', '@graph': graph }
}

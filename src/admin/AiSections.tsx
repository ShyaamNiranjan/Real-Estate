import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  MAX_SUMMARY_CHARS,
  MIN_SUMMARY_WORDS,
  TONES,
  clearDraft,
  draftFromCopy,
  factsFromListing,
  loadDraft,
  parseListingCopy,
  saveDraft,
  streamedProse,
  templateDraft,
  wordCount,
  type GenerateRequest,
  type ListingDraft,
  type Tone,
} from '../lib/listingCopy'
import { useRealtor } from '../lib/realtor'
import type { EditorData } from './ListingEditor'
import { errorMessage, useToast } from './ui'

type Phase = 'compose' | 'writing' | 'building' | 'done' | 'preview'
type Device = 'desktop' | 'phone'

const BUILD_STEPS = ['Story', 'At a glance', 'Spaces', 'Location', 'Questions buyers ask', 'Call to action', 'Search snippet']

const SUMMARY_HINTS = [
  'What makes it special: light, views, materials, the layout',
  'The rooms that matter and how they connect',
  'The street and neighbourhood: walks, schools, transport',
  'Anything recent: renovation, systems, outdoor space',
]

class GenerateError extends Error {
  readonly retryable: boolean
  constructor(message: string, retryable: boolean) {
    super(message)
    this.retryable = retryable
  }
}

async function requestCopy(req: GenerateRequest, onText: (raw: string) => void, signal: AbortSignal) {
  const res = await fetch('/api/listing-content', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(req),
    signal,
  })
  if (!res.ok || !res.body) {
    const body = (await res.json().catch(() => null)) as { error?: string } | null
    throw new GenerateError(body?.error ?? `The writer returned ${res.status}`, res.status >= 500)
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let raw = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    raw += decoder.decode(value, { stream: true })
    onText(raw)
  }
  return { raw, model: res.headers.get('x-ye-model') ?? undefined, remaining: Number(res.headers.get('x-ye-remaining') ?? NaN) }
}

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms))

export function AiSections({ data, onClassic }: { data: EditorData; onClassic: () => void }) {
  const toast = useToast()
  const { listing } = data
  const { listing: listingPath } = useRealtor()
  const [draft, setDraft] = useState<ListingDraft | null>(() => loadDraft(listing.id))
  const [phase, setPhase] = useState<Phase>(() => (loadDraft(listing.id) ? 'preview' : 'compose'))
  const [summary, setSummary] = useState(() => draft?.summary ?? listing.summary ?? '')
  const [tone, setTone] = useState<Tone>(() => draft?.tone ?? 'luxury')
  const [prose, setProse] = useState('')
  const [built, setBuilt] = useState(0)
  const [notice, setNotice] = useState<string | null>(null)
  const [remaining, setRemaining] = useState<number | null>(null)
  const [editing, setEditing] = useState(false)
  const [device, setDevice] = useState<Device>('desktop')
  const [confirmRegen, setConfirmRegen] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const proseRef = useRef<HTMLDivElement>(null)

  const words = wordCount(summary)
  const ready = words >= MIN_SUMMARY_WORDS

  useEffect(() => {
    const sync = () => setDraft(loadDraft(listing.id))
    window.addEventListener('storage', sync)
    return () => {
      window.removeEventListener('storage', sync)
      abortRef.current?.abort()
    }
  }, [listing.id])

  useEffect(() => {
    proseRef.current?.scrollTo({ top: proseRef.current.scrollHeight })
  }, [prose])

  const generate = useCallback(async () => {
    setConfirmRegen(false)
    setNotice(null)
    setEditing(false)
    setProse('')
    setBuilt(0)
    setPhase('writing')
    const req: GenerateRequest = {
      listingId: listing.id,
      facts: factsFromListing(listing),
      summary: summary.trim(),
      tone,
      country: 'United States',
    }
    const abort = new AbortController()
    abortRef.current = abort

    let next: ListingDraft | null = null
    for (let attempt = 0; attempt < 2 && !next; attempt++) {
      try {
        const out = await requestCopy(req, (raw) => setProse(streamedProse(raw)), abort.signal)
        next = draftFromCopy(req, parseListingCopy(out.raw), out.model)
        if (Number.isFinite(out.remaining)) setRemaining(out.remaining)
      } catch (err) {
        if (abort.signal.aborted) return
        const retryable = !(err instanceof GenerateError) || err.retryable
        if (!retryable) {
          setNotice(errorMessage(err))
          setPhase(draft ? 'preview' : 'compose')
          return
        }
        if (attempt === 1) {
          next = templateDraft(req)
          setNotice('The writer is busy right now, so we laid your summary into the standard sections. Regenerate in a minute for the full write-up.')
        } else setProse('')
      }
    }
    if (!next) return

    setPhase('building')
    for (let i = 1; i <= BUILD_STEPS.length; i++) {
      await wait(180)
      if (abort.signal.aborted) return
      setBuilt(i)
    }
    saveDraft(next)
    setDraft(next)
    setPhase('done')
    await wait(1300)
    if (!abort.signal.aborted) setPhase('preview')
  }, [draft, listing, summary, tone])

  const regenerate = () => {
    if (draft?.editedAt && !confirmRegen) return setConfirmRegen(true)
    void generate()
  }

  const discard = () => {
    clearDraft(listing.id)
    setDraft(null)
    setEditing(false)
    setPhase('compose')
    toast('Draft discarded')
  }

  const previewSrc = useMemo(
    () => `${listingPath(listing.slug)}?draft=1${editing ? '&edit=1' : ''}`,
    [editing, listing.slug, listingPath],
  )

  if (phase === 'writing' || phase === 'building' || phase === 'done')
    return (
      <section className="ai-stage" aria-live="polite">
        {phase === 'writing' && (
          <>
            <p className="ai-stage__label">
              <span className="ai-pulse" aria-hidden /> Writing your content…
            </p>
            <div className="ai-prose" ref={proseRef}>
              {prose ? prose : <span className="ai-prose__wait">Reading your summary and the listing details</span>}
              <span className="ai-caret" aria-hidden />
            </div>
          </>
        )}
        {phase === 'building' && (
          <>
            <p className="ai-stage__label">
              <span className="ai-pulse" aria-hidden /> Building your sections…
            </p>
            <ul className="ai-build">
              {BUILD_STEPS.map((s, i) => (
                <li key={s} className={i < built ? 'is-done' : ''}>
                  <span aria-hidden>{i < built ? '✓' : ''}</span>
                  {s}
                </li>
              ))}
            </ul>
          </>
        )}
        {phase === 'done' && (
          <div className="ai-done">
            <svg className="ai-tick" viewBox="0 0 52 52" aria-hidden>
              <circle cx="26" cy="26" r="24" />
              <path d="M15 27l7 7 15-16" />
            </svg>
            <p>Your sections are ready</p>
          </div>
        )}
        {phase === 'writing' && (
          <button type="button" className="a-btn a-btn--ghost a-btn--sm" onClick={() => {
            abortRef.current?.abort()
            setPhase(draft ? 'preview' : 'compose')
          }}>
            Cancel
          </button>
        )}
      </section>
    )

  if (phase === 'preview' && draft)
    return (
      <section className="ai-preview">
        <div className="ai-toolbar">
          <div className="ai-toolbar__group">
            <button type="button" className="a-btn a-btn--primary" onClick={() => setEditing((e) => !e)}>
              {editing ? 'Done editing' : 'Customise'}
            </button>
            <div className="ai-seg" role="group" aria-label="Preview width">
              {(['desktop', 'phone'] as const).map((d) => (
                <button key={d} type="button" className={device === d ? 'is-on' : ''} onClick={() => setDevice(d)}>
                  {d === 'desktop' ? 'Desktop' : 'Phone'}
                </button>
              ))}
            </div>
          </div>
          <div className="ai-toolbar__group">
            <button type="button" className="a-btn a-btn--ghost" onClick={() => setPhase('compose')}>
              Edit summary
            </button>
            <button type="button" className="a-btn a-btn--ghost" onClick={regenerate}>
              {confirmRegen ? 'Overwrite your edits?' : 'Regenerate'}
            </button>
            <button type="button" className="a-btn a-btn--ghost" onClick={discard}>
              Discard
            </button>
          </div>
        </div>

        {editing && <p className="a-note">Click any text on the page to edit it. Changes save as you go. Empty fields are hidden on the live page.</p>}
        {notice && <p className="a-note a-note--warn">{notice}</p>}
        <DraftNotes draft={draft} remaining={remaining} />

        <div className={`ai-frame ai-frame--${device}`}>
          <iframe key={previewSrc} src={previewSrc} title="Listing preview" />
        </div>
      </section>
    )

  return (
    <section className="ai-compose">
      <div className="ai-compose__main">
        <h2 className="ai-compose__title">Tell us about this property</h2>
        <p className="a-muted">
          Write it the way you would describe it to a buyer on the phone. We turn it into the page sections, the search snippet and the
          buyer questions, using only what you write here and on the Details tab.
        </p>
        <textarea
          className="a-input ai-summary"
          value={summary}
          maxLength={MAX_SUMMARY_CHARS}
          onChange={(e) => setSummary(e.target.value)}
          placeholder="A 1920s brick house on a quiet, tree-lined street, fully renovated in 2024…"
          rows={10}
        />
        <div className="ai-compose__meta">
          <span className={ready ? 'is-ok' : ''}>
            {words} {words === 1 ? 'word' : 'words'}
            {!ready && ` · at least ${MIN_SUMMARY_WORDS} for a strong page`}
          </span>
          <label className="ai-tone">
            Tone
            <select className="a-input" value={tone} onChange={(e) => setTone(e.target.value as Tone)}>
              {TONES.map((t) => (
                <option key={t.key} value={t.key}>
                  {t.label} · {t.hint}
                </option>
              ))}
            </select>
          </label>
        </div>
        {notice && <p className="a-note a-note--warn">{notice}</p>}
        <div className="ai-compose__actions">
          <button type="button" className="a-btn a-btn--primary" disabled={!ready} onClick={regenerate}>
            See preview
          </button>
          {draft && (
            <button type="button" className="a-btn a-btn--ghost" onClick={() => setPhase('preview')}>
              Back to preview
            </button>
          )}
          <button type="button" className="a-link" onClick={onClassic}>
            Use the classic section editor
          </button>
        </div>
      </div>
      <aside className="ai-compose__aside">
        <p className="ai-label">Good summaries mention</p>
        <ul>
          {SUMMARY_HINTS.map((h) => (
            <li key={h}>{h}</li>
          ))}
        </ul>
        <p className="ai-label">Taken from Details</p>
        <p className="a-muted">Price, bedrooms, bathrooms and area come from the Details tab, so keep those up to date there.</p>
        <p className="ai-privacy">Only this text and the listing details are sent to the writer. No photos, names or contact details.</p>
      </aside>
    </section>
  )
}

function DraftNotes({ draft, remaining }: { draft: ListingDraft; remaining: number | null }) {
  const bits: string[] = []
  if (draft.source === 'template') bits.push('Standard layout (not AI-written)')
  else if (draft.model) bits.push(`Written by ${draft.model}`)
  if (remaining !== null) bits.push(`${remaining} regenerations left today`)
  if (draft.editedAt) bits.push('Edited by you')
  return (
    <>
      {draft.missing.length > 0 && (
        <div className="a-note">
          <strong>Add these for a stronger page:</strong>
          <ul>
            {draft.missing.map((m) => (
              <li key={m}>{m}</li>
            ))}
          </ul>
        </div>
      )}
      {draft.flags.length > 0 && (
        <div className="a-note a-note--warn">
          <strong>Check this wording for fair-housing rules:</strong> {draft.flags.map((f) => `“${f}”`).join(', ')}
        </div>
      )}
      {bits.length > 0 && <p className="ai-meta">{bits.join(' · ')}</p>}
    </>
  )
}

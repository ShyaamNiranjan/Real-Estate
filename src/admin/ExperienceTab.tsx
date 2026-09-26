import { useMemo, useState } from 'react'
import { expandFramePattern, joinUrl } from '../lib/format'
import { asObject, type ExperienceConfig, type ScrollBeat } from '../types/content'
import type { Json, ListingMediaRow, ListingRow, MediaAspect } from '../types/database'
import { createMedia, deleteMedia, updateListing, updateMedia, uploadFrameSequence } from './api'
import type { EditorData } from './ListingEditor'
import { ConfirmButton, Field, Kbd, errorMessage, isMac, useSaveShortcut, useToast, useUnsavedGuard } from './ui'

type Props = {
  data: EditorData
  onListing: (l: ListingRow) => void
  setMedia: (fn: (m: ListingMediaRow[]) => ListingMediaRow[]) => void
}

const newBeat = (at: number): ScrollBeat => ({
  id: crypto.randomUUID().slice(0, 8),
  side: 'left',
  at,
  label: '',
  text: '',
})

export function ExperienceTab({ data, onListing, setMedia }: Props) {
  const toast = useToast()
  const { listing } = data
  const initial = useMemo(() => asObject<ExperienceConfig>(listing.experience), [listing.experience])
  const [hero, setHero] = useState(initial.hero ?? {})
  const [beats, setBeats] = useState<ScrollBeat[]>(() => [...(initial.beats ?? [])].sort((a, b) => a.at - b.at))
  const [saving, setSaving] = useState(false)

  const dirty = JSON.stringify({ hero, beats }) !== JSON.stringify({ hero: initial.hero ?? {}, beats: [...(initial.beats ?? [])].sort((a, b) => a.at - b.at) })
  useUnsavedGuard(dirty)

  const save = async () => {
    if (saving) return
    setSaving(true)
    try {
      const clean = beats
        .filter((b) => b.text.trim())
        .map((b) => ({ ...b, at: Math.min(0.94, Math.max(0.04, Number(b.at) || 0.05)) }))
        .sort((a, b) => a.at - b.at)
      const experience = { ...asObject<Record<string, Json>>(listing.experience), hero, beats: clean } as unknown as Json
      const saved = await updateListing(listing.id, { experience })
      onListing(saved)
      setBeats(clean)
      toast('Walkthrough saved')
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setSaving(false)
    }
  }
  useSaveShortcut(() => void save())

  const updateBeat = (i: number, patch: Partial<ScrollBeat>) => setBeats((b) => b.map((x, j) => (j === i ? { ...x, ...patch } : x)))

  return (
    <div className="a-editor">
      <div className="a-editor__main">
        <Sequences data={data} setMedia={setMedia} />

        <section className="a-card">
          <div className="a-card__head">
            <div>
              <h2 className="a-card__title">Scroll beats</h2>
              <p className="a-muted">Short captions that appear as the camera moves. Position is how far through the walkthrough (0–100%).</p>
            </div>
            <button
              type="button"
              className="a-btn a-btn--ghost"
              onClick={() => setBeats((b) => [...b, newBeat(Math.min(0.9, (b.at(-1)?.at ?? 0) + 0.15))])}
            >
              Add beat
            </button>
          </div>

          <div className="a-timeline" aria-hidden>
            {beats.map((b, i) => (
              <span key={b.id} className={`a-timeline__mark a-timeline__mark--${b.side}`} style={{ left: `${b.at * 100}%` }}>
                {i + 1}
              </span>
            ))}
          </div>

          {beats.length === 0 && <p className="a-muted">No beats yet. The walkthrough will play with just the hero.</p>}

          <ol className="a-beats">
            {beats.map((b, i) => (
              <li key={b.id} className="a-beat">
                <span className="a-beat__num">{String(i + 1).padStart(2, '0')}</span>
                <div className="a-beat__fields">
                  <div className="a-grid a-grid--beat">
                    <Field label="Label">
                      {(id) => <input id={id} className="a-input" value={b.label} onChange={(e) => updateBeat(i, { label: e.target.value })} placeholder="Arrival" />}
                    </Field>
                    <Field label={`Position · ${Math.round(b.at * 100)}%`}>
                      {(id) => (
                        <input
                          id={id}
                          type="range"
                          min={0.04}
                          max={0.94}
                          step={0.01}
                          value={b.at}
                          onChange={(e) => updateBeat(i, { at: Number(e.target.value) })}
                          className="a-range"
                        />
                      )}
                    </Field>
                    <Field label="Side">
                      {(id) => (
                        <select id={id} className="a-input" value={b.side} onChange={(e) => updateBeat(i, { side: e.target.value as ScrollBeat['side'] })}>
                          <option value="left">Left</option>
                          <option value="right">Right</option>
                        </select>
                      )}
                    </Field>
                  </div>
                  <Field label="Caption" wide>
                    {(id) => (
                      <textarea
                        id={id}
                        className="a-input"
                        rows={2}
                        value={b.text}
                        onChange={(e) => updateBeat(i, { text: e.target.value })}
                        placeholder="One step in, the ceiling lifts and the noise drops."
                      />
                    )}
                  </Field>
                </div>
                <button type="button" className="a-link a-link--danger" onClick={() => setBeats((all) => all.filter((_, j) => j !== i))}>
                  Remove
                </button>
              </li>
            ))}
          </ol>
        </section>
      </div>

      <aside className="a-editor__side">
        <section className="a-card a-card--sticky">
          <h2 className="a-card__title">Opening frame</h2>
          <p className="a-muted">Held on screen for the first few scrolls.</p>
          <div className="a-form">
            <Field label="Brand line">
              {(id) => <input id={id} className="a-input" value={hero.brand ?? ''} onChange={(e) => setHero({ ...hero, brand: e.target.value })} placeholder={listing.title} />}
            </Field>
            <Field label="Headline">
              {(id) => <input id={id} className="a-input" value={hero.line ?? ''} onChange={(e) => setHero({ ...hero, line: e.target.value })} placeholder={listing.subtitle ?? ''} />}
            </Field>
            <Field label="Supporting sentence">
              {(id) => <textarea id={id} className="a-input" rows={2} value={hero.support ?? ''} onChange={(e) => setHero({ ...hero, support: e.target.value })} />}
            </Field>
            <Field label="Scroll hint">
              {(id) => (
                <input id={id} className="a-input" value={hero.scrollHint ?? ''} onChange={(e) => setHero({ ...hero, scrollHint: e.target.value })} placeholder="Scroll to enter" />
              )}
            </Field>
          </div>
          <div className="a-card__actions">
            <button type="button" className="a-btn a-btn--primary a-btn--block" onClick={() => void save()} disabled={saving || !dirty}>
              {saving ? 'Saving…' : dirty ? 'Save walkthrough' : 'Saved'}
              <Kbd>{isMac ? '⌘' : 'Ctrl'} S</Kbd>
            </button>
            <a className="a-btn a-btn--ghost a-btn--block" href={`/listing/${listing.slug}`} target="_blank" rel="noreferrer">
              Open preview ↗
            </a>
          </div>
        </section>
      </aside>
    </div>
  )
}

// Frame sequences ------------------------------------------------------------

function Sequences({ data, setMedia }: { data: EditorData; setMedia: Props['setMedia'] }) {
  const toast = useToast()
  const { listing, media } = data
  const sequences = media.filter((m) => m.kind === 'frame_sequence')
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null)
  const [uploadAspect, setUploadAspect] = useState<MediaAspect>('landscape')

  const add = async () => {
    try {
      const row = await createMedia({
        listing_id: listing.id,
        kind: 'frame_sequence',
        public_url: '/media/sequence',
        frame_count: 240,
        frame_pattern: 'frame-{###}.jpg',
        aspect: sequences.some((s) => s.aspect === 'landscape') ? 'portrait' : 'landscape',
        label: 'Frame sequence',
        sort_order: sequences.length,
      })
      setMedia((m) => [...m, row])
    } catch (err) {
      toast(errorMessage(err), 'error')
    }
  }

  const uploadFrames = async (files: File[]) => {
    if (!files.length) return
    setProgress({ done: 0, total: files.length })
    try {
      const res = await uploadFrameSequence(listing.id, files, (done, total) => setProgress({ done, total }))
      const row = await createMedia({
        listing_id: listing.id,
        kind: 'frame_sequence',
        storage_path: res.prefix,
        public_url: res.baseUrl,
        frame_count: res.count,
        frame_pattern: res.pattern,
        aspect: uploadAspect,
        label: `Uploaded ${uploadAspect} sequence`,
        sort_order: sequences.length,
      })
      setMedia((m) => [...m, row])
      toast(`${res.count} frames uploaded`)
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setProgress(null)
    }
  }

  return (
    <section className="a-card">
      <div className="a-card__head">
        <div>
          <h2 className="a-card__title">Frame sequences</h2>
          <p className="a-muted">
            One landscape sequence for desktop and an optional portrait one for phones. Frames are drawn to a canvas as the visitor scrolls.
          </p>
        </div>
        <button type="button" className="a-btn a-btn--ghost" onClick={() => void add()}>
          Add by path
        </button>
      </div>

      {sequences.length === 0 && <p className="a-note a-note--warn">No sequences yet — the listing falls back to the photo layout.</p>}

      <div className="a-seqs">
        {sequences.map((s) => (
          <SequenceRow key={s.id} row={s} setMedia={setMedia} />
        ))}
      </div>

      <div className="a-upload-frames">
        <div>
          <h3 className="a-card__subtitle">Upload frames</h3>
          <p className="a-muted">
            Select a folder or a set of numbered JPGs (max 5 MB each). They are renamed <code>frame-001.jpg…</code> in the{' '}
            <code>listing-frames</code> bucket.
          </p>
        </div>
        <div className="a-inline-form">
          <select className="a-input" value={uploadAspect} onChange={(e) => setUploadAspect(e.target.value as MediaAspect)} aria-label="Aspect">
            <option value="landscape">Landscape</option>
            <option value="portrait">Portrait</option>
          </select>
          <label className="a-btn a-btn--ghost a-file">
            {progress ? `Uploading ${progress.done}/${progress.total}` : 'Choose frames'}
            <input
              type="file"
              multiple
              accept="image/jpeg,image/png,image/webp"
              disabled={Boolean(progress)}
              onChange={(e) => {
                void uploadFrames(Array.from(e.target.files ?? []))
                e.target.value = ''
              }}
            />
          </label>
        </div>
        {progress && (
          <div className="a-progress" aria-hidden>
            <span style={{ transform: `scaleX(${progress.done / progress.total})` }} />
          </div>
        )}
      </div>

      <details className="a-details">
        <summary>From a video file</summary>
        {/* TODO(v2): server-side worker (Edge Function + FFmpeg) that turns an uploaded listing-videos object into frames automatically. */}
        <p className="a-muted">
          Automatic video → frame extraction is not part of v1. Export frames locally with FFmpeg, then upload them above:
        </p>
        <pre className="a-code">
          {`# landscape, 240 frames, 1920px wide
ffmpeg -i walkthrough.mp4 -vf "fps=240/DURATION,scale=1920:-2" -q:v 3 frame-%03d.jpg

# portrait (phones), 120 frames, 900px wide
ffmpeg -i walkthrough-portrait.mp4 -vf "fps=120/DURATION,scale=900:-2" -q:v 4 frame-%03d.jpg`}
        </pre>
        <p className="a-muted">Replace DURATION with the clip length in seconds.</p>
      </details>
    </section>
  )
}

function SequenceRow({ row, setMedia }: { row: ListingMediaRow; setMedia: Props['setMedia'] }) {
  const toast = useToast()
  const meta = asObject<{ px_per_frame?: number }>(row.metadata)
  const [draft, setDraft] = useState({
    public_url: row.public_url ?? '',
    frame_count: String(row.frame_count ?? ''),
    frame_pattern: row.frame_pattern ?? 'frame-{###}.jpg',
    aspect: (row.aspect ?? 'landscape') as MediaAspect,
    px_per_frame: meta.px_per_frame ? String(meta.px_per_frame) : '',
  })
  const [saving, setSaving] = useState(false)
  const count = Number(draft.frame_count) || 0
  const validPattern = /\{#+\}/.test(draft.frame_pattern)
  const thumb = (n: number) => (draft.public_url && validPattern ? joinUrl(draft.public_url, expandFramePattern(draft.frame_pattern, n)) : '')

  const save = async () => {
    if (!validPattern) return toast('Pattern needs a {###} placeholder', 'error')
    if (count < 2) return toast('Frame count must be at least 2', 'error')
    setSaving(true)
    try {
      const px = Number(draft.px_per_frame)
      const saved = await updateMedia(row.id, {
        public_url: draft.public_url.trim(),
        frame_count: count,
        frame_pattern: draft.frame_pattern.trim(),
        aspect: draft.aspect,
        metadata: { ...asObject<Record<string, Json>>(row.metadata), px_per_frame: px > 0 ? px : null },
      })
      setMedia((m) => m.map((x) => (x.id === saved.id ? saved : x)))
      toast('Sequence saved')
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setSaving(false)
    }
  }

  const remove = async () => {
    try {
      await deleteMedia(row)
      setMedia((m) => m.filter((x) => x.id !== row.id))
      toast('Sequence removed')
    } catch (err) {
      toast(errorMessage(err), 'error')
    }
  }

  return (
    <div className="a-seq">
      <div className="a-seq__thumbs">
        {thumb(1) && <img src={thumb(1)} alt="First frame" loading="lazy" />}
        {count > 1 && thumb(count) && <img src={thumb(count)} alt="Last frame" loading="lazy" />}
      </div>
      <div className="a-grid a-grid--seq">
        <Field label="Base URL" wide hint={row.storage_path ? 'Uploaded to storage' : 'Path under /public or any CDN folder'}>
          {(id) => <input id={id} className="a-input a-input--mono" value={draft.public_url} onChange={(e) => setDraft({ ...draft, public_url: e.target.value })} />}
        </Field>
        <Field label="File pattern" error={validPattern ? null : 'Needs {###}'}>
          {(id) => <input id={id} className="a-input a-input--mono" value={draft.frame_pattern} onChange={(e) => setDraft({ ...draft, frame_pattern: e.target.value })} />}
        </Field>
        <Field label="Frames">
          {(id) => <input id={id} className="a-input" inputMode="numeric" value={draft.frame_count} onChange={(e) => setDraft({ ...draft, frame_count: e.target.value })} />}
        </Field>
        <Field label="Aspect">
          {(id) => (
            <select id={id} className="a-input" value={draft.aspect} onChange={(e) => setDraft({ ...draft, aspect: e.target.value as MediaAspect })}>
              <option value="landscape">Landscape (desktop)</option>
              <option value="portrait">Portrait (phones)</option>
            </select>
          )}
        </Field>
        <Field label="Px per frame" hint="Blank = auto">
          {(id) => <input id={id} className="a-input" inputMode="numeric" value={draft.px_per_frame} onChange={(e) => setDraft({ ...draft, px_per_frame: e.target.value })} />}
        </Field>
      </div>
      <div className="a-seq__actions">
        <button type="button" className="a-btn a-btn--ghost" onClick={() => void save()} disabled={saving}>
          {saving ? 'Saving…' : 'Save sequence'}
        </button>
        <ConfirmButton onConfirm={() => void remove()} className="a-link a-link--danger" confirmLabel="Remove sequence?">
          Remove
        </ConfirmButton>
      </div>
    </div>
  )
}

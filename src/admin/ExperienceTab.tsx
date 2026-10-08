import { useEffect, useMemo, useRef, useState, type DragEvent } from 'react'
import { useRealtor } from '../lib/realtor'
import { expandFramePattern, joinUrl } from '../lib/format'
import { BEATS_END, asMobileMode, asObject, beatEnd, type ExperienceConfig, type MobileMode, type ScrollBeat } from '../types/content'
import type { Json, ListingMediaRow, ListingRow, MediaAspect } from '../types/database'
import { createMedia, deleteMedia, updateListing, updateMedia, uploadFrameSequence } from './api'
import type { EditorData } from './ListingEditor'
import { VIDEO_PRESETS, extractFrames, probeVideo, type VideoInfo } from './videoFrames'
import { ConfirmButton, Field, Kbd, errorMessage, isMac, useSaveShortcut, useToast, useUnsavedGuard } from './ui'

type Props = {
  data: EditorData
  onListing: (l: ListingRow) => void
  setMedia: (fn: (m: ListingMediaRow[]) => ListingMediaRow[]) => void
}

const MIN_BEAT = 0.02

const newBeat = (at: number): ScrollBeat => ({
  id: crypto.randomUUID().slice(0, 8),
  side: 'left',
  at,
  label: '',
  text: '',
})

export function ExperienceTab({ data, onListing, setMedia }: Props) {
  const toast = useToast()
  const { listing: listingPath } = useRealtor()
  const { listing } = data
  const initial = useMemo(() => asObject<ExperienceConfig>(listing.experience), [listing.experience])
  const [hero, setHero] = useState(initial.hero ?? {})
  const [beats, setBeats] = useState<ScrollBeat[]>(() => [...(initial.beats ?? [])].sort((a, b) => a.at - b.at))
  const [mobileMode, setMobileMode] = useState<MobileMode>(() => asMobileMode(initial.mobile_mode))
  const [saving, setSaving] = useState(false)

  const dirty =
    JSON.stringify({ hero, beats, mobileMode }) !==
    JSON.stringify({ hero: initial.hero ?? {}, beats: [...(initial.beats ?? [])].sort((a, b) => a.at - b.at), mobileMode: asMobileMode(initial.mobile_mode) })
  useUnsavedGuard(dirty)

  const save = async () => {
    if (saving) return
    setSaving(true)
    try {
      const clean = beats
        .filter((b) => b.text.trim())
        .map((b) => {
          const at = Math.min(0.92, Math.max(0.04, Number(b.at) || 0.05))
          const until = typeof b.until === 'number' && b.until > at ? Math.min(BEATS_END, b.until) : null
          return { ...b, at, until }
        })
        .sort((a, b) => a.at - b.at)
      const experience = { ...asObject<Record<string, Json>>(listing.experience), hero, beats: clean, mobile_mode: mobileMode } as unknown as Json
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

  const timeline = useMemo(() => {
    const sorted = beats.map((beat, idx) => ({ beat, num: idx + 1 })).sort((a, b) => a.beat.at - b.beat.at)
    const plain = sorted.map((s) => s.beat)
    return sorted.map((s, j) => ({ ...s, end: beatEnd(plain, j) }))
  }, [beats])
  const endOf = (b: ScrollBeat) => timeline.find((t) => t.beat.id === b.id)?.end ?? BEATS_END

  return (
    <div className="a-editor">
      <div className="a-editor__main">
        <Sequences data={data} setMedia={setMedia} onListing={onListing} />

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
            {timeline.map(({ beat: b, num, end }) => (
              <span
                key={b.id}
                className={`a-timeline__bar a-timeline__bar--${b.side}`}
                style={{ left: `${b.at * 100}%`, width: `${Math.max(0, end - b.at) * 100}%` }}
              >
                <span className="a-timeline__mark">{num}</span>
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
                    <Field label={`Starts · ${Math.round(b.at * 100)}%`}>
                      {(id) => (
                        <input
                          id={id}
                          type="range"
                          min={0.04}
                          max={0.92}
                          step={0.01}
                          value={b.at}
                          onChange={(e) => {
                            const at = Number(e.target.value)
                            updateBeat(i, typeof b.until === 'number' && b.until < at + MIN_BEAT ? { at, until: Math.min(BEATS_END, at + MIN_BEAT) } : { at })
                          }}
                          className="a-range"
                        />
                      )}
                    </Field>
                    <Field
                      label={`Ends · ${Math.round(endOf(b) * 100)}%`}
                      hint={
                        typeof b.until === 'number' ? (
                          <button type="button" className="a-link" onClick={() => updateBeat(i, { until: null })}>
                            Reset to auto
                          </button>
                        ) : (
                          'Auto — until the next beat'
                        )
                      }
                    >
                      {(id) => (
                        <input
                          id={id}
                          type="range"
                          min={0.06}
                          max={BEATS_END}
                          step={0.01}
                          value={endOf(b)}
                          onChange={(e) => updateBeat(i, { until: Math.max(b.at + MIN_BEAT, Number(e.target.value)) })}
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
          <p className="a-muted">Shown over the first frame, before the visitor starts scrolling.</p>
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
            <Field label="On phones" hint="Used on upright phones when there is no portrait version.">
              {(id) => (
                <select id={id} className="a-input" value={mobileMode} onChange={(e) => setMobileMode(asMobileMode(e.target.value))}>
                  <option value="rotate">Rotate for landscape (recommended)</option>
                  <option value="fit">Fit with bars</option>
                  <option value="fill">Fill screen (crops sides)</option>
                </select>
              )}
            </Field>
          </div>
          <div className="a-card__actions">
            <button type="button" className="a-btn a-btn--primary a-btn--block" onClick={() => void save()} disabled={saving || !dirty}>
              {saving ? 'Saving…' : dirty ? 'Save walkthrough' : 'Saved'}
              <Kbd>{isMac ? '⌘' : 'Ctrl'} S</Kbd>
            </button>
            <a className="a-btn a-btn--ghost a-btn--block" href={listingPath(listing.slug)} target="_blank" rel="noreferrer">
              Open preview ↗
            </a>
          </div>
        </section>
      </aside>
    </div>
  )
}

// Frame sequences ------------------------------------------------------------

type VideoJob = { phase: 'reading' | 'extracting' | 'uploading'; done: number; total: number }

/** Counts enter/leave so hovering over child elements does not flicker the highlight. */
function useFileDrop(onFiles: (files: File[]) => void, enabled: boolean) {
  const [isOver, setIsOver] = useState(false)
  const depth = useRef(0)
  const hasFiles = (e: DragEvent) => Array.from(e.dataTransfer.types).includes('Files')
  const props = {
    onDragEnter: (e: DragEvent) => {
      if (!hasFiles(e)) return
      e.preventDefault()
      depth.current += 1
      if (enabled) setIsOver(true)
    },
    onDragOver: (e: DragEvent) => {
      if (!hasFiles(e)) return
      e.preventDefault()
      e.dataTransfer.dropEffect = enabled ? 'copy' : 'none'
    },
    onDragLeave: () => {
      depth.current = Math.max(0, depth.current - 1)
      if (depth.current === 0) setIsOver(false)
    },
    onDrop: (e: DragEvent) => {
      if (!hasFiles(e)) return
      e.preventDefault()
      depth.current = 0
      setIsOver(false)
      if (enabled) onFiles(Array.from(e.dataTransfer.files))
    },
  }
  return { isOver, props }
}

/** Checks the browser can make before upload; shake and brightness are measured by the processing worker. */
function footageWarnings(info: VideoInfo) {
  const warnings: string[] = []
  const shortSide = Math.min(info.width, info.height)
  if (info.duration < 6) warnings.push('This video is under 6 seconds, so the walkthrough will feel abrupt.')
  if (info.duration > 90) warnings.push('This video is over 90 seconds; a tighter 10–40 second take keeps buyers scrolling.')
  if (shortSide < 1080) warnings.push(`It was filmed at ${info.width}×${info.height}. Film in 4K for sharp frames on large screens.`)
  if (info.aspect === 'square') warnings.push('Square video is cropped on phones and desktops. Film wide for desktop or tall for phones.')
  return warnings
}

function videoLabel(job: VideoJob) {
  if (job.phase === 'reading') return 'Reading video…'
  const pct = job.total ? Math.round((job.done / job.total) * 100) : 0
  return job.phase === 'extracting' ? `Extracting frames · ${pct}%` : `Uploading · ${pct}%`
}

const SLOTS: { aspect: MediaAspect; title: string; device: string; hint: string }[] = [
  { aspect: 'landscape', title: 'Landscape version', device: 'tablets, laptops and desktops', hint: 'Filmed with the phone held sideways (16:9).' },
  { aspect: 'portrait', title: 'Portrait version', device: 'phones', hint: 'Filmed with the phone upright (9:16).' },
]

function coverage(hasLandscape: boolean, hasPortrait: boolean) {
  if (hasLandscape && hasPortrait) return 'Phones play the portrait version; tablets and larger screens play the landscape one.'
  if (hasLandscape) return 'Phones play the landscape version turned sideways (change this under “On phones”). Add a portrait version for a full-screen phone walkthrough.'
  if (hasPortrait) return 'Tablets and desktops show the portrait version as a tall panel beside the story. Add a landscape version for a full-screen desktop walkthrough.'
  return 'No walkthrough yet, so the listing uses the photo layout.'
}

function Sequences({ data, setMedia, onListing }: { data: EditorData; setMedia: Props['setMedia']; onListing: Props['onListing'] }) {
  const toast = useToast()
  const { listing, media } = data
  const sequences = media.filter((m) => m.kind === 'frame_sequence').sort((a, b) => a.sort_order - b.sort_order)
  const [job, setJob] = useState<{ aspect: MediaAspect; video: VideoJob | null; frames: { done: number; total: number } | null } | null>(null)
  const [warnings, setWarnings] = useState<{ aspect: MediaAspect; list: string[] } | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const busy = Boolean(job)

  useEffect(() => {
    const block = (e: globalThis.DragEvent) => {
      if (e.dataTransfer && Array.from(e.dataTransfer.types).includes('Files')) e.preventDefault()
    }
    window.addEventListener('dragover', block)
    window.addEventListener('drop', block)
    return () => {
      window.removeEventListener('dragover', block)
      window.removeEventListener('drop', block)
    }
  }, [])

  /** New sequences go first so they win over any older sequence with the same aspect on the public page. */
  const saveSequence = async (res: Awaited<ReturnType<typeof uploadFrameSequence>>, aspect: MediaAspect, label: string) => {
    const row = await createMedia({
      listing_id: listing.id,
      kind: 'frame_sequence',
      storage_path: res.prefix,
      public_url: res.baseUrl,
      frame_count: res.count,
      frame_pattern: res.pattern,
      aspect,
      label,
      sort_order: Math.min(0, ...sequences.map((s) => s.sort_order)) - 1,
    })
    setMedia((m) => [row, ...m])
    if (listing.experience_type !== 'immersive') onListing(await updateListing(listing.id, { experience_type: 'immersive' }))
  }

  const uploadVideo = async (file: File, slot: MediaAspect) => {
    const controller = new AbortController()
    abortRef.current = controller
    setJob({ aspect: slot, video: { phase: 'reading', done: 0, total: 0 }, frames: null })
    setWarnings(null)
    try {
      const info = await probeVideo(file)
      if (info.aspect !== 'square' && info.aspect !== slot) {
        const other = SLOTS.find((s) => s.aspect === info.aspect)!
        toast(`This video was filmed ${info.aspect === 'portrait' ? 'upright' : 'sideways'}. Upload it under “${other.title}”.`, 'error')
        return
      }
      setWarnings({ aspect: slot, list: footageWarnings(info) })
      const preset = VIDEO_PRESETS[slot]
      const frames = await extractFrames(
        file,
        { count: preset.frames, maxWidth: preset.width, quality: preset.quality },
        (done, total) => setJob({ aspect: slot, video: { phase: 'extracting', done, total }, frames: null }),
        controller.signal,
      )
      if (controller.signal.aborted) throw new DOMException('Cancelled', 'AbortError')
      const res = await uploadFrameSequence(listing.id, frames, (done, total) =>
        setJob({ aspect: slot, video: { phase: 'uploading', done, total }, frames: null }),
      )
      await saveSequence(res, slot, `${file.name} · ${slot}`)
      toast(`${slot === 'landscape' ? 'Landscape' : 'Portrait'} walkthrough ready — ${res.count} frames`)
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') toast('Video upload cancelled')
      else toast(errorMessage(err), 'error')
    } finally {
      abortRef.current = null
      setJob(null)
    }
  }

  const uploadFrames = async (files: File[], slot: MediaAspect) => {
    if (!files.length) return
    setJob({ aspect: slot, video: null, frames: { done: 0, total: files.length } })
    try {
      const res = await uploadFrameSequence(listing.id, files, (done, total) => setJob({ aspect: slot, video: null, frames: { done, total } }))
      await saveSequence(res, slot, `Uploaded ${slot} frames`)
      toast(`${res.count} frames uploaded`)
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setJob(null)
    }
  }

  const addByPath = async (slot: MediaAspect) => {
    try {
      const row = await createMedia({
        listing_id: listing.id,
        kind: 'frame_sequence',
        public_url: slot === 'portrait' ? '/media/sequence-portrait' : '/media/sequence',
        frame_count: 240,
        frame_pattern: 'frame-{###}.jpg',
        aspect: slot,
        label: `${slot} sequence`,
        sort_order: Math.min(0, ...sequences.map((s) => s.sort_order)) - 1,
      })
      setMedia((m) => [row, ...m])
    } catch (err) {
      toast(errorMessage(err), 'error')
    }
  }

  const ofAspect = (aspect: MediaAspect) => sequences.filter((s) => (s.aspect ?? 'landscape') === aspect)
  const hasLandscape = ofAspect('landscape').length > 0
  const hasPortrait = ofAspect('portrait').length > 0

  return (
    <section className="a-card">
      <div className="a-card__head">
        <div>
          <h2 className="a-card__title">Walkthrough video</h2>
          <p className="a-muted">Add one or both versions. Each screen automatically plays the version that fits it best.</p>
        </div>
      </div>

      <p className={`a-note${hasLandscape || hasPortrait ? '' : ' a-note--warn'}`}>{coverage(hasLandscape, hasPortrait)}</p>

      <div className="a-slots">
        {SLOTS.map((slot) => (
          <SequenceSlot
            key={slot.aspect}
            slot={slot}
            rows={ofAspect(slot.aspect)}
            job={job?.aspect === slot.aspect ? job : null}
            busy={busy}
            warnings={warnings?.aspect === slot.aspect ? warnings.list : []}
            onVideo={(f) => void uploadVideo(f, slot.aspect)}
            onFrames={(f) => void uploadFrames(f, slot.aspect)}
            onAddByPath={() => void addByPath(slot.aspect)}
            onCancel={() => abortRef.current?.abort()}
            setMedia={setMedia}
          />
        ))}
      </div>

      <ul className="a-filming">
        <li>Use a gimbal, or your phone's stabilised / action mode.</li>
        <li>Walk slowly at one steady pace. No stopping, no zooming.</li>
        <li>Film in 4K at 60fps, with every light on and exposure locked.</li>
        <li>One continuous take, 10–40 seconds, entrance to the best room.</li>
      </ul>

      <details className="a-details">
        <summary>Exporting frames yourself</summary>
        <p className="a-muted">For full control over quality, export frames with FFmpeg and upload them in the matching slot:</p>
        <pre className="a-code">
          {`# landscape, 240 frames, 1920px wide
ffmpeg -i walkthrough.mp4 -vf "fps=240/DURATION,scale=1920:-2" -q:v 3 frame-%03d.jpg

# portrait (phones), 240 frames, 720px wide
ffmpeg -i walkthrough-portrait.mp4 -vf "fps=240/DURATION,scale=720:-2" -q:v 4 frame-%03d.jpg`}
        </pre>
        <p className="a-muted">Replace DURATION with the clip length in seconds.</p>
      </details>
    </section>
  )
}

type SlotJob = { video: VideoJob | null; frames: { done: number; total: number } | null }

function SequenceSlot({
  slot,
  rows,
  job,
  busy,
  warnings,
  onVideo,
  onFrames,
  onAddByPath,
  onCancel,
  setMedia,
}: {
  slot: (typeof SLOTS)[number]
  rows: ListingMediaRow[]
  job: SlotJob | null
  busy: boolean
  warnings: string[]
  onVideo: (file: File) => void
  onFrames: (files: File[]) => void
  onAddByPath: () => void
  onCancel: () => void
  setMedia: Props['setMedia']
}) {
  const toast = useToast()
  const active = rows[0]
  const older = rows.slice(1)
  const onDropped = (files: File[]) => {
    if (busy || !files.length) return
    const video = files.find((f) => f.type.startsWith('video/') || /\.(mp4|webm|mov|m4v)$/i.test(f.name))
    if (video) return onVideo(video)
    const images = files.filter((f) => f.type.startsWith('image/'))
    if (images.length) return onFrames(images)
    toast('Drop a video or image frames', 'error')
  }
  const drop = useFileDrop(onDropped, !busy)
  const first = active?.public_url && active.frame_pattern ? joinUrl(active.public_url, expandFramePattern(active.frame_pattern, 1)) : ''
  const progress = job?.video ? job.video : job?.frames ? { ...job.frames, phase: 'uploading' as const } : null

  const removeOlder = async () => {
    try {
      for (const row of older) await deleteMedia(row)
      setMedia((m) => m.filter((x) => !older.some((o) => o.id === x.id)))
      toast('Older uploads removed')
    } catch (err) {
      toast(errorMessage(err), 'error')
    }
  }

  return (
    <div className={`a-slot a-slot--${slot.aspect} a-dropzone${drop.isOver ? ' is-over' : ''}${active ? ' has-video' : ''}`} {...drop.props}>
      <div className="a-slot__head">
        <div>
          <h3 className="a-card__subtitle">{slot.title}</h3>
          <p className="a-slot__device">Plays on {slot.device}</p>
        </div>
        <span className={`a-slot__status${active ? ' is-on' : ''}`}>{active ? 'Added' : 'Optional'}</span>
      </div>

      <div className="a-slot__preview">
        {first ? <img src={first} alt={`${slot.title} first frame`} loading="lazy" /> : <span className="a-slot__frame" aria-hidden />}
      </div>

      {active ? (
        <p className="a-muted a-slot__meta">
          {active.frame_count} frames · {active.label ?? 'Walkthrough'}
        </p>
      ) : (
        <p className="a-muted a-slot__meta">{slot.hint} Drop the video here or choose it below.</p>
      )}

      {warnings.length > 0 && (
        <div className="a-note a-note--warn">
          <strong>Before you publish:</strong>
          <ul>
            {warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="a-inline-form">
        <label className={`a-btn ${active ? 'a-btn--ghost' : 'a-btn--primary'} a-file${busy ? ' is-disabled' : ''}`}>
          {job?.video ? videoLabel(job.video) : job?.frames ? `Uploading ${job.frames.done}/${job.frames.total}` : active ? 'Replace video' : 'Choose video'}
          <input
            type="file"
            accept="video/mp4,video/webm,video/quicktime,.mp4,.webm,.mov,.m4v"
            disabled={busy}
            onChange={(e) => {
              const file = e.target.files?.[0]
              e.target.value = ''
              if (file) onVideo(file)
            }}
          />
        </label>
        {job?.video && (
          <button type="button" className="a-link" onClick={onCancel}>
            Cancel
          </button>
        )}
      </div>
      {progress && progress.total > 0 && (
        <div className="a-progress" aria-hidden>
          <span style={{ transform: `scaleX(${progress.done / progress.total})` }} />
        </div>
      )}

      <details className="a-details">
        <summary>Advanced</summary>
        <div className="a-inline-form">
          <label className={`a-btn a-btn--ghost a-btn--sm a-file${busy ? ' is-disabled' : ''}`}>
            Upload numbered frames
            <input
              type="file"
              multiple
              accept="image/jpeg,image/png,image/webp"
              disabled={busy}
              onChange={(e) => {
                onFrames(Array.from(e.target.files ?? []))
                e.target.value = ''
              }}
            />
          </label>
          <button type="button" className="a-link" onClick={onAddByPath}>
            Add by path
          </button>
        </div>
        {active && <SequenceRow key={active.id} row={active} setMedia={setMedia} />}
        {older.length > 0 && (
          <p className="a-muted">
            {older.length} older upload{older.length === 1 ? '' : 's'} not in use.{' '}
            <ConfirmButton onConfirm={() => void removeOlder()} className="a-link a-link--danger" confirmLabel="Delete them?">
              Remove
            </ConfirmButton>
          </p>
        )}
      </details>
    </div>
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

import { useState, type DragEvent } from 'react'
import type { ListingMediaRow, ListingRow } from '../types/database'
import { createMedia, deleteMedia, reorderRows, updateListing, updateMedia, uploadImage } from './api'
import type { EditorData } from './ListingEditor'
import { ConfirmButton, EmptyState, errorMessage, useToast } from './ui'

type Props = {
  data: EditorData
  setMedia: (fn: (m: ListingMediaRow[]) => ListingMediaRow[]) => void
  onListing: (l: ListingRow) => void
}

export function MediaTab({ data, setMedia, onListing }: Props) {
  const toast = useToast()
  const { listing, media } = data
  const images = media.filter((m) => m.kind === 'gallery' || m.kind === 'cover')
  const [queue, setQueue] = useState<{ name: string; done: boolean }[]>([])
  const [dragOver, setDragOver] = useState(false)
  const [urlDraft, setUrlDraft] = useState('')

  const upload = async (files: File[]) => {
    const list = files.filter((f) => f.type.startsWith('image/'))
    if (!list.length) return toast('Choose JPG, PNG, WebP or AVIF images', 'error')
    setQueue(list.map((f) => ({ name: f.name, done: false })))
    let order = images.length ? Math.max(...images.map((m) => m.sort_order)) + 1 : 0
    let ok = 0
    for (const [i, file] of list.entries()) {
      try {
        const { path, url } = await uploadImage(file, `${listing.id}/gallery`)
        const row = await createMedia({
          listing_id: listing.id,
          kind: 'gallery',
          storage_path: path,
          public_url: url,
          label: file.name.replace(/\.[^.]+$/, '').replace(/[-_]+/g, ' '),
          aspect: 'landscape',
          sort_order: order++,
        })
        setMedia((m) => [...m, row])
        ok += 1
      } catch (err) {
        toast(`${file.name}: ${errorMessage(err)}`, 'error')
      }
      setQueue((q) => q.map((x, j) => (j === i ? { ...x, done: true } : x)))
    }
    if (ok) toast(`${ok} image${ok === 1 ? '' : 's'} uploaded`)
    window.setTimeout(() => setQueue([]), 1200)
  }

  const addByUrl = async () => {
    const url = urlDraft.trim()
    if (!url) return
    try {
      const row = await createMedia({
        listing_id: listing.id,
        kind: 'gallery',
        public_url: url,
        aspect: 'landscape',
        sort_order: images.length,
      })
      setMedia((m) => [...m, row])
      setUrlDraft('')
      toast('Image added')
    } catch (err) {
      toast(errorMessage(err), 'error')
    }
  }

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    void upload(Array.from(e.dataTransfer.files))
  }

  const move = async (index: number, delta: number) => {
    const next = [...images]
    const target = index + delta
    if (target < 0 || target >= next.length) return
    ;[next[index], next[target]] = [next[target], next[index]]
    const ids = next.map((m) => m.id)
    setMedia((m) =>
      m.map((row) => (ids.includes(row.id) ? { ...row, sort_order: ids.indexOf(row.id) } : row)).sort((a, b) => a.sort_order - b.sort_order),
    )
    try {
      await reorderRows('listing_media', ids)
    } catch (err) {
      toast(errorMessage(err), 'error')
    }
  }

  const setCover = async (url: string) => {
    try {
      onListing(await updateListing(listing.id, { cover_image_url: url }))
      toast('Cover updated')
    } catch (err) {
      toast(errorMessage(err), 'error')
    }
  }

  const saveLabel = async (row: ListingMediaRow, label: string) => {
    if ((row.label ?? '') === label) return
    try {
      const saved = await updateMedia(row.id, { label: label || null })
      setMedia((m) => m.map((x) => (x.id === saved.id ? saved : x)))
    } catch (err) {
      toast(errorMessage(err), 'error')
    }
  }

  const remove = async (row: ListingMediaRow) => {
    try {
      await deleteMedia(row)
      setMedia((m) => m.filter((x) => x.id !== row.id))
      toast('Image removed')
    } catch (err) {
      toast(errorMessage(err), 'error')
    }
  }

  return (
    <div className="a-stack">
      <section className="a-card">
        <div className="a-card__head">
          <div>
            <h2 className="a-card__title">Gallery images</h2>
            <p className="a-muted">Stored in the public <code>listing-images</code> bucket. Order here is the order on the page.</p>
          </div>
        </div>

        <label
          className={`a-drop ${dragOver ? 'is-over' : ''}`}
          onDragOver={(e) => {
            e.preventDefault()
            setDragOver(true)
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={onDrop}
        >
          <input
            type="file"
            multiple
            accept="image/jpeg,image/png,image/webp,image/avif"
            onChange={(e) => {
              void upload(Array.from(e.target.files ?? []))
              e.target.value = ''
            }}
          />
          <strong>Drop images here, or click to choose</strong>
          <span>JPG, PNG, WebP or AVIF up to 20 MB each. Landscape 2400px wide works best.</span>
        </label>

        {queue.length > 0 && (
          <ul className="a-queue">
            {queue.map((q, i) => (
              <li key={i} className={q.done ? 'is-done' : ''}>
                <span>{q.name}</span>
                <span>{q.done ? 'Done' : 'Uploading…'}</span>
              </li>
            ))}
          </ul>
        )}

        <div className="a-inline-form">
          <input
            className="a-input a-input--mono"
            placeholder="…or add an existing image URL (e.g. /frames/frame-01.jpg)"
            value={urlDraft}
            onChange={(e) => setUrlDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                void addByUrl()
              }
            }}
          />
          <button type="button" className="a-btn a-btn--ghost" onClick={() => void addByUrl()} disabled={!urlDraft.trim()}>
            Add
          </button>
        </div>
      </section>

      {images.length === 0 ? (
        <EmptyState title="No images yet">
          <p>Upload a set above. The first one can become the cover.</p>
        </EmptyState>
      ) : (
        <ul className="a-media-grid">
          {images.map((m, i) => {
            const isCover = listing.cover_image_url === m.public_url
            return (
              <li key={m.id} className={`a-media ${isCover ? 'is-cover' : ''}`}>
                <div className="a-media__img">
                  <img src={m.public_url ?? ''} alt={m.label ?? ''} loading="lazy" />
                  <span className="a-media__index">{String(i + 1).padStart(2, '0')}</span>
                  {isCover && <span className="a-media__flag">Cover</span>}
                </div>
                <input
                  className="a-input a-input--sm"
                  defaultValue={m.label ?? ''}
                  placeholder="Alt text / caption"
                  aria-label="Image label"
                  onBlur={(e) => void saveLabel(m, e.target.value.trim())}
                />
                <div className="a-media__actions">
                  <button type="button" className="a-icon-btn" onClick={() => void move(i, -1)} disabled={i === 0} aria-label="Move earlier">
                    ←
                  </button>
                  <button
                    type="button"
                    className="a-icon-btn"
                    onClick={() => void move(i, 1)}
                    disabled={i === images.length - 1}
                    aria-label="Move later"
                  >
                    →
                  </button>
                  <button type="button" className="a-link" onClick={() => void setCover(m.public_url!)} disabled={isCover}>
                    {isCover ? 'Is cover' : 'Set cover'}
                  </button>
                  <ConfirmButton onConfirm={() => void remove(m)} className="a-link a-link--danger" confirmLabel="Remove?">
                    Remove
                  </ConfirmButton>
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

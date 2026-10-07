import { useState, type DragEvent } from 'react'
import { floorPlanFromFile, saveFloorPlans, suggestedLabel, useFloorPlans, type FloorPlan } from '../lib/floorPlans'
import { ConfirmButton, errorMessage, useToast } from './ui'

export function FloorPlansCard({ listingId }: { listingId: string }) {
  const toast = useToast()
  const plans = useFloorPlans(listingId)
  const [busy, setBusy] = useState(false)
  const [dragOver, setDragOver] = useState(false)

  const commit = (next: FloorPlan[]) => {
    try {
      saveFloorPlans(listingId, next)
      return true
    } catch {
      toast('This browser is out of space for more plans. Remove one, or use smaller images.', 'error')
      return false
    }
  }

  const upload = async (files: File[]) => {
    const list = files.filter((f) => f.type.startsWith('image/'))
    if (!list.length) return toast('Choose JPG, PNG or WebP images of the plan', 'error')
    setBusy(true)
    const added: FloorPlan[] = []
    for (const file of list) {
      try {
        added.push(await floorPlanFromFile(file, suggestedLabel(plans.length + added.length)))
      } catch (err) {
        toast(`${file.name}: ${errorMessage(err)}`, 'error')
      }
    }
    setBusy(false)
    if (added.length && commit([...plans, ...added])) toast(`${added.length} floor plan${added.length === 1 ? '' : 's'} added`)
  }

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    void upload(Array.from(e.dataTransfer.files))
  }

  const move = (index: number, delta: number) => {
    const next = [...plans]
    const target = index + delta
    if (target < 0 || target >= next.length) return
    ;[next[index], next[target]] = [next[target], next[index]]
    commit(next)
  }

  return (
    <section className="a-card">
      <div className="a-card__head">
        <div>
          <h2 className="a-card__title">Floor plans</h2>
          <p className="a-muted">
            A Floor plan section appears on the page once a plan is uploaded. With more than one, buyers switch between them using the
            labels you give here.
          </p>
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
          accept="image/jpeg,image/png,image/webp"
          disabled={busy}
          onChange={(e) => {
            void upload(Array.from(e.target.files ?? []))
            e.target.value = ''
          }}
        />
        <strong>{busy ? 'Preparing plans…' : 'Drop floor plans here, or click to choose'}</strong>
        <span>One image per level. JPG, PNG or WebP. Plans on a white background read best.</span>
      </label>

      {plans.length > 0 && (
        <ul className="a-plans">
          {plans.map((p, i) => (
            <li key={p.id} className="a-plan">
              <div className="a-plan__img">
                <img src={p.src} alt={p.label} />
              </div>
              <input
                className="a-input a-input--sm"
                defaultValue={p.label}
                placeholder={suggestedLabel(i)}
                aria-label="Floor plan label"
                onBlur={(e) => {
                  const label = e.target.value.trim()
                  if (label !== p.label) commit(plans.map((x) => (x.id === p.id ? { ...x, label } : x)))
                }}
              />
              <div className="a-media__actions">
                <button type="button" className="a-icon-btn" onClick={() => move(i, -1)} disabled={i === 0} aria-label="Move earlier">
                  ←
                </button>
                <button type="button" className="a-icon-btn" onClick={() => move(i, 1)} disabled={i === plans.length - 1} aria-label="Move later">
                  →
                </button>
                <ConfirmButton onConfirm={() => commit(plans.filter((x) => x.id !== p.id))} className="a-link a-link--danger" confirmLabel="Remove?">
                  Remove
                </ConfirmButton>
              </div>
            </li>
          ))}
        </ul>
      )}
      <p className="a-note">Prototype: floor plans are kept in this browser only, so they show on your preview but not on other devices yet.</p>
    </section>
  )
}

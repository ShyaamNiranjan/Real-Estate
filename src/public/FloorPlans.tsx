import { useRef, useState } from 'react'
import { suggestedLabel, useFloorPlans } from '../lib/floorPlans'
import type { ListingRow } from '../types/database'
import { useReveal } from './useReveal'

export function FloorPlans({ listing }: { listing: ListingRow }) {
  const plans = useFloorPlans(listing.id)
  const [active, setActive] = useState(0)
  const dialogRef = useRef<HTMLDialogElement>(null)
  const ref = useReveal<HTMLDivElement>()

  if (!plans.length) return null
  const index = Math.min(active, plans.length - 1)
  const plan = plans[index]
  const label = (i: number) => plans[i].label || suggestedLabel(i)

  const facts: { label: string; value: string }[] = []
  if (listing.area_sqft) facts.push({ label: 'Total area', value: `${listing.area_sqft.toLocaleString('en-US')} sq ft` })
  if (listing.bedrooms) facts.push({ label: 'Bedrooms', value: String(listing.bedrooms) })
  if (listing.bathrooms) facts.push({ label: 'Bathrooms', value: String(listing.bathrooms) })
  if (plans.length > 1) facts.push({ label: 'Levels', value: String(plans.length) })

  return (
    <section className="sec sec--plans tone-light" aria-labelledby="plans-title">
      <div className="sec__inner reveal" ref={ref}>
        <div className="plans">
          <div className="plans__aside">
            <p className="eyebrow">Layout</p>
            <h2 id="plans-title" className="sec__title">
              {plans.length > 1 ? 'Floor plans' : 'Floor plan'}
            </h2>
            {plans.length > 1 && (
              <div className="plans__tabs" role="tablist" aria-label="Levels">
                {plans.map((p, i) => (
                  <button
                    key={p.id}
                    type="button"
                    role="tab"
                    aria-selected={i === index}
                    className={`plans__tab ${i === index ? 'is-on' : ''}`}
                    onClick={() => setActive(i)}
                  >
                    {label(i)}
                  </button>
                ))}
              </div>
            )}
            {facts.length > 0 && (
              <dl className="plans__facts">
                {facts.map((f) => (
                  <div key={f.label}>
                    <dt>{f.label}</dt>
                    <dd>{f.value}</dd>
                  </div>
                ))}
              </dl>
            )}
          </div>

          <figure className="plans__figure" role="tabpanel">
            <button type="button" className="plans__zoom" onClick={() => dialogRef.current?.showModal()} aria-label={`Enlarge ${label(index)}`}>
              <img key={plan.id} src={plan.src} alt={`${label(index)} floor plan`} width={plan.width} height={plan.height} decoding="async" />
            </button>
            <figcaption>
              <span>{label(index)}</span>
              <span>Tap to enlarge · For guidance only, not to scale</span>
            </figcaption>
          </figure>
        </div>
      </div>

      <dialog ref={dialogRef} className="plans__dialog" onClick={(e) => e.target === e.currentTarget && dialogRef.current?.close()}>
        <div className="plans__dialog-scroll">
          <img src={plan.src} alt={`${label(index)} floor plan`} />
        </div>
        <button type="button" className="lightbox__close" onClick={() => dialogRef.current?.close()}>
          Close
        </button>
      </dialog>
    </section>
  )
}

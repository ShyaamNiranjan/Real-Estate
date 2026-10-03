import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { PLANS, planName, setProto, useProto } from '../lib/prototype'
import { useDocumentTitle } from '../lib/site'
import { useToast } from './ui'

/** Brand and website setup unlock only after subscribing. */
export function PaidOnly({ feature, body, children }: { feature: string; body: string; children: ReactNode }) {
  const { plan } = useProto()
  if (plan !== 'free') return <>{children}</>
  return (
    <div className="a-page">
      <div className="a-locked">
        <p className="a-eyebrow">{feature}</p>
        <h1 className="a-title">Make it yours when you subscribe.</h1>
        <p className="a-muted">{body}</p>
        <p className="a-muted">Your free listing carries over, so nothing you have built is lost.</p>
        <Link to="/studio/plan" className="a-btn a-btn--primary">
          See plans
        </Link>
      </div>
    </div>
  )
}

export function PlanPage() {
  useDocumentTitle('Plan')
  const { plan } = useProto()
  const toast = useToast()

  return (
    <div className="a-page">
      <header className="a-page__head">
        <div>
          <p className="a-eyebrow">Billing</p>
          <h1 className="a-title">Plan</h1>
          <p className="a-muted">
            You are on <strong>{planName(plan)}</strong>. Prices are placeholders until pricing is locked.
          </p>
        </div>
      </header>

      <div className="a-plans">
        {PLANS.map((p) => {
          const current = plan === p.key
          return (
            <section key={p.key} className={`a-card a-plancard ${current ? 'is-current' : ''} ${p.key === 'team' ? 'is-featured' : ''}`}>
              {p.key === 'team' && <span className="a-plancard__tag">Most teams</span>}
              <h2 className="a-plancard__name">{p.name}</h2>
              <p className="a-plancard__price">
                {p.price}
                {p.price !== 'Custom' && <small>/month</small>}
              </p>
              <p className="a-muted">{p.blurb}</p>
              <ul className="a-plancard__list">
                <li>
                  {p.seats === 1 ? '1 user' : `Up to ${p.seats} users`} · {p.listings}
                </li>
                {p.features.map((f) => (
                  <li key={f}>{f}</li>
                ))}
              </ul>
              <button
                type="button"
                className={`a-btn ${current ? 'a-btn--ghost' : 'a-btn--primary'} a-btn--block`}
                disabled={current}
                onClick={() => {
                  setProto({ plan: p.key })
                  toast(`Now on ${p.name} (prototype — no payment taken)`)
                }}
              >
                {current ? 'Current plan' : plan === 'free' ? `Subscribe to ${p.name}` : `Switch to ${p.name}`}
              </button>
            </section>
          )
        })}
      </div>

      {plan === 'free' && (
        <p className="a-note">
          You are on the free preview: one private listing that only you can see. Subscribing unlocks your brand, your website and
          publishing.
        </p>
      )}
    </div>
  )
}

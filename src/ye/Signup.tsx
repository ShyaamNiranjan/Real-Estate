import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { COUNTRIES, PLANS, resetProto, type Plan } from '../lib/prototype'
import { FrameLoop } from '../public/FrameLoop'
import { YeMark } from './chrome'
import './ye.css'

type Step = 'account' | 'plan' | 'pay' | 'done'
type PaidPlan = Exclude<Plan, 'free'>

const PORTRAIT = { baseUrl: '/media/sequence-portrait-lite', pattern: 'frame-{###}.jpg', count: 120 }

export function Signup() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const free = params.get('start') === 'free'
  const initialPlan = (PLANS.find((p) => p.key === params.get('plan'))?.key ?? 'agent') as PaidPlan
  const [step, setStep] = useState<Step>('account')
  const [plan, setPlan] = useState<PaidPlan>(initialPlan)
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [country, setCountry] = useState('US')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    document.title = free ? 'Try Scrollwalk free' : 'Get started · Scrollwalk'
  }, [free])

  const steps: Step[] = free ? ['account', 'done'] : ['account', 'plan', 'pay', 'done']
  const index = steps.indexOf(step)
  const chosen = PLANS.find((p) => p.key === plan)!

  const finish = () => {
    resetProto({ plan: free ? 'free' : plan, country, ownerName: name.trim() })
    setStep('done')
  }

  const submitAccount = (e: FormEvent) => {
    e.preventDefault()
    if (!name.trim()) return setError('Add your name')
    if (!/^\S+@\S+\.\S+$/.test(email.trim())) return setError('Add a valid email')
    setError(null)
    if (free) finish()
    else setStep('plan')
  }

  return (
    <div className="ye ye-signup">
      <div className="ye-signup__panel">
        <Link to="/" className="ye-signup__brand" aria-label="Scrollwalk home">
          <YeMark />
        </Link>

        {step !== 'done' && (
          <ol className="ye-progress" aria-label="Progress">
            {steps.slice(0, -1).map((s, i) => (
              <li key={s} className={i < index ? 'is-done' : i === index ? 'is-on' : ''}>
                {s === 'account' ? 'Account' : s === 'plan' ? 'Plan' : 'Payment'}
              </li>
            ))}
          </ol>
        )}

        {step === 'account' && (
          <form className="ye-form" onSubmit={submitAccount}>
            <p className="ye-eyebrow">{free ? 'Free preview' : `${chosen.name} plan`}</p>
            <h1 className="ye-signup__title">{free ? 'Build your first listing free.' : 'Create your workspace.'}</h1>
            <p className="ye-signup__lede">
              {free
                ? 'One listing with a walkthrough, on your own home. Only you can see it until you subscribe.'
                : 'Your agency site and Studio, ready in a minute. You can change plans any time.'}
            </p>
            <label className="ye-field">
              <span>Your name</span>
              <input value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" autoFocus />
            </label>
            <label className="ye-field">
              <span>Work email</span>
              <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
            </label>
            <label className="ye-field">
              <span>Password</span>
              <input type="password" autoComplete="new-password" placeholder="Not stored in the prototype" />
            </label>
            <label className="ye-field">
              <span>Where do you sell?</span>
              <select value={country} onChange={(e) => setCountry(e.target.value)}>
                {COUNTRIES.map((c) => (
                  <option key={c.code} value={c.code}>
                    {c.name}
                  </option>
                ))}
              </select>
              <small>Sets your currency, units and the licence fields your market expects.</small>
            </label>
            {error && <p className="ye-form__error">{error}</p>}
            <button type="submit" className="ye-btn ye-btn--primary ye-btn--block">
              {free ? 'Create free account' : 'Continue'}
            </button>
            <p className="ye-signup__switch">
              {free ? (
                <>
                  Ready to publish now? <Link to="/signup?plan=agent">Choose a plan</Link>
                </>
              ) : (
                <>
                  Want to try first? <Link to="/signup?start=free">Build one listing free</Link>
                </>
              )}
            </p>
          </form>
        )}

        {step === 'plan' && (
          <div className="ye-form">
            <p className="ye-eyebrow">Plan</p>
            <h1 className="ye-signup__title">Choose your plan.</h1>
            <p className="ye-signup__lede">Prices are placeholders while pricing is finalised.</p>
            <div className="ye-planpick" role="radiogroup" aria-label="Plan">
              {PLANS.map((p) => (
                <button
                  key={p.key}
                  type="button"
                  role="radio"
                  aria-checked={plan === p.key}
                  className={`ye-planpick__opt ${plan === p.key ? 'is-on' : ''}`}
                  onClick={() => setPlan(p.key)}
                >
                  <span>
                    <strong>{p.name}</strong>
                    <small>
                      {p.seats === 1 ? '1 user' : `Up to ${p.seats} users`} · {p.listings}
                    </small>
                  </span>
                  <em>
                    {p.price}
                    {p.price !== 'Custom' && '/mo'}
                  </em>
                </button>
              ))}
            </div>
            <button type="button" className="ye-btn ye-btn--primary ye-btn--block" onClick={() => setStep('pay')}>
              Continue to payment
            </button>
            <button type="button" className="ye-signup__back" onClick={() => setStep('account')}>
              ← Back
            </button>
          </div>
        )}

        {step === 'pay' && (
          <div className="ye-form">
            <p className="ye-eyebrow">Payment</p>
            <h1 className="ye-signup__title">Start your subscription.</h1>
            <div className="ye-summary">
              <span>{chosen.name} plan</span>
              <strong>
                {chosen.price}
                {chosen.price !== 'Custom' && '/month'}
              </strong>
            </div>
            <div className="ye-mockpay" aria-label="Payment form placeholder">
              <span>Card number</span>
              <div>•••• •••• •••• 4242</div>
              <span>Expiry · CVC</span>
              <div>12 / 29 · •••</div>
            </div>
            <p className="ye-signup__note">Prototype: no payment is taken. The payment provider is still to be chosen.</p>
            <button type="button" className="ye-btn ye-btn--primary ye-btn--block" onClick={finish}>
              Start subscription
            </button>
            <button type="button" className="ye-signup__back" onClick={() => setStep('plan')}>
              ← Back
            </button>
          </div>
        )}

        {step === 'done' && (
          <div className="ye-form">
            <span className="ye-done__badge" aria-hidden>
              ✓
            </span>
            <h1 className="ye-signup__title">{free ? `You're in, ${name.split(' ')[0]}.` : `Welcome to Scrollwalk, ${name.split(' ')[0]}.`}</h1>
            <p className="ye-signup__lede">
              {free
                ? 'Next: create your listing and upload a walkthrough video. It stays private until you subscribe.'
                : 'Your workspace is ready. A short setup guide will walk you through your details, your first property and publishing.'}
            </p>
            <button
              type="button"
              className="ye-btn ye-btn--primary ye-btn--block"
              onClick={() => navigate(free ? '/studio/listings/new' : '/studio')}
            >
              {free ? 'Create my listing' : 'Open my Studio'}
            </button>
            <p className="ye-signup__note">Prototype: Studio uses the existing demo sign-in.</p>
          </div>
        )}
      </div>

      <aside className="ye-signup__art" aria-hidden>
        <div className="ye-signup__phone">
          <FrameLoop source={PORTRAIT} poster="/media/sequence-portrait-lite/frame-001.jpg" />
        </div>
        <blockquote>
          “Buyers walked the whole house before they called. The viewing was just to confirm.”
          <cite>What we want every agent to say</cite>
        </blockquote>
      </aside>
    </div>
  )
}

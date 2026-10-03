import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../lib/auth'
import { markDone, seatLimit, setProto, useProto } from '../lib/prototype'
import { useDocumentTitle } from '../lib/site'
import { Field, useToast } from './ui'

export function TeamPage() {
  useDocumentTitle('Team')
  const proto = useProto()
  const { profile } = useAuth()
  const toast = useToast()
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const limit = seatLimit(proto.plan)
  const teamPlan = proto.plan === 'team' || proto.plan === 'brokerage'
  const used = 1 + proto.team.length
  const full = used >= limit

  const invite = (e: FormEvent) => {
    e.preventDefault()
    if (!name.trim() || !/^\S+@\S+\.\S+$/.test(email.trim())) return toast('Add a name and a valid email', 'error')
    if (full) return toast('Every seat on this plan is taken', 'error')
    setProto({ team: [...proto.team, { name: name.trim(), email: email.trim(), role: 'Agent' }] })
    markDone('team')
    setName('')
    setEmail('')
    toast(`Invitation sent to ${email.trim()} (prototype)`)
  }

  if (!teamPlan)
    return (
      <div className="a-page">
        <div className="a-locked">
          <p className="a-eyebrow">Team</p>
          <h1 className="a-title">Bring your team in.</h1>
          <p className="a-muted">Add agents who publish their own listings under your brand. Available on the Team and Brokerage plans.</p>
          <Link to="/studio/plan" className="a-btn a-btn--primary">
            See plans
          </Link>
        </div>
      </div>
    )

  return (
    <div className="a-page a-page--narrow">
      <header className="a-page__head">
        <div>
          <p className="a-eyebrow">Workspace</p>
          <h1 className="a-title">Team</h1>
          <p className="a-muted">
            {used} of {limit} seats used
          </p>
        </div>
      </header>

      <section className="a-card">
        <h2 className="a-card__title">Members</h2>
        <ul className="a-members">
          <li>
            <span className="a-members__avatar">{(proto.ownerName || profile?.email || 'Y').charAt(0).toUpperCase()}</span>
            <span>
              <strong>{proto.ownerName || profile?.full_name || 'You'}</strong>
              <small>{profile?.email}</small>
            </span>
            <span className="a-members__role">Owner</span>
          </li>
          {proto.team.map((m) => (
            <li key={m.email}>
              <span className="a-members__avatar">{m.name.charAt(0).toUpperCase()}</span>
              <span>
                <strong>{m.name}</strong>
                <small>{m.email} · invited</small>
              </span>
              <span className="a-members__role">{m.role}</span>
              <button
                type="button"
                className="a-link"
                onClick={() => setProto({ team: proto.team.filter((t) => t.email !== m.email) })}
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      </section>

      <form className="a-card a-form" onSubmit={invite}>
        <h2 className="a-card__title">Invite an agent</h2>
        <div className="a-grid">
          <Field label="Name">{(id) => <input id={id} className="a-input" value={name} onChange={(e) => setName(e.target.value)} />}</Field>
          <Field label="Email">
            {(id) => <input id={id} className="a-input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />}
          </Field>
        </div>
        <p className="a-muted">Agents can create and publish listings. Only the owner manages the brand, website and plan.</p>
        <div className="a-form__actions">
          <button type="submit" className="a-btn a-btn--primary" disabled={full}>
            {full ? 'All seats taken' : 'Send invitation'}
          </button>
        </div>
      </form>
    </div>
  )
}

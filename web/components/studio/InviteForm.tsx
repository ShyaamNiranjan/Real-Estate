'use client'

import { useEffect, useState, type FormEvent } from 'react'
import { isEmail } from '@/components/forms'
import { api } from '@/lib/api/client'
import { asApiError, unwrap, type ApiError } from '@/lib/api/errors'
import type { components } from '@/lib/api/schema'
import { useStudio } from '@/lib/studio'
import { ErrorAlert, Field } from './ui'

type Role = components['schemas']['RoleOut']
type Invitation = components['schemas']['InvitationOut']

/** Everyone invited needs a role; a new team has none, so offer the suggested ones. */
function FirstRole({ onCreated }: { onCreated: (r: Role) => void }) {
  const { noteError } = useStudio()
  const [suggestions, setSuggestions] = useState<components['schemas']['RoleSuggestion'][] | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    let cancelled = false
    unwrap(api.GET('/api/v1/team/permissions'))
      .then((c) => !cancelled && setSuggestions(c.suggestions))
      .catch((err) => !cancelled && setError(asApiError(err)))
    return () => {
      cancelled = true
    }
  }, [])
  return (
    <div>
      <p className="a-muted">Everyone you invite gets a role. Add one to start; you can edit it on the Team page.</p>
      <div className="a-chips">
        {(suggestions ?? []).map((s) => (
          <button
            key={s.name}
            type="button"
            className="a-chip"
            disabled={busy}
            onClick={async () => {
              setBusy(true)
              setError(null)
              try {
                onCreated(await unwrap(api.POST('/api/v1/team/roles', { body: s })))
              } catch (err) {
                setError(noteError(err))
              } finally {
                setBusy(false)
              }
            }}
          >
            Add the {s.name} role
          </button>
        ))}
      </div>
      <ErrorAlert error={error} />
    </div>
  )
}

/** `POST /team/invitations {email, role_id}`. Loads roles itself unless the Team page passes them. */
export function InviteForm({ roles: given, onSent, disabled }: { roles?: Role[]; onSent?: (inv: Invitation) => void; disabled?: boolean }) {
  const { noteError, toast } = useStudio()
  const [loaded, setLoaded] = useState<Role[] | null>(null)
  const [loadError, setLoadError] = useState<ApiError | null>(null)
  const roles = given ?? loaded
  const [email, setEmail] = useState('')
  const [roleId, setRoleId] = useState('')
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [failure, setFailure] = useState<ApiError | null>(null)
  const [busy, setBusy] = useState(false)
  const role = roleId || roles?.[0]?.id || ''

  useEffect(() => {
    if (given) return
    let cancelled = false
    unwrap(api.GET('/api/v1/team/roles'))
      .then((r) => !cancelled && setLoaded(r))
      .catch((err) => !cancelled && setLoadError(asApiError(err)))
    return () => {
      cancelled = true
    }
  }, [given])

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (busy) return
    if (!isEmail(email)) return setErrors({ email: 'Enter a valid email address.' })
    setBusy(true)
    setErrors({})
    setFailure(null)
    try {
      const inv = await unwrap(api.POST('/api/v1/team/invitations', { body: { email: email.trim(), role_id: role } }))
      toast(`Invitation sent to ${inv.email}`)
      setEmail('')
      onSent?.(inv)
    } catch (err) {
      const apiError = noteError(err)
      setErrors(apiError.fields)
      if (!apiError.fields.email && !apiError.fields.role_id) setFailure(apiError)
    } finally {
      setBusy(false)
    }
  }

  if (loadError) return <ErrorAlert error={loadError} />
  if (roles && !roles.length)
    return given ? (
      <p className="a-muted">Create a role first (under Roles below), then invite people to it.</p>
    ) : (
      <FirstRole onCreated={(r) => setLoaded([r])} />
    )

  // A <div> rather than a nested <form>: the setup guide wraps this in its own form.
  return (
    <div
      className="a-guide__grid"
      onKeyDown={(e) => {
        if (e.key === 'Enter' && (e.target as HTMLElement).tagName === 'INPUT') void submit(e as unknown as FormEvent)
      }}
    >
      <Field label="Email" error={errors.email}>
        {(a) => (
          <input
            {...a}
            className="a-input"
            type="email"
            inputMode="email"
            autoComplete="off"
            spellCheck={false}
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        )}
      </Field>
      <Field label="Role" error={errors.role_id}>
        {(a) => (
          <select {...a} className="a-input" value={role} onChange={(e) => setRoleId(e.target.value)} disabled={!roles}>
            {(roles ?? []).map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
              </option>
            ))}
          </select>
        )}
      </Field>
      <div className="a-field--wide">
        <ErrorAlert error={failure} />
        <button type="button" className="a-btn a-btn--ghost" disabled={busy || disabled || !roles?.length} onClick={(e) => void submit(e as unknown as FormEvent)}>
          {busy ? 'Sending…' : 'Send invitation'}
        </button>
      </div>
    </div>
  )
}

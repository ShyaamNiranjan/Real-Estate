'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { InviteForm } from '@/components/studio/InviteForm'
import { CountUp, Dialog, ErrorAlert, Field, LoadFailed, PageHead, PageSkeleton } from '@/components/studio/ui'
import { api } from '@/lib/api/client'
import { asApiError, unwrap, type ApiError } from '@/lib/api/errors'
import type { components } from '@/lib/api/schema'
import { useSession } from '@/lib/session'
import { initials, useWorkspace } from '@/lib/studio'

type Member = components['schemas']['MemberOut']
type Role = components['schemas']['RoleOut']
type Catalogue = components['schemas']['Catalogue']
type Invitations = components['schemas']['InvitationList']

type Data = { members: Member[]; roles: Role[] | null; catalogue: Catalogue | null; invitations: Invitations | null }

const dateFmt = (iso: string) => new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })

export function Team() {
  const { teamPlan, can, workspace } = useWorkspace()
  const manageMembers = can('team.manage_members')
  const manageRoles = can('team.manage_roles')
  const [data, setData] = useState<Data | null>(null)
  const [error, setError] = useState<ApiError | null>(null)

  const fetchAll = useCallback(async (): Promise<Data> => {
    const [members, roles, catalogue, invitations] = await Promise.all([
      unwrap(api.GET('/api/v1/team/members')),
      manageMembers || manageRoles ? unwrap(api.GET('/api/v1/team/roles')) : null,
      manageRoles ? unwrap(api.GET('/api/v1/team/permissions')) : null,
      manageMembers ? unwrap(api.GET('/api/v1/team/invitations')) : null,
    ])
    return { members, roles, catalogue, invitations }
  }, [manageMembers, manageRoles])

  const load = useCallback(async () => {
    try {
      setData(await fetchAll())
      setError(null)
    } catch (err) {
      setError(asApiError(err))
    }
  }, [fetchAll])

  useEffect(() => {
    if (!teamPlan) return
    let cancelled = false
    fetchAll()
      .then((d) => !cancelled && setData(d))
      .catch((err) => !cancelled && setError(asApiError(err)))
    return () => {
      cancelled = true
    }
  }, [fetchAll, teamPlan, workspace.id])

  if (!teamPlan)
    return (
      <div className="a-page">
        <div className="a-locked">
          <p className="a-eyebrow">Team</p>
          <h1 className="a-title">Bring your team in.</h1>
          <p className="a-muted">Add agents who publish their own listings under your brand. Available on the Team and Brokerage plans.</p>
          {workspace.is_admin && (
            <Link href="/studio/billing" className="a-btn a-btn--primary">
              See plans
            </Link>
          )}
        </div>
      </div>
    )

  if (error && !data)
    return (
      <div className="a-page a-page--narrow">
        <PageHead eyebrow="Workspace" title="Team" />
        <LoadFailed error={error} onRetry={() => void load()} />
      </div>
    )
  if (!data) return <PageSkeleton label="Loading your team" />

  const update = (patch: Partial<Data>) => setData((d) => (d ? { ...d, ...patch } : d))

  return (
    <div className="a-page a-page--narrow">
      <PageHead
        eyebrow="Workspace"
        title="Team"
        sub={
          data.invitations ? (
            <span>
              <CountUp value={data.invitations.seats.used} /> of <span className="a-num">{data.invitations.seats.total}</span> seats used
            </span>
          ) : undefined
        }
      />
      <div className="a-stack">
        <Members data={data} onChange={(members) => update({ members })} reload={load} />
        {data.invitations && data.roles && <InvitationsCard invitations={data.invitations} roles={data.roles} reload={load} />}
        {manageRoles && data.roles && data.catalogue && (
          <RolesCard roles={data.roles} catalogue={data.catalogue} onChange={(roles) => update({ roles })} />
        )}
        {workspace.is_admin && data.roles && <TransferAdmin members={data.members} roles={data.roles} onDone={(members) => update({ members })} />}
        {!workspace.is_admin && <LeaveTeam members={data.members} />}
      </div>
    </div>
  )
}

// Members -----------------------------------------------------------------------

function Members({ data, onChange, reload }: { data: Data; onChange: (m: Member[]) => void; reload: () => Promise<void> }) {
  const { can, noteError, toast } = useWorkspace()
  const manage = can('team.manage_members')
  const [removing, setRemoving] = useState<Member | null>(null)
  const [rowError, setRowError] = useState<{ id: string; error: ApiError } | null>(null)

  const changeRole = async (m: Member, roleId: string) => {
    setRowError(null)
    try {
      const updated = await unwrap(api.PATCH('/api/v1/team/members/{member_id}', { params: { path: { member_id: m.id } }, body: { role_id: roleId } }))
      onChange(data.members.map((x) => (x.id === m.id ? updated : x)))
      toast(`${m.name} is now ${updated.role?.name ?? 'updated'}`)
    } catch (err) {
      setRowError({ id: m.id, error: noteError(err) })
    }
  }

  return (
    <section className="a-card" aria-labelledby="members-title">
      <h2 id="members-title" className="a-card__title">
        Members
      </h2>
      <ul className="a-members">
        {data.members.map((m) => (
          <li key={m.id}>
            <span className="a-members__avatar" aria-hidden>
              {initials(m.name)}
            </span>
            <span>
              <strong>
                {m.name}
                {m.is_you && ' (you)'}
              </strong>
              <small>
                {[m.email, m.licence_number && `Licence ${m.licence_number}`, `Joined ${dateFmt(m.joined_at)}`].filter(Boolean).join(' · ')}
              </small>
              {rowError?.id === m.id && (
                <span role="alert" className="a-field__error" style={{ display: 'block' }}>
                  {rowError.error.message}
                </span>
              )}
            </span>
            {manage && !m.is_admin && !m.is_you && data.roles ? (
              <>
                <label className="visually-hidden" htmlFor={`role-${m.id}`}>
                  Role for {m.name}
                </label>
                <select id={`role-${m.id}`} className="a-input a-input--sm" value={m.role?.id ?? ''} onChange={(e) => void changeRole(m, e.target.value)}>
                  {!m.role && <option value="">No role</option>}
                  {data.roles.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.name}
                    </option>
                  ))}
                </select>
              </>
            ) : (
              <span className="a-members__role">{m.is_admin ? 'Admin' : (m.role?.name ?? '')}</span>
            )}
            {manage && !m.is_admin && !m.is_you ? (
              <button type="button" className="a-link a-link--danger" onClick={() => setRemoving(m)}>
                Remove<span className="visually-hidden"> {m.name}</span>
              </button>
            ) : m.is_you ? (
              <LicenceEdit member={m} onSaved={(u) => onChange(data.members.map((x) => (x.id === u.id ? u : x)))} />
            ) : (
              <span />
            )}
          </li>
        ))}
      </ul>
      {removing && (
        <RemoveDialog
          member={removing}
          members={data.members}
          onClose={() => setRemoving(null)}
          onRemoved={() => {
            toast(`${removing.name} was removed`)
            setRemoving(null)
            void reload()
          }}
        />
      )}
    </section>
  )
}

function LicenceEdit({ member, onSaved }: { member: Member; onSaved: (m: Member) => void }) {
  const { noteError, toast } = useWorkspace()
  const [open, setOpen] = useState(false)
  const [value, setValue] = useState(member.licence_number ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  if (!open)
    return (
      <button type="button" className="a-link" onClick={() => setOpen(true)}>
        {member.licence_number ? 'Edit licence' : 'Add licence'}
      </button>
    )
  return (
    <Dialog title="Your licence number" onClose={() => setOpen(false)}>
      <form
        className="a-form"
        noValidate
        onSubmit={async (e) => {
          e.preventDefault()
          setBusy(true)
          setError(null)
          try {
            const m = await unwrap(
              api.PATCH('/api/v1/team/members/{member_id}', { params: { path: { member_id: member.id } }, body: { licence_number: value.trim() } }),
            )
            onSaved(m)
            toast('Licence number saved')
            setOpen(false)
          } catch (err) {
            setError(noteError(err))
          } finally {
            setBusy(false)
          }
        }}
      >
        <Field label="Licence number" hint="Shown on listings where your country requires it." error={error?.fields.licence_number}>
          {(a) => <input {...a} className="a-input" value={value} onChange={(e) => setValue(e.target.value)} />}
        </Field>
        {!error?.fields.licence_number && <ErrorAlert error={error} />}
        <div className="a-actions">
          <button type="submit" className="a-btn a-btn--primary" disabled={busy}>
            {busy ? 'Saving…' : 'Save'}
          </button>
          <button type="button" className="a-btn a-btn--ghost" onClick={() => setOpen(false)}>
            Cancel
          </button>
        </div>
      </form>
    </Dialog>
  )
}

/** "Who takes over their listings?" — the successor picker shared by Remove and Leave. */
function SuccessorField({ members, exclude, value, onChange }: { members: Member[]; exclude: string; value: string; onChange: (v: string) => void }) {
  const admin = members.find((m) => m.is_admin)
  const others = members.filter((m) => m.id !== exclude && !m.is_admin && m.can_be_listing_agent)
  return (
    <Field label="Who takes over their listings?" hint="Their listings and enquiries move to this person.">
      {(a) => (
        <select {...a} className="a-input" value={value} onChange={(e) => onChange(e.target.value)}>
          <option value="">{admin ? `${admin.name} (Admin)` : 'The Admin'}</option>
          {others.map((m) => (
            <option key={m.id} value={m.id}>
              {m.name}
            </option>
          ))}
        </select>
      )}
    </Field>
  )
}

function RemoveDialog({ member, members, onClose, onRemoved }: { member: Member; members: Member[]; onClose: () => void; onRemoved: () => void }) {
  const { noteError } = useWorkspace()
  const [successor, setSuccessor] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  return (
    <Dialog eyebrow="Remove member" title={`Remove ${member.name}?`} onClose={onClose}>
      <p className="a-muted">They lose access to this workspace straight away.</p>
      <SuccessorField members={members} exclude={member.id} value={successor} onChange={setSuccessor} />
      <ErrorAlert error={error} />
      <div className="a-actions">
        <button
          type="button"
          className="a-btn a-btn--danger"
          disabled={busy}
          onClick={async () => {
            setBusy(true)
            setError(null)
            try {
              await unwrap(
                api.POST('/api/v1/team/members/{member_id}/remove', {
                  params: { path: { member_id: member.id } },
                  body: { successor_id: successor || null },
                }),
              )
              onRemoved()
            } catch (err) {
              setError(noteError(err))
              setBusy(false)
            }
          }}
        >
          {busy ? 'Removing…' : 'Remove'}
        </button>
        <button type="button" className="a-btn a-btn--ghost" onClick={onClose}>
          Cancel
        </button>
      </div>
    </Dialog>
  )
}

// Invitations -------------------------------------------------------------------

function InvitationsCard({ invitations, roles, reload }: { invitations: Invitations; roles: Role[]; reload: () => Promise<void> }) {
  const { noteError, toast } = useWorkspace()
  const [error, setError] = useState<ApiError | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const full = invitations.seats.used >= invitations.seats.total

  const act = async (id: string, kind: 'resend' | 'delete', email: string) => {
    setBusyId(id)
    setError(null)
    try {
      if (kind === 'resend') await unwrap(api.POST('/api/v1/team/invitations/{invitation_id}/resend', { params: { path: { invitation_id: id } } }))
      else await unwrap(api.DELETE('/api/v1/team/invitations/{invitation_id}', { params: { path: { invitation_id: id } } }))
      toast(kind === 'resend' ? `New link sent to ${email}` : `Invitation to ${email} withdrawn`)
      await reload()
    } catch (err) {
      setError(noteError(err))
    } finally {
      setBusyId(null)
    }
  }

  return (
    <section className="a-card" aria-labelledby="inv-title">
      <div className="a-card__head">
        <h2 id="inv-title" className="a-card__title">
          Invitations
        </h2>
        <span className={`a-badge ${full ? 'a-badge--warn' : ''}`}>
          <span className="a-num">
            {invitations.seats.used} / {invitations.seats.total}
          </span>
          &nbsp;seats
        </span>
      </div>
      <InviteForm roles={roles} onSent={() => void reload()} disabled={full} />
      {full && <p className="a-muted">Every seat is taken. Withdraw an invitation or remove a member to invite someone new.</p>}
      <ErrorAlert error={error} />
      {invitations.items.length > 0 && (
        <ul className="a-list" style={{ marginTop: '1.2rem' }}>
          {invitations.items.map((inv) => (
            <li key={inv.id}>
              <div>
                <strong>{inv.email}</strong>
                <span className="a-muted">
                  {inv.role.name} · invited by {inv.invited_by} ·{' '}
                  {inv.status === 'expired' ? 'expired' : `expires ${dateFmt(inv.expires_at)}`}
                </span>
              </div>
              <div className="a-tags">
                {inv.status === 'expired' && <span className="a-badge a-badge--warn">Expired</span>}
                <button type="button" className="a-btn a-btn--ghost a-btn--sm" disabled={busyId === inv.id} onClick={() => void act(inv.id, 'resend', inv.email)}>
                  Resend<span className="visually-hidden"> to {inv.email}</span>
                </button>
                <button type="button" className="a-link a-link--danger" disabled={busyId === inv.id} onClick={() => void act(inv.id, 'delete', inv.email)}>
                  Withdraw<span className="visually-hidden"> invitation to {inv.email}</span>
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

// Roles -------------------------------------------------------------------------

function RolesCard({ roles, catalogue, onChange }: { roles: Role[]; catalogue: Catalogue; onChange: (r: Role[]) => void }) {
  const { noteError, toast } = useWorkspace()
  const [editing, setEditing] = useState<Role | 'new' | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const label = (key: string) => catalogue.permissions.find((p) => p.key === key)?.label ?? key

  return (
    <section className="a-card" aria-labelledby="roles-title">
      <div className="a-card__head">
        <h2 id="roles-title" className="a-card__title">
          Roles
        </h2>
        <button type="button" className="a-btn a-btn--ghost a-btn--sm" onClick={() => setEditing('new')}>
          Create role
        </button>
      </div>
      <ErrorAlert error={error} />
      <ul className="a-list">
        {roles.map((r) => (
          <li key={r.id}>
            <div>
              <strong>{r.name}</strong>
              <span className="a-muted">
                {r.description || r.permissions.map(label).join(', ') || 'No permissions'} ·{' '}
                <span className="a-num">{r.member_count}</span> {r.member_count === 1 ? 'member' : 'members'}
              </span>
            </div>
            <div className="a-tags">
              <button type="button" className="a-btn a-btn--ghost a-btn--sm" onClick={() => setEditing(r)}>
                Edit<span className="visually-hidden"> {r.name}</span>
              </button>
              <button
                type="button"
                className="a-link a-link--danger"
                onClick={async () => {
                  setError(null)
                  try {
                    await unwrap(api.DELETE('/api/v1/team/roles/{role_id}', { params: { path: { role_id: r.id } } }))
                    onChange(roles.filter((x) => x.id !== r.id))
                    toast(`${r.name} deleted`)
                  } catch (err) {
                    setError(noteError(err))
                  }
                }}
              >
                Delete<span className="visually-hidden"> {r.name}</span>
              </button>
            </div>
          </li>
        ))}
      </ul>
      {editing && (
        <RoleDialog
          role={editing === 'new' ? null : editing}
          catalogue={catalogue}
          onClose={() => setEditing(null)}
          onSaved={(saved) => {
            onChange(editing === 'new' ? [...roles, saved] : roles.map((x) => (x.id === saved.id ? saved : x)))
            toast(`${saved.name} saved`)
            setEditing(null)
          }}
        />
      )}
    </section>
  )
}

function RoleDialog({ role, catalogue, onClose, onSaved }: { role: Role | null; catalogue: Catalogue; onClose: () => void; onSaved: (r: Role) => void }) {
  const { noteError } = useWorkspace()
  const [name, setName] = useState(role?.name ?? '')
  const [description, setDescription] = useState(role?.description ?? '')
  const [perms, setPerms] = useState<Set<string>>(() => new Set(role?.permissions ?? []))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  const groups = catalogue.permissions.reduce<Record<string, typeof catalogue.permissions>>((acc, p) => {
    ;(acc[p.group] ??= []).push(p)
    return acc
  }, {})

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (busy) return
    setBusy(true)
    setError(null)
    const body = { name: name.trim(), description: description.trim(), permissions: [...perms] }
    try {
      const saved = role
        ? await unwrap(api.PUT('/api/v1/team/roles/{role_id}', { params: { path: { role_id: role.id } }, body }))
        : await unwrap(api.POST('/api/v1/team/roles', { body }))
      onSaved(saved)
    } catch (err) {
      setError(noteError(err))
      setBusy(false)
    }
  }

  return (
    <Dialog eyebrow="Roles" title={role ? `Edit ${role.name}` : 'Create role'} onClose={onClose}>
      <form className="a-form" onSubmit={submit} noValidate>
        {!role && catalogue.suggestions.length > 0 && (
          <div>
            <p className="a-field__label" id="role-suggest">
              Start from a suggestion
            </p>
            <div className="a-chips" role="group" aria-labelledby="role-suggest">
              {catalogue.suggestions.map((s) => (
                <button
                  key={s.name}
                  type="button"
                  className="a-chip"
                  onClick={() => {
                    setName(s.name)
                    setDescription(s.description)
                    setPerms(new Set(s.permissions))
                  }}
                >
                  {s.name}
                </button>
              ))}
            </div>
          </div>
        )}
        <Field label="Name" error={error?.fields.name}>
          {(a) => <input {...a} className="a-input" maxLength={60} value={name} onChange={(e) => setName(e.target.value)} />}
        </Field>
        <Field label="Description" optional error={error?.fields.description}>
          {(a) => <input {...a} className="a-input" value={description} onChange={(e) => setDescription(e.target.value)} />}
        </Field>
        <div className="a-perms">
          {Object.entries(groups).map(([group, items]) => (
            <fieldset key={group}>
              <legend>{group}</legend>
              {items.map((p) => (
                <label key={p.key} className="a-switch">
                  <input
                    type="checkbox"
                    role="switch"
                    checked={perms.has(p.key)}
                    onChange={(e) =>
                      setPerms((s) => {
                        const next = new Set(s)
                        if (e.target.checked) next.add(p.key)
                        else next.delete(p.key)
                        return next
                      })
                    }
                  />
                  <span>
                    <strong>{p.label}</strong>
                    <small>{p.description}</small>
                  </span>
                </label>
              ))}
            </fieldset>
          ))}
        </div>
        {!error?.fields.name && !error?.fields.description && <ErrorAlert error={error} />}
        <div className="a-actions">
          <button type="submit" className="a-btn a-btn--primary" disabled={busy}>
            {busy ? 'Saving…' : role ? 'Save role' : 'Create role'}
          </button>
          <button type="button" className="a-btn a-btn--ghost" onClick={onClose}>
            Cancel
          </button>
        </div>
      </form>
    </Dialog>
  )
}

// Danger zone -------------------------------------------------------------------

function TransferAdmin({ members, roles, onDone }: { members: Member[]; roles: Role[]; onDone: (m: Member[]) => void }) {
  const { noteError, reload, toast } = useWorkspace()
  const { refresh } = useSession()
  const [open, setOpen] = useState(false)
  const [memberId, setMemberId] = useState('')
  const [roleId, setRoleId] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  const candidates = members.filter((m) => !m.is_you && !m.is_admin)
  const member = memberId || candidates[0]?.id || ''
  const role = roleId || roles[0]?.id || ''

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (busy || !member || !role || !password) return
    setBusy(true)
    setError(null)
    try {
      const next = await unwrap(api.POST('/api/v1/team/transfer-admin', { body: { member_id: member, my_new_role_id: role, password } }))
      onDone(next)
      setOpen(false)
      toast('Admin handed over')
      await Promise.all([reload(), refresh()])
    } catch (err) {
      setError(noteError(err))
      setBusy(false)
    }
  }

  return (
    <section className="a-card a-danger" aria-labelledby="transfer-title">
      <p className="a-eyebrow">Danger zone</p>
      <h2 id="transfer-title" className="a-card__title">
        Transfer Admin
      </h2>
      <p className="a-muted">Hand the workspace, billing and team to another member. You keep access with the role you choose.</p>
      <div className="a-actions">
        <button type="button" className="a-btn a-btn--danger" disabled={!candidates.length} onClick={() => setOpen(true)}>
          Transfer Admin…
        </button>
      </div>
      {!candidates.length && <p className="a-muted">Invite someone first; only team members can become Admin.</p>}
      {open && (
        <Dialog eyebrow="Danger zone" title="Transfer Admin" onClose={() => setOpen(false)}>
          <form className="a-form" onSubmit={submit} noValidate>
            <Field label="New Admin" error={error?.code === 'invalid_member' ? error.message : null}>
              {(a) => (
                <select {...a} className="a-input" value={member} onChange={(e) => setMemberId(e.target.value)}>
                  {candidates.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.name}
                    </option>
                  ))}
                </select>
              )}
            </Field>
            <Field label="Your role afterwards" error={error?.code === 'invalid_role' ? error.message : null}>
              {(a) => (
                <select {...a} className="a-input" value={role} onChange={(e) => setRoleId(e.target.value)}>
                  {roles.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.name}
                    </option>
                  ))}
                </select>
              )}
            </Field>
            <Field label="Your password" error={error?.code === 'invalid_password' ? error.message : null}>
              {(a) => (
                <input {...a} className="a-input" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
              )}
            </Field>
            {error && !['invalid_member', 'invalid_role', 'invalid_password'].includes(error.code) && <ErrorAlert error={error} />}
            <div className="a-actions">
              <button type="submit" className="a-btn a-btn--danger" disabled={busy || !password}>
                {busy ? 'Transferring…' : 'Transfer Admin'}
              </button>
              <button type="button" className="a-btn a-btn--ghost" onClick={() => setOpen(false)}>
                Cancel
              </button>
            </div>
          </form>
        </Dialog>
      )}
    </section>
  )
}

function LeaveTeam({ members }: { members: Member[] }) {
  const { noteError } = useWorkspace()
  const { signedIn } = useSession()
  const router = useRouter()
  const me = members.find((m) => m.is_you)
  const [open, setOpen] = useState(false)
  const [successor, setSuccessor] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)

  return (
    <section className="a-card a-danger" aria-labelledby="leave-title">
      <h2 id="leave-title" className="a-card__title">
        Leave this team
      </h2>
      <p className="a-muted">You lose access to this workspace. Your own account stays.</p>
      <div className="a-actions">
        <button type="button" className="a-btn a-btn--danger" onClick={() => setOpen(true)}>
          Leave team…
        </button>
      </div>
      {open && (
        <Dialog eyebrow="Team" title="Leave this team?" onClose={() => setOpen(false)}>
          <SuccessorField members={members} exclude={me?.id ?? ''} value={successor} onChange={setSuccessor} />
          <ErrorAlert error={error} />
          <div className="a-actions">
            <button
              type="button"
              className="a-btn a-btn--danger"
              disabled={busy}
              onClick={async () => {
                setBusy(true)
                setError(null)
                try {
                  signedIn(await unwrap(api.POST('/api/v1/team/leave', { body: { successor_id: successor || null } })))
                  router.push('/studio')
                } catch (err) {
                  setError(noteError(err))
                  setBusy(false)
                }
              }}
            >
              {busy ? 'Leaving…' : 'Leave team'}
            </button>
            <button type="button" className="a-btn a-btn--ghost" onClick={() => setOpen(false)}>
              Cancel
            </button>
          </div>
        </Dialog>
      )}
    </section>
  )
}

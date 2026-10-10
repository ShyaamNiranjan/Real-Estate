'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useState, type FormEvent } from 'react'
import { ChangeEmail } from '@/components/studio/ChangeEmail'
import {
  ABOUT_KEYS,
  AboutFields,
  CONTACT_KEYS,
  ContactFields,
  SITE_KEYS,
  StylePicker,
  UsernameClaim,
  suggestUsername,
  useComplianceProfiles,
  useProfileDraft,
  type Draft,
} from '@/components/studio/profile'
import { Dialog, ErrorAlert, Field, PageHead } from '@/components/studio/ui'
import { api } from '@/lib/api/client'
import { unwrap, type ApiError } from '@/lib/api/errors'
import { useSession } from '@/lib/session'
import { useWorkspace } from '@/lib/studio'

export function Settings() {
  const { workspace: ws, me, can } = useWorkspace()
  const brand = can('site.edit_brand')
  const contact = can('site.edit_contact')
  return (
    <div className="a-page a-page--narrow">
      <PageHead eyebrow="Workspace" title="Settings" />
      <div className="a-stack">
        {(brand || contact) && <ProfileCard brand={brand} contact={contact} />}
        {brand && !ws.username && ws.can_claim_username && <UsernameCard />}
        <ChangeEmail hasPassword={me.user.has_password} />
        <SessionsCard />
        {ws.is_admin && <DangerZone />}
      </div>
    </div>
  )
}

function ProfileCard({ brand, contact }: { brand: boolean; contact: boolean }) {
  const { toast, workspace, can } = useWorkspace()
  const profile = useProfileDraft()
  const profiles = useComplianceProfiles()
  const pages = can('site.edit_pages')
  const keys: (keyof Draft)[] = [
    ...(brand ? [...ABOUT_KEYS, 'style_preset' as const] : []),
    ...(contact ? CONTACT_KEYS : []),
    ...(pages ? SITE_KEYS : []),
  ]

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (await profile.save(keys)) toast('Saved')
  }

  return (
    <form className="a-card" onSubmit={submit} noValidate aria-labelledby="profile-title">
      <div className="a-card__head">
        <h2 id="profile-title" className="a-card__title">
          Profile
        </h2>
        {workspace.username && <span className="a-badge a-num">scrollwalk.com/{workspace.username}</span>}
      </div>
      <div className="a-guide__grid" style={{ marginTop: 0 }}>
        {brand && (
          <AboutFields draft={profile.draft} set={profile.set} errors={profile.errors} profiles={profiles} team={workspace.kind === 'team'} />
        )}
        {contact && <ContactFields draft={profile.draft} set={profile.set} errors={profile.errors} />}
        {pages && (
          <>
            <Field label="Tagline" optional wide hint="A line under your name on the About page." error={profile.errors.tagline}>
              {(a) => <input {...a} className="a-input" value={profile.draft.tagline} onChange={(e) => profile.set('tagline', e.target.value)} />}
            </Field>
            <Field label="About you" optional wide error={profile.errors.bio}>
              {(a) => <textarea {...a} className="a-input" rows={4} value={profile.draft.bio} onChange={(e) => profile.set('bio', e.target.value)} />}
            </Field>
          </>
        )}
        {brand && (
          <StylePicker value={profile.draft.style_preset} onChange={(v) => profile.set('style_preset', v)} error={profile.errors.style_preset} />
        )}
      </div>
      <ErrorAlert error={profile.failure} />
      <div className="a-actions">
        <button type="submit" className="a-btn a-btn--primary" disabled={profile.busy}>
          {profile.busy ? 'Saving…' : 'Save changes'}
        </button>
      </div>
    </form>
  )
}

function UsernameCard() {
  const { workspace, setWorkspace, toast } = useWorkspace()
  return (
    <section className="a-card" aria-labelledby="username-title">
      <h2 id="username-title" className="a-card__title">
        Your scrollwalk.com link
      </h2>
      <UsernameClaim
        suggested={suggestUsername(workspace.display_name)}
        onClaimed={(ws) => {
          setWorkspace(ws)
          toast(`scrollwalk.com/${ws.username} is yours`)
        }}
      />
    </section>
  )
}

function SessionsCard() {
  const { signOut } = useSession()
  const { noteError } = useWorkspace()
  const router = useRouter()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  return (
    <section className="a-card" aria-labelledby="sessions-title">
      <h2 id="sessions-title" className="a-card__title">
        Signed-in devices
      </h2>
      <p className="a-muted">Signs you out on every phone, tablet and computer, including this one.</p>
      <ErrorAlert error={error} />
      <div className="a-actions">
        <button
          type="button"
          className="a-btn a-btn--ghost"
          disabled={busy}
          onClick={async () => {
            setBusy(true)
            setError(null)
            try {
              await signOut(true)
              router.replace('/login')
            } catch (err) {
              setError(noteError(err))
              setBusy(false)
            }
          }}
        >
          {busy ? 'Signing out…' : 'Sign out everywhere'}
        </button>
      </div>
    </section>
  )
}

function DangerZone() {
  const [open, setOpen] = useState(false)
  return (
    <section className="a-card a-danger" aria-labelledby="danger-title">
      <p className="a-eyebrow">Danger zone</p>
      <h2 id="danger-title" className="a-card__title">
        Delete account
      </h2>
      <p className="a-muted">
        Takes your website and listings offline and deletes the workspace after a grace period. Team members lose access.
      </p>
      <div className="a-actions">
        <button type="button" className="a-btn a-btn--danger" onClick={() => setOpen(true)}>
          Delete account…
        </button>
      </div>
      {open && <DeleteDialog onClose={() => setOpen(false)} />}
    </section>
  )
}

function DeleteDialog({ onClose }: { onClose: () => void }) {
  const { noteError } = useWorkspace()
  const { signOut } = useSession()
  const router = useRouter()
  const [confirm, setConfirm] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  const [scheduled, setScheduled] = useState<string | null>(null)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (confirm !== 'DELETE' || !password || busy) return
    setBusy(true)
    setError(null)
    try {
      const res = await unwrap(api.POST('/api/v1/workspace/delete', { body: { confirm: 'DELETE', password } }))
      setScheduled(new Date(res.delete_after).toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' }))
    } catch (err) {
      setError(noteError(err))
    } finally {
      setBusy(false)
    }
  }

  if (scheduled)
    return (
      <Dialog eyebrow="Account" title="Your account is scheduled for deletion">
        <p className="a-muted">
          Everything is deleted on <strong className="a-num">{scheduled}</strong>. We’ve emailed you the details.
        </p>
        <div className="a-actions">
          <button
            type="button"
            className="a-btn a-btn--primary"
            onClick={async () => {
              try {
                await signOut()
              } finally {
                router.replace('/')
              }
            }}
          >
            Sign out
          </button>
        </div>
      </Dialog>
    )

  return (
    <Dialog eyebrow="Danger zone" title="Delete your account?" onClose={onClose}>
      <form className="a-form" onSubmit={submit} noValidate>
        <p className="a-muted">This takes your site and every listing offline. Type DELETE and enter your password to confirm.</p>
        <Field label="Type DELETE">
          {(a) => (
            <input
              {...a}
              className="a-input a-input--mono"
              autoComplete="off"
              autoCapitalize="characters"
              spellCheck={false}
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
            />
          )}
        </Field>
        <Field label="Password" error={error?.code === 'invalid_password' ? error.message : null}>
          {(a) => (
            <input {...a} className="a-input" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
          )}
        </Field>
        {error && error.code !== 'invalid_password' && (
          <div role="alert">
            <p className="a-alert a-alert--error">{error.message}</p>
            {error.code === 'cancel_subscription_first' && (
              <p>
                <Link className="a-linkbtn" href="/studio/billing">
                  Go to Billing
                </Link>
              </p>
            )}
          </div>
        )}
        <div className="a-actions">
          <button type="submit" className="a-btn a-btn--danger" disabled={busy || confirm !== 'DELETE' || !password}>
            {busy ? 'Deleting…' : 'Delete account'}
          </button>
          <button type="button" className="a-btn a-btn--ghost" onClick={onClose}>
            Cancel
          </button>
        </div>
      </form>
    </Dialog>
  )
}

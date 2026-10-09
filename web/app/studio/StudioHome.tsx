'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useEffect, useRef, useState } from 'react'
import { asApiError, type ApiError } from '@/lib/api/errors'
import type { Me } from '@/lib/api/client'
import { useSession } from '@/lib/session'
import { ChangeEmail } from './ChangeEmail'

export function StudioHome() {
  const { status, me, error, refresh } = useSession()
  const router = useRouter()
  const leaving = useRef(false)

  useEffect(() => {
    if (status === 'signed-out' && !leaving.current) router.replace('/login?next=/studio')
  }, [status, router])

  if (status === 'error') {
    return (
      <div className="a-boot">
        <div className="a-card a-boot__card" role="alert">
          <h1 className="a-title a-title--sm">We couldn&rsquo;t open your Studio.</h1>
          <p className="a-muted">{error?.message}</p>
          <button type="button" className="a-btn a-btn--primary" onClick={() => void refresh()}>
            Try again
          </button>
        </div>
      </div>
    )
  }

  if (status !== 'signed-in' || !me) {
    return (
      <div className="a-boot" role="status" aria-live="polite">
        <span className="a-spinner" aria-hidden />
        <span className="visually-hidden">Loading your Studio…</span>
      </div>
    )
  }

  return <Signed me={me} onLeaving={() => (leaving.current = true)} />
}

function workspaceName(name: string) {
  return name.trim() || 'Untitled workspace'
}

function Signed({ me, onLeaving }: { me: Me; onLeaving: () => void }) {
  const { signOut } = useSession()
  const router = useRouter()
  const [busy, setBusy] = useState<'one' | 'all' | null>(null)
  const [failure, setFailure] = useState<ApiError | null>(null)
  const { user, workspaces } = me
  const first = user.display_name.trim().split(/\s+/)[0] || 'there'
  const current = workspaces.find((w) => w.id === me.current_workspace_id) ?? workspaces[0] ?? null

  const doSignOut = async (everywhere: boolean) => {
    setBusy(everywhere ? 'all' : 'one')
    setFailure(null)
    onLeaving()
    try {
      await signOut(everywhere)
      router.replace('/login')
    } catch (err) {
      setFailure(asApiError(err))
      setBusy(null)
    }
  }

  return (
    <div className="a-shell">
      <aside className="a-side" aria-label="Studio">
        <div className="a-side__top">
          <Link href="/" className="a-side__brand" aria-label="Scrollwalk home">
            <span className="ye-mark ye-mark--light">
              scrollwalk<i aria-hidden />
            </span>
            <small>Studio</small>
          </Link>
        </div>
        <nav className="a-side__nav" aria-label="Studio sections">
          <Link href="/studio" className="a-side__link active" aria-current="page">
            Home
          </Link>
        </nav>
        <div className="a-side__foot">
          <p className="a-side__user" title={user.email}>
            {user.email}
          </p>
          <button type="button" className="a-side__signout" onClick={() => void doSignOut(false)} disabled={busy !== null}>
            {busy === 'one' ? 'Signing out…' : 'Sign out'}
          </button>
        </div>
      </aside>

      <main id="main" className="a-main">
        <div className="a-page a-page--narrow a-stack">
          <header className="a-page__head">
            <div>
              <p className="a-eyebrow">{current ? workspaceName(current.display_name) : 'Your Studio'}</p>
              <h1 className="a-title">Welcome, {first}.</h1>
              <p className="a-muted">Your Studio is being built. Listings, your site and the setup guide arrive here next.</p>
            </div>
          </header>

          {failure && (
            <p className="a-alert a-alert--error" role="alert">
              {failure.message}
            </p>
          )}

          <section className="a-card" aria-labelledby="account-title">
            <div className="a-card__head">
              <h2 id="account-title" className="a-card__title">
                Your account
              </h2>
            </div>
            <div className="a-profile">
              <span className="a-avatar" aria-hidden>
                {user.avatar_url ? (
                  // eslint-disable-next-line @next/next/no-img-element -- avatar from the API, any host
                  <img src={user.avatar_url} alt="" referrerPolicy="no-referrer" />
                ) : (
                  (user.display_name.trim()[0] ?? user.email[0] ?? '?').toUpperCase()
                )}
              </span>
              <dl className="a-dl">
                <div>
                  <dt>Name</dt>
                  <dd>{user.display_name || '—'}</dd>
                </div>
                <div>
                  <dt>Email</dt>
                  <dd>
                    {user.email}{' '}
                    <span className={`a-badge ${user.email_verified ? 'a-badge--ok' : 'a-badge--warn'}`}>
                      {user.email_verified ? 'Verified' : 'Not verified'}
                    </span>
                  </dd>
                </div>
                <div>
                  <dt>Sign-in</dt>
                  <dd>{user.has_password ? 'Email and password' : 'Google'}</dd>
                </div>
              </dl>
            </div>
          </section>

          <section className="a-card" aria-labelledby="ws-title">
            <div className="a-card__head">
              <h2 id="ws-title" className="a-card__title">
                Workspaces
              </h2>
              <span className="a-num a-muted">{workspaces.length}</span>
            </div>
            {workspaces.length === 0 ? (
              <p className="a-muted">No workspace yet.</p>
            ) : (
              <ul className="a-list">
                {workspaces.map((w) => (
                  <li key={w.id}>
                    <div>
                      <strong>{workspaceName(w.display_name)}</strong>
                      <span className="a-muted">
                        {w.username ? <code>scrollwalk.com/{w.username}</code> : 'No username yet'}
                      </span>
                    </div>
                    <span className="a-tags">
                      {w.id === current?.id && <span className="a-badge">Current</span>}
                      {w.is_admin && <span className="a-badge a-badge--gold">Admin</span>}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <ChangeEmail hasPassword={user.has_password} />

          <section className="a-card" aria-labelledby="sessions-title">
            <div className="a-card__head">
              <h2 id="sessions-title" className="a-card__title">
                Sessions
              </h2>
            </div>
            <p className="a-muted">Signed in on a shared or lost device? Sign out everywhere, including here.</p>
            <div className="a-actions">
              <button type="button" className="a-btn a-btn--ghost" onClick={() => void doSignOut(false)} disabled={busy !== null}>
                {busy === 'one' ? 'Signing out…' : 'Sign out'}
              </button>
              <button type="button" className="a-btn a-btn--danger" onClick={() => void doSignOut(true)} disabled={busy !== null}>
                {busy === 'all' ? 'Signing out…' : 'Sign out everywhere'}
              </button>
            </div>
          </section>
        </div>
      </main>
    </div>
  )
}

'use client'

import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { Suspense, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { api, type Me } from '@/lib/api/client'
import { asApiError, unwrap, type ApiError } from '@/lib/api/errors'
import type { components } from '@/lib/api/schema'
import { planByKey } from '@/lib/plans'
import { useSession } from '@/lib/session'
import { StudioProvider, SUPPORT_EMAIL, useStudio, type Workspace } from '@/lib/studio'
import { Dialog, ErrorAlert, LoadFailed, PageSkeleton, Toasts } from './ui'

type Announcement = components['schemas']['Announcement']
type NavItem = { href: string; label: string; show: boolean }

const DISMISSED_KEY = 'sw_dismissed_announcements'

/** Signed-in guard plus the Studio frame. Every Studio page renders inside this. */
export function StudioShell({ children }: { children: ReactNode }) {
  const { status, me, error, refresh } = useSession()
  const router = useRouter()
  const pathname = usePathname()

  useEffect(() => {
    if (status === 'signed-out') router.replace(`/login?next=${encodeURIComponent(pathname)}`)
  }, [status, router, pathname])

  if (status === 'error' && error)
    return (
      <div className="a-boot">
        <div className="a-boot__card">
          <p className="a-alert a-alert--error" role="alert">
            {error.message}
          </p>
          <button type="button" className="a-btn a-btn--ghost" onClick={() => void refresh()}>
            Try again
          </button>
        </div>
      </div>
    )

  if (status !== 'signed-in' || !me)
    return (
      <div className="a-boot" role="status" aria-label="Loading the Studio">
        <span className="a-spinner" aria-hidden />
      </div>
    )

  return (
    <StudioProvider me={me}>
      <Frame me={me}>{children}</Frame>
    </StudioProvider>
  )
}

function navItems(ws: Workspace | null, can: (p: string) => boolean, teamPlan: boolean): NavItem[] {
  const any = (...p: string[]) => p.some(can)
  return [
    { href: '/studio', label: 'Dashboard', show: true },
    { href: '/studio/listings', label: 'Listings', show: any('listings.create', 'listings.edit_own', 'listings.edit_all') },
    { href: '/studio/enquiries', label: 'Enquiries', show: any('enquiries.view_own', 'enquiries.view_all') },
    { href: '/studio/analytics', label: 'Analytics', show: any('analytics.view_own', 'analytics.view_all') },
    { href: '/studio/team', label: 'Team', show: teamPlan },
    { href: '/studio/billing', label: 'Billing', show: Boolean(ws?.is_admin) },
    { href: '/studio/settings', label: 'Settings', show: true },
  ]
}

function isActive(pathname: string, href: string) {
  if (href === '/studio') return pathname === '/studio' || pathname.startsWith('/studio/setup')
  return pathname === href || pathname.startsWith(`${href}/`)
}

function Frame({ me, children }: { me: Me; children: ReactNode }) {
  const { workspace, loadError, reload, can, teamPlan, readOnly, frozen, toasts } = useStudio()
  const { signOut } = useSession()
  const router = useRouter()
  const pathname = usePathname()
  const navRef = useRef<HTMLElement>(null)
  const [navOpenAt, setNavOpenAt] = useState<string | null>(null)
  const navOpen = navOpenAt === pathname
  const items = navItems(workspace, can, teamPlan).filter((i) => i.show)

  useLayoutEffect(() => {
    const nav = navRef.current
    if (!nav) return
    const place = () => {
      const active = nav.querySelector<HTMLElement>('.a-side__link.active')
      nav.style.setProperty('--ind-y', `${active?.offsetTop ?? 0}px`)
      nav.style.setProperty('--ind-h', `${active?.offsetHeight ?? 0}px`)
      nav.classList.toggle('has-active', Boolean(active))
    }
    place()
    window.addEventListener('resize', place)
    return () => window.removeEventListener('resize', place)
  }, [pathname, items.length])

  const plan = planByKey(workspace?.plan_key)

  return (
    <div className={`a-shell ${navOpen ? 'nav-open' : ''}`}>
      <aside className="a-side">
        <div className="a-side__top">
          <Link href="/studio" className="a-side__brand" aria-label="Scrollwalk Studio, dashboard">
            <span>scrollwalk</span>
            <small>Studio</small>
          </Link>
          <button
            type="button"
            className="a-side__toggle"
            aria-expanded={navOpen}
            aria-controls="studio-nav"
            aria-label="Menu"
            onClick={() => setNavOpenAt(navOpen ? null : pathname)}
          >
            <span />
            <span />
          </button>
        </div>

        <div className="a-side__workspace">
          <p>{workspace?.display_name ?? me.workspaces.find((w) => w.id === me.current_workspace_id)?.display_name ?? ' '}</p>
          <span className={`a-plan a-plan--${workspace?.plan_key ?? 'free'}`}>{plan?.name ?? 'Free preview'}</span>
          <WorkspaceSwitcher me={me} />
        </div>

        <nav id="studio-nav" className="a-side__nav" aria-label="Studio" ref={navRef}>
          {items.map((item) => {
            const active = isActive(pathname, item.href)
            return (
              <Link key={item.href} href={item.href} className={`a-side__link ${active ? 'active' : ''}`} aria-current={active ? 'page' : undefined}>
                {item.label}
              </Link>
            )
          })}
          {workspace?.username && workspace.site_state === 'live' && (
            <a href={`/${workspace.username}`} target="_blank" rel="noreferrer" className="a-side__link a-side__link--muted">
              View site ↗<span className="visually-hidden"> (opens in a new tab)</span>
            </a>
          )}
        </nav>

        <div className="a-side__foot">
          <p className="a-side__user" title={me.user.email}>
            {me.user.display_name || me.user.email}
          </p>
          <button
            type="button"
            className="a-side__signout"
            onClick={async () => {
              try {
                await signOut()
              } finally {
                router.replace('/login')
              }
            }}
          >
            Sign out
          </button>
        </div>
      </aside>

      <main className="a-main" id="main">
        {readOnly && (
          <div className="a-banner a-banner--staff" role="status">
            <strong>Scrollwalk support is viewing this account (read-only)</strong>
          </div>
        )}
        {frozen && (
          <div className="a-banner a-banner--frozen" role="alert">
            <div>
              <strong>{frozen}</strong>
              <p>
                <a className="a-linkbtn" href={`mailto:${SUPPORT_EMAIL}`}>
                  Contact support
                </a>
              </p>
            </div>
          </div>
        )}
        <Announcements />
        <fieldset className="a-ro" disabled={readOnly}>
          <div className="a-route" key={pathname.split('/')[2] ?? ''}>
            {workspace ? (
              <Suspense fallback={<PageSkeleton />}>{children}</Suspense>
            ) : loadError ? (
              <div className="a-page">
                <LoadFailed error={loadError} onRetry={() => void reload()} />
              </div>
            ) : (
              <div className="a-page">
                <PageSkeleton label="Loading your workspace" />
              </div>
            )}
          </div>
        </fieldset>
      </main>

      {!readOnly && me.legal_pending.length > 0 && <LegalDialog pending={me.legal_pending} />}
      <Toasts toasts={toasts} />
    </div>
  )
}

function WorkspaceSwitcher({ me }: { me: Me }) {
  const { signedIn } = useSession()
  const { readOnly, noteError, toast } = useStudio()
  const router = useRouter()
  const [busy, setBusy] = useState(false)
  if (me.workspaces.length < 2) return null
  return (
    <>
      <label htmlFor="ws-switch" className="visually-hidden">
        Switch workspace
      </label>
      <select
        id="ws-switch"
        className="a-side__switch"
        value={me.current_workspace_id ?? ''}
        disabled={busy || readOnly}
        onChange={async (e) => {
          setBusy(true)
          try {
            signedIn(await unwrap(api.POST('/api/v1/auth/workspace', { body: { workspace_id: e.target.value } })))
            router.push('/studio')
          } catch (err) {
            toast(noteError(err).message, 'error')
          } finally {
            setBusy(false)
          }
        }}
      >
        {me.workspaces.map((w) => (
          <option key={w.id} value={w.id}>
            {w.display_name}
            {w.is_admin ? '' : ' (member)'}
          </option>
        ))}
      </select>
    </>
  )
}

function readDismissed(): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(DISMISSED_KEY) ?? '[]')
    return Array.isArray(v) ? v.filter((x) => typeof x === 'string') : []
  } catch {
    return []
  }
}

function Announcements() {
  const { workspace } = useStudio()
  const [items, setItems] = useState<Announcement[]>([])
  const [dismissed, setDismissed] = useState<string[]>(readDismissed)
  const workspaceId = workspace?.id

  useEffect(() => {
    if (!workspaceId) return
    let cancelled = false
    api
      .GET('/api/v1/workspace/announcements')
      .then(({ data }) => {
        if (!cancelled && data) setItems(data)
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [workspaceId])

  const shown = items.filter((a) => !dismissed.includes(a.id))
  if (!shown.length) return null
  return (
    <>
      {shown.map((a) => (
        <section key={a.id} className="a-banner" aria-label="Announcement">
          <div>
            <strong>{a.title}</strong>
            {a.body && <p>{a.body}</p>}
          </div>
          <button
            type="button"
            className="a-btn a-btn--ghost a-btn--sm"
            onClick={() => {
              const next = [...dismissed, a.id]
              setDismissed(next)
              try {
                // Keep only ids still being shown, so the list doesn't grow forever.
                localStorage.setItem(DISMISSED_KEY, JSON.stringify(next.filter((id) => items.some((x) => x.id === id))))
              } catch {}
            }}
          >
            Dismiss<span className="visually-hidden"> announcement: {a.title}</span>
          </button>
        </section>
      ))}
    </>
  )
}

const DOC_LABEL = { terms: 'Terms of Service', privacy: 'Privacy Policy' } as const

function LegalDialog({ pending }: { pending: Me['legal_pending'] }) {
  const { signedIn, refresh } = useSession()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)

  const accept = async () => {
    setBusy(true)
    setError(null)
    try {
      signedIn(await unwrap(api.POST('/api/v1/auth/legal/accept', { body: { documents: pending } })))
    } catch (err) {
      const e = asApiError(err)
      if (e.code === 'legal_version_changed') await refresh()
      setError(e)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog eyebrow="Before you continue" title="We've updated our terms">
      {pending.map((doc) => (
        <div key={`${doc.document}-${doc.version}`}>
          <p>
            <strong>{DOC_LABEL[doc.document]}</strong>{' '}
            <a className="a-linkbtn" href={`/${doc.document}`} target="_blank" rel="noreferrer">
              Read it<span className="visually-hidden"> (opens in a new tab)</span>
            </a>
          </p>
          {doc.summary && <p className="a-muted">{doc.summary}</p>}
        </div>
      ))}
      <ErrorAlert error={error} />
      <div className="a-actions">
        <button type="button" className="a-btn a-btn--primary" disabled={busy} onClick={() => void accept()}>
          {busy ? 'Saving…' : 'I agree'}
        </button>
      </div>
    </Dialog>
  )
}

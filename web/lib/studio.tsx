'use client'

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { api, type Me } from './api/client'
import { ApiError, asApiError, unwrap } from './api/errors'
import type { components } from './api/schema'
import { useSession } from './session'

export type Workspace = components['schemas']['WorkspaceOut']
export type SetupStepKey = components['schemas']['SetupStep']['step']

export const TEAM_PLANS = new Set(['team', 'brokerage'])
export const SUPPORT_EMAIL = 'support@scrollwalk.com'

type Toast = { id: number; tone: 'ok' | 'error'; text: string }

type Studio = {
  me: Me
  workspace: Workspace | null
  /** Set when `GET /workspace` failed; the page shows it with a retry. */
  loadError: ApiError | null
  reload: () => Promise<void>
  /** Use the `WorkspaceOut` most writes return. */
  setWorkspace: (ws: Workspace) => void
  /** A staff member is viewing this account; every write is refused. */
  readOnly: boolean
  /** The message from `403 account_frozen`, once a write has hit it. */
  frozen: string | null
  can: (permission: string) => boolean
  teamPlan: boolean
  /** Route any write failure through this: it notices frozen accounts, then returns the error to show. */
  noteError: (err: unknown) => ApiError
  toast: (text: string, tone?: Toast['tone']) => void
  toasts: Toast[]
}

const StudioContext = createContext<Studio | null>(null)

export function StudioProvider({ me, children }: { me: Me; children: ReactNode }) {
  const { signedIn } = useSession()
  const [workspace, setWorkspace] = useState<Workspace | null>(null)
  const [loadError, setLoadError] = useState<ApiError | null>(null)
  const [frozen, setFrozen] = useState<string | null>(null)
  const [toasts, setToasts] = useState<Toast[]>([])
  const seq = useRef(0)

  const noteError = useCallback((err: unknown) => {
    const e = asApiError(err)
    if (e.code === 'account_frozen') setFrozen(e.message)
    return e
  }, [])

  const load = useCallback(async () => {
    try {
      return await unwrap(api.GET('/api/v1/workspace'))
    } catch (err) {
      const e = asApiError(err)
      if (e.code !== 'no_workspace') throw e
      // Removed from a team (or similar): land in the user's own workspace.
      signedIn(await unwrap(api.POST('/api/v1/auth/workspace', { body: {} })))
      return await unwrap(api.GET('/api/v1/workspace'))
    }
  }, [signedIn])

  const reload = useCallback(async () => {
    try {
      setWorkspace(await load())
      setLoadError(null)
    } catch (err) {
      setLoadError(noteError(err))
    }
  }, [load, noteError])

  const workspaceId = me.current_workspace_id
  useEffect(() => {
    let cancelled = false
    load()
      .then((ws) => {
        if (cancelled) return
        setWorkspace(ws)
        setLoadError(null)
      })
      .catch((err) => {
        if (!cancelled) setLoadError(asApiError(err))
      })
    return () => {
      cancelled = true
    }
  }, [load, workspaceId])

  const toast = useCallback((text: string, tone: Toast['tone'] = 'ok') => {
    const id = ++seq.current
    setToasts((t) => [...t, { id, tone, text }])
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), tone === 'error' ? 6000 : 3200)
  }, [])

  const value = useMemo<Studio>(() => {
    const perms = new Set(workspace?.my_permissions ?? [])
    return {
      me,
      workspace,
      loadError,
      reload,
      setWorkspace,
      readOnly: me.read_only,
      frozen,
      can: (p) => Boolean(workspace?.is_admin) || perms.has(p),
      teamPlan: TEAM_PLANS.has(workspace?.plan_key ?? ''),
      noteError,
      toast,
      toasts,
    }
  }, [me, workspace, loadError, reload, frozen, noteError, toast, toasts])

  return <StudioContext.Provider value={value}>{children}</StudioContext.Provider>
}

export function useStudio() {
  const studio = useContext(StudioContext)
  if (!studio) throw new Error('useStudio must be used inside <StudioProvider>')
  return studio
}

/** The signed-in Studio with its workspace loaded (pages render only once it is). */
export function useWorkspace() {
  const studio = useStudio()
  return { ...studio, workspace: studio.workspace as Workspace }
}

export function initials(name: string) {
  return (name.trim().charAt(0) || '?').toUpperCase()
}

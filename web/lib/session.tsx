'use client'

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, rememberCsrfToken, type Me } from './api/client'
import { ApiError, asApiError, unwrap } from './api/errors'

type Status = 'loading' | 'signed-in' | 'signed-out' | 'error'

type Session = {
  status: Status
  me: Me | null
  /** Set when `/auth/me` failed for a reason other than "not signed in" (e.g. the API is down). */
  error: ApiError | null
  /** Call with the `Me` returned by verify, login or reset. */
  signedIn: (me: Me) => void
  refresh: () => Promise<void>
  signOut: (everywhere?: boolean) => Promise<void>
}

const SessionContext = createContext<Session | null>(null)

export function SessionProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>('loading')
  const [me, setMe] = useState<Me | null>(null)
  const [error, setError] = useState<ApiError | null>(null)

  const signedIn = useCallback((next: Me) => {
    rememberCsrfToken(next.csrf_token)
    setMe(next)
    setError(null)
    setStatus('signed-in')
  }, [])

  const signedOut = useCallback(() => {
    rememberCsrfToken(null)
    setMe(null)
    setError(null)
    setStatus('signed-out')
  }, [])

  const refresh = useCallback(async () => {
    try {
      signedIn(await unwrap(api.GET('/api/v1/auth/me')))
    } catch (err) {
      const e = asApiError(err)
      if (e.status === 401) signedOut()
      else {
        setError(e)
        setStatus('error')
      }
    }
  }, [signedIn, signedOut])

  const signOut = useCallback(
    async (everywhere = false) => {
      try {
        await unwrap(api.POST(everywhere ? '/api/v1/auth/logout-all' : '/api/v1/auth/logout'))
      } catch (err) {
        // Already signed out on the server is still signed out.
        if (asApiError(err).status !== 401) throw err
      }
      signedOut()
    },
    [signedOut],
  )

  useEffect(() => {
    let cancelled = false
    api
      .GET('/api/v1/auth/me')
      .then(({ data, response }) => {
        if (cancelled) return
        if (response.ok && data) signedIn(data)
        else if (response.status === 401) signedOut()
        else {
          setError(new ApiError(response.status, 'server_error', 'We couldn’t load your account. Please try again.'))
          setStatus('error')
        }
      })
      .catch((err) => {
        if (cancelled) return
        setError(asApiError(err))
        setStatus('error')
      })
    return () => {
      cancelled = true
    }
  }, [signedIn, signedOut])

  const value = useMemo(
    () => ({ status, me, error, signedIn, refresh, signOut }),
    [status, me, error, signedIn, refresh, signOut],
  )

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
}

export function useSession() {
  const session = useContext(SessionContext)
  if (!session) throw new Error('useSession must be used inside <SessionProvider>')
  return session
}

/** Only same-site Studio paths are accepted as a post-sign-in destination. */
export function safeNext(next: string | null | undefined): string {
  if (next && /^\/studio(?:[/?#]|$)/.test(next)) return next
  return '/studio'
}

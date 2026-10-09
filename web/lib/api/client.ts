import createClient, { type Middleware } from 'openapi-fetch'
import type { components, paths } from './schema'

export type Me = components['schemas']['Me']
export type MeUser = components['schemas']['MeUser']
export type MeWorkspace = components['schemas']['MeWorkspace']

const CSRF_COOKIE = '__Host-sw_csrf'
const WRITE_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])

/** Fallback for when the cookie can't be read; set from `csrf_token` in `GET /auth/me`. Memory only. */
let csrfFromMe: string | null = null

export function rememberCsrfToken(token: string | null) {
  csrfFromMe = token
}

function readCookie(name: string): string | null {
  if (typeof document === 'undefined') return null
  for (const part of document.cookie.split(';')) {
    const [key, ...rest] = part.trim().split('=')
    if (key === name) return decodeURIComponent(rest.join('='))
  }
  return null
}

export function csrfToken(): string | null {
  return readCookie(CSRF_COOKIE) ?? csrfFromMe
}

const csrf: Middleware = {
  onRequest({ request }) {
    if (WRITE_METHODS.has(request.method.toUpperCase())) {
      const token = csrfToken()
      if (token) request.headers.set('X-CSRF-Token', token)
    }
    return request
  },
}

/**
 * Typed client for the FastAPI backend. Paths are same-origin (`/api/v1/...`); Next.js rewrites
 * them to FastAPI. The session cookie is HttpOnly and travels on its own; we never touch it.
 */
export const api = createClient<paths>({
  baseUrl: typeof window === 'undefined' ? 'http://localhost' : window.location.origin,
  credentials: 'include',
  headers: { 'Content-Type': 'application/json' },
})

api.use(csrf)

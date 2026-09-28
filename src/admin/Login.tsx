import { useState, type FormEvent } from 'react'
import { Link, Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../lib/auth'
import { brandParts, useDocumentTitle, useSite } from '../lib/site'
import { errorMessage } from './ui'

export function Login() {
  useDocumentTitle('Admin sign in')
  const { settings } = useSite()
  const brand = brandParts(settings.brand_name).name
  const { session, isAdmin, loading, signIn } = useAuth()
  const location = useLocation()
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  const from = (location.state as { from?: string } | null)?.from ?? '/admin'

  if (!loading && session && isAdmin) return <Navigate to={from.startsWith('/admin') ? from : '/admin'} replace />

  const onSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    const data = new FormData(e.currentTarget)
    setBusy(true)
    setError(null)
    try {
      await signIn(String(data.get('email') ?? '').trim(), String(data.get('password') ?? ''))
    } catch (err) {
      const msg = errorMessage(err)
      setError(/invalid/i.test(msg) ? 'That email and password do not match an account.' : msg)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="a-auth">
      <div className="a-auth__art" aria-hidden>
        <img src={settings.hero_image_url ?? '/media/sequence/frame-001.jpg'} alt="" />
        <div className="a-auth__art-veil" />
        <p className="a-auth__art-brand">{brand}</p>
      </div>
      <div className="a-auth__panel">
        <p className="a-auth__brand">{brand} · Studio</p>
        <h1 className="a-auth__title">Sign in to manage the collection.</h1>
        <form className="a-auth__form" onSubmit={onSubmit}>
          <label className="a-field">
            <span className="a-field__label">Email</span>
            <input className="a-input" name="email" type="email" autoComplete="username" required autoFocus />
          </label>
          <label className="a-field">
            <span className="a-field__label">Password</span>
            <span className="a-password">
              <input
                className="a-input"
                name="password"
                type={showPassword ? 'text' : 'password'}
                autoComplete="current-password"
                required
              />
              <button
                type="button"
                className="a-password__toggle"
                onClick={() => setShowPassword((v) => !v)}
                aria-label={showPassword ? 'Hide password' : 'Show password'}
                aria-pressed={showPassword}
              >
                {showPassword ? (
                  <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                    <path d="M3 3l18 18" />
                    <path d="M10.6 5.1A10.4 10.4 0 0 1 12 5c6 0 9.5 7 9.5 7a17.6 17.6 0 0 1-3.2 4.1" />
                    <path d="M6.6 6.6C3.9 8.4 2.5 12 2.5 12s3.5 7 9.5 7a9.8 9.8 0 0 0 5.4-1.6" />
                    <path d="M9.9 9.9a3 3 0 0 0 4.2 4.2" />
                  </svg>
                ) : (
                  <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                    <path d="M2.5 12S6 5 12 5s9.5 7 9.5 7-3.5 7-9.5 7-9.5-7-9.5-7Z" />
                    <circle cx="12" cy="12" r="3" />
                  </svg>
                )}
              </button>
            </span>
          </label>
          {error && (
            <p className="a-auth__error" role="alert">
              {error}
            </p>
          )}
          <button type="submit" className="a-btn a-btn--primary a-btn--block" disabled={busy}>
            {busy ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
        <Link to="/" className="a-auth__back">
          ← Back to the site
        </Link>
      </div>
    </div>
  )
}

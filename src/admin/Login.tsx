import { useState, type FormEvent } from 'react'
import { Link, Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../lib/auth'
import { useDocumentTitle, useSite } from '../lib/site'
import { errorMessage } from './ui'

export function Login() {
  useDocumentTitle('Admin sign in')
  const { settings } = useSite()
  const { session, isAdmin, loading, signIn } = useAuth()
  const location = useLocation()
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
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
        <p className="a-auth__art-brand">{settings.brand_name}</p>
      </div>
      <div className="a-auth__panel">
        <p className="a-auth__brand">{settings.brand_name} · Studio</p>
        <h1 className="a-auth__title">Sign in to manage the collection.</h1>
        <form className="a-auth__form" onSubmit={onSubmit}>
          <label className="a-field">
            <span className="a-field__label">Email</span>
            <input className="a-input" name="email" type="email" autoComplete="username" required autoFocus />
          </label>
          <label className="a-field">
            <span className="a-field__label">Password</span>
            <input className="a-input" name="password" type="password" autoComplete="current-password" required />
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

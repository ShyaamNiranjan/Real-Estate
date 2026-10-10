'use client'

import { useId, useRef, useState, type FormEvent } from 'react'
import { CODE_LENGTH, CodeInput } from '@/components/auth/CodeInput'
import { ResendCode } from '@/components/auth/ResendCode'
import { isEmail } from '@/components/forms'
import { api } from '@/lib/api/client'
import { asApiError, unwrap, type ApiError } from '@/lib/api/errors'
import { useSession } from '@/lib/session'

/** Change email: `POST /auth/email/change {new_email, password}` → code → `POST /auth/email/confirm {code}`. */
export function ChangeEmail({ hasPassword }: { hasPassword: boolean }) {
  const { signedIn } = useSession()
  const [open, setOpen] = useState(false)
  const [step, setStep] = useState<'form' | 'code'>('form')
  const [newEmail, setNewEmail] = useState('')
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [failure, setFailure] = useState<ApiError | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [sentAt, setSentAt] = useState(0)
  const emailRef = useRef<HTMLInputElement>(null)
  const codeRef = useRef<HTMLInputElement>(null)
  const id = useId()

  const reset = () => {
    setStep('form')
    setCode('')
    setPassword('')
    setErrors({})
    setFailure(null)
  }

  const request = async () => {
    await unwrap(api.POST('/api/v1/auth/email/change', { body: { new_email: newEmail.trim(), password } }))
    setSentAt(Date.now())
  }

  const submitForm = async (e: FormEvent) => {
    e.preventDefault()
    if (busy) return
    const next: Record<string, string> = {}
    if (!isEmail(newEmail)) next.new_email = 'Enter a valid email address.'
    if (!password) next.password = 'Enter your current password.'
    setErrors(next)
    setFailure(null)
    setNotice(null)
    if (Object.keys(next).length) return emailRef.current?.focus()
    setBusy(true)
    try {
      await request()
      setStep('code')
      requestAnimationFrame(() => codeRef.current?.focus())
    } catch (err) {
      const apiError = asApiError(err)
      setErrors(apiError.fields)
      if (!Object.keys(apiError.fields).length) setFailure(apiError)
    } finally {
      setBusy(false)
    }
  }

  const confirm = async (value: string) => {
    if (busy) return
    if (value.length !== CODE_LENGTH) {
      setErrors({ code: 'Enter the 6-digit code from the email.' })
      return codeRef.current?.focus()
    }
    setBusy(true)
    setFailure(null)
    try {
      const me = await unwrap(api.POST('/api/v1/auth/email/confirm', { body: { code: value } }))
      signedIn(me)
      setNotice(`Your email is now ${me.user.email}.`)
      setOpen(false)
      reset()
      setNewEmail('')
    } catch (err) {
      const apiError = asApiError(err)
      if (apiError.code === 'invalid_code' || apiError.fields.code) {
        setErrors({ code: apiError.fields.code ?? apiError.message })
        setCode('')
        codeRef.current?.focus()
      } else setFailure(apiError)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="a-card" aria-labelledby={`${id}-title`}>
      <div className="a-card__head">
        <h2 id={`${id}-title`} className="a-card__title">
          Email address
        </h2>
        {hasPassword && !open && (
          <button
            type="button"
            className="a-btn a-btn--ghost a-btn--sm"
            aria-expanded={false}
            aria-controls={`${id}-panel`}
            onClick={() => {
              setOpen(true)
              setNotice(null)
              requestAnimationFrame(() => emailRef.current?.focus())
            }}
          >
            Change email
          </button>
        )}
      </div>

      <div role="status" className="a-alert-slot">
        {notice && <p className="a-alert a-alert--ok">{notice}</p>}
      </div>

      {!hasPassword && (
        <p className="a-muted">You sign in with Google, so your email follows your Google account.</p>
      )}

      {open && step === 'form' && (
        <form id={`${id}-panel`} className="a-form" onSubmit={submitForm} noValidate>
          <label className="a-field">
            <span>New email</span>
            <input
              ref={emailRef}
              className="a-input"
              type="email"
              inputMode="email"
              autoComplete="email"
              spellCheck={false}
              autoCapitalize="none"
              value={newEmail}
              onChange={(e) => setNewEmail(e.target.value)}
              aria-invalid={errors.new_email ? true : undefined}
              aria-describedby={errors.new_email ? `${id}-email-error` : undefined}
            />
            {errors.new_email && (
              <small id={`${id}-email-error`} className="a-field__error">
                {errors.new_email}
              </small>
            )}
          </label>
          <label className="a-field">
            <span>Current password</span>
            <input
              className="a-input"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              aria-invalid={errors.password ? true : undefined}
              aria-describedby={errors.password ? `${id}-pw-error` : undefined}
            />
            {errors.password && (
              <small id={`${id}-pw-error`} className="a-field__error">
                {errors.password}
              </small>
            )}
          </label>
          {failure && (
            <p className="a-alert a-alert--error" role="alert">
              {failure.message}
            </p>
          )}
          <div className="a-actions">
            <button type="submit" className="a-btn a-btn--primary" disabled={busy}>
              {busy ? 'Sending…' : 'Send code'}
            </button>
            <button
              type="button"
              className="a-btn a-btn--ghost"
              onClick={() => {
                setOpen(false)
                reset()
              }}
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      {open && step === 'code' && (
        <form
          id={`${id}-panel`}
          className="a-form a-form--code"
          onSubmit={(e) => {
            e.preventDefault()
            void confirm(code)
          }}
          noValidate
        >
          <p className="a-muted" id={`${id}-sent`}>
            We sent a 6-digit code to <strong>{newEmail.trim()}</strong>. Your email changes once you enter it.
          </p>
          <CodeInput
            ref={codeRef}
            value={code}
            onChange={(v) => {
              setCode(v)
              if (errors.code) setErrors({})
            }}
            onComplete={(v) => void confirm(v)}
            error={errors.code}
            describedBy={`${id}-sent`}
          />
          {failure && (
            <p className="a-alert a-alert--error" role="alert">
              {failure.message}
            </p>
          )}
          <div className="a-actions">
            <button type="submit" className="a-btn a-btn--primary" disabled={busy}>
              {busy ? 'Confirming…' : 'Confirm new email'}
            </button>
            <ResendCode
              sentAt={sentAt}
              onResend={async () => {
                setFailure(null)
                try {
                  await request()
                  setCode('')
                  setNotice(`We sent a new code to ${newEmail.trim()}.`)
                } catch (err) {
                  setFailure(asApiError(err))
                }
              }}
            />
          </div>
          <p className="a-muted">
            Wrong email?{' '}
            <button
              type="button"
              className="a-linkbtn"
              onClick={() => {
                reset()
                requestAnimationFrame(() => emailRef.current?.focus())
              }}
            >
              Change it
            </button>
          </p>
        </form>
      )}
    </section>
  )
}

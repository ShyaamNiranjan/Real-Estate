'use client'

import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { FormAlert, SubmitButton } from '@/components/forms'
import { api } from '@/lib/api/client'
import { asApiError, unwrap, type ApiError } from '@/lib/api/errors'
import { CODE_LENGTH, CodeInput } from './CodeInput'
import { ResendCode } from './ResendCode'

type Props = {
  eyebrow: string
  title: string
  lede: ReactNode
  email: string
  purpose: 'verify' | 'reset'
  sentAt: number
  onSent: () => void
  submitLabel: string
  busyLabel: string
  /** Submit the code; throw an `ApiError` to show it. */
  onSubmit: (code: string) => Promise<void>
  onChangeEmail: () => void
  /** Extra fields under the code, e.g. the new password on the reset screen. */
  children?: ReactNode
  /** Submit as soon as six digits are in (off when more fields follow). */
  autoSubmit?: boolean
}

export function CodeStep({
  eyebrow,
  title,
  lede,
  email,
  purpose,
  sentAt,
  onSent,
  submitLabel,
  busyLabel,
  onSubmit,
  onChangeEmail,
  children,
  autoSubmit = true,
}: Props) {
  const [code, setCode] = useState('')
  const [codeError, setCodeError] = useState<string | null>(null)
  const [failure, setFailure] = useState<ApiError | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const ledeId = useId()

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  const run = async (value: string) => {
    if (busy) return
    if (value.length !== CODE_LENGTH) {
      setCodeError('Enter the 6-digit code from the email.')
      inputRef.current?.focus()
      return
    }
    setBusy(true)
    setFailure(null)
    setCodeError(null)
    setNotice(null)
    try {
      await onSubmit(value)
    } catch (err) {
      const e = asApiError(err)
      if (e.code === 'invalid_code' || e.fields.code) {
        setCodeError(e.fields.code ?? e.message)
        setCode('')
        inputRef.current?.focus()
      } else if (!(e.fields.password && Object.keys(e.fields).length === 1)) {
        // A lone password problem is shown on the password field by the screen that owns it.
        setFailure(e)
      }
      setBusy(false)
    }
  }

  const submit = (e: FormEvent) => {
    e.preventDefault()
    void run(code)
  }

  const resend = async () => {
    setFailure(null)
    setNotice(null)
    try {
      await unwrap(api.POST('/api/v1/auth/resend', { body: { email, purpose } }))
      onSent()
      setCode('')
      setCodeError(null)
      setNotice(`We sent a new code to ${email}.`)
      inputRef.current?.focus()
    } catch (err) {
      setFailure(asApiError(err))
    }
  }

  return (
    <form className="ye-form" onSubmit={submit} noValidate>
      <p className="ye-eyebrow">{eyebrow}</p>
      <h1 className="ye-signup__title">{title}</h1>
      <p className="ye-signup__lede" id={ledeId}>
        {lede}
      </p>
      <CodeInput
        ref={inputRef}
        describedBy={ledeId}
        value={code}
        onChange={(v) => {
          setCode(v)
          if (codeError) setCodeError(null)
        }}
        onComplete={autoSubmit ? (v) => void run(v) : undefined}
        error={codeError}
      />
      {children}
      <FormAlert error={failure} notice={notice} />
      <SubmitButton busy={busy} busyLabel={busyLabel}>
        {submitLabel}
      </SubmitButton>
      <div className="ye-code__actions">
        <ResendCode sentAt={sentAt} onResend={resend} />
        <p className="ye-signup__switch">
          Wrong email?{' '}
          <button type="button" className="ye-textbtn ye-textbtn--accent" onClick={onChangeEmail}>
            Change it
          </button>
        </p>
      </div>
      <p className="ye-signup__note">The code expires after 10 minutes. Check your spam folder if it hasn&rsquo;t arrived.</p>
    </form>
  )
}

'use client'

import { forwardRef, useId, useState, type InputHTMLAttributes, type ReactNode } from 'react'
import type { ApiError } from '@/lib/api/errors'

type FieldProps = Omit<InputHTMLAttributes<HTMLInputElement>, 'id'> & {
  label: string
  hint?: ReactNode
  error?: string | null
  /** Shown inside the input on the left, e.g. "@". */
  prefix?: string
  optional?: boolean
}

/** Labelled text input with hint and error wired to `aria-describedby`. */
export const Field = forwardRef<HTMLInputElement, FieldProps>(function Field(
  { label, hint, error, prefix, optional, className, ...input },
  ref,
) {
  const id = useId()
  const hintId = hint ? `${id}-hint` : undefined
  const errorId = error ? `${id}-error` : undefined
  const describedBy = [errorId, hintId].filter(Boolean).join(' ') || undefined
  return (
    <div className={`ye-field ${error ? 'is-invalid' : ''} ${className ?? ''}`}>
      <label htmlFor={id}>
        {label}
        {optional && <span className="ye-field__optional"> (optional)</span>}
      </label>
      <div className={prefix ? 'ye-field__affix' : undefined}>
        {prefix && (
          <span className="ye-field__prefix" aria-hidden>
            {prefix}
          </span>
        )}
        <input ref={ref} id={id} aria-invalid={error ? true : undefined} aria-describedby={describedBy} {...input} />
      </div>
      {error && (
        <p id={errorId} className="ye-field__error">
          {error}
        </p>
      )}
      {hint && <small id={hintId}>{hint}</small>}
    </div>
  )
})

/** Password input with a show/hide toggle. */
export const PasswordField = forwardRef<HTMLInputElement, Omit<FieldProps, 'type' | 'prefix'>>(function PasswordField(
  { label, hint, error, className, ...input },
  ref,
) {
  const id = useId()
  const [shown, setShown] = useState(false)
  const hintId = hint ? `${id}-hint` : undefined
  const errorId = error ? `${id}-error` : undefined
  const describedBy = [errorId, hintId].filter(Boolean).join(' ') || undefined
  return (
    <div className={`ye-field ${error ? 'is-invalid' : ''} ${className ?? ''}`}>
      <label htmlFor={id}>{label}</label>
      <div className="ye-field__affix ye-field__affix--end">
        <input
          ref={ref}
          id={id}
          type={shown ? 'text' : 'password'}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy}
          spellCheck={false}
          autoCapitalize="none"
          {...input}
        />
        <button
          type="button"
          className="ye-field__toggle"
          aria-pressed={shown}
          aria-controls={id}
          onClick={() => setShown((s) => !s)}
        >
          {shown ? 'Hide' : 'Show'}
          <span className="visually-hidden"> password</span>
        </button>
      </div>
      {error && (
        <p id={errorId} className="ye-field__error">
          {error}
        </p>
      )}
      {hint && <small id={hintId}>{hint}</small>}
    </div>
  )
})

/** Form-level message. Errors interrupt (`role="alert"`); notices are polite. */
export function FormAlert({ error, notice }: { error?: ApiError | string | null; notice?: string | null }) {
  const message = typeof error === 'string' ? error : error?.message
  return (
    <>
      <div className="ye-alert-slot" role="alert" aria-atomic>
        {message && <p className="ye-alert ye-alert--error">{message}</p>}
      </div>
      <div className="ye-alert-slot" role="status" aria-atomic>
        {notice && !message && <p className="ye-alert ye-alert--notice">{notice}</p>}
      </div>
    </>
  )
}

export function SubmitButton({ busy, children, busyLabel }: { busy: boolean; children: ReactNode; busyLabel?: string }) {
  return (
    <button type="submit" className="ye-btn ye-btn--primary ye-btn--block" aria-disabled={busy || undefined} disabled={busy}>
      {busy && <span className="ye-spinner" aria-hidden />}
      {busy ? (busyLabel ?? children) : children}
    </button>
  )
}

/** Client-side checks that mirror the API (SignupIn / LoginIn / ResetIn). */
export const isEmail = (value: string) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.trim())
export const PASSWORD_MIN = 8
export const PASSWORD_MAX = 128

export function passwordProblem(value: string): string | null {
  if (value.length < PASSWORD_MIN) return `Use at least ${PASSWORD_MIN} characters.`
  if (value.length > PASSWORD_MAX) return `Use ${PASSWORD_MAX} characters or fewer.`
  return null
}

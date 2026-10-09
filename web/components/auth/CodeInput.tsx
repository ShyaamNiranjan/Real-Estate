'use client'

import { forwardRef, useEffect, useId, useState } from 'react'

export const CODE_LENGTH = 6

type Props = {
  value: string
  onChange: (value: string) => void
  /** Called once the sixth digit lands (typing, paste or keyboard auto-fill). */
  onComplete?: (code: string) => void
  error?: string | null
  label?: string
  disabled?: boolean
  /** Id of text that explains where the code was sent. */
  describedBy?: string
}

/**
 * One real input (so paste and `one-time-code` auto-fill just work) drawn as six slots.
 * The input sits on top of the slots with transparent text.
 */
export const CodeInput = forwardRef<HTMLInputElement, Props>(function CodeInput(
  { value, onChange, onComplete, error, label = '6-digit code', disabled, describedBy },
  ref,
) {
  const id = useId()
  const [focused, setFocused] = useState(false)
  const errorId = error ? `${id}-error` : undefined
  const described = [errorId, describedBy].filter(Boolean).join(' ') || undefined

  useEffect(() => {
    if (value.length === CODE_LENGTH) onComplete?.(value)
    // Only fire when the value becomes complete, not when the callback identity changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value])

  return (
    <div className={`ye-field ye-code ${error ? 'is-invalid' : ''}`}>
      <label htmlFor={id}>{label}</label>
      <div className="ye-code__box">
        <input
          ref={ref}
          id={id}
          className="ye-code__input"
          value={value}
          onChange={(e) => onChange(e.target.value.replace(/\D/g, '').slice(0, CODE_LENGTH))}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          inputMode="numeric"
          autoComplete="one-time-code"
          pattern="[0-9]{6}"
          maxLength={CODE_LENGTH}
          spellCheck={false}
          disabled={disabled}
          aria-invalid={error ? true : undefined}
          aria-describedby={described}
          required
        />
        <div className="ye-code__slots" aria-hidden>
          {Array.from({ length: CODE_LENGTH }, (_, i) => {
            const active = focused && (i === value.length || (i === CODE_LENGTH - 1 && value.length === CODE_LENGTH))
            return (
              <span key={i} className={`ye-code__slot ${value[i] ? 'is-filled' : ''} ${active ? 'is-active' : ''}`}>
                {value[i] ?? ''}
              </span>
            )
          })}
        </div>
      </div>
      {error && (
        <p id={errorId} className="ye-field__error" role="alert">
          {error}
        </p>
      )}
    </div>
  )
})

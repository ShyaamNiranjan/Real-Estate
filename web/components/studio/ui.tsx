'use client'

import Link from 'next/link'
import { useEffect, useId, useLayoutEffect, useRef, useState, useSyncExternalStore, type ReactNode } from 'react'
import type { ApiError } from '@/lib/api/errors'

// Motion ------------------------------------------------------------------------

const REDUCED = '(prefers-reduced-motion: reduce)'

function subscribeReduced(onChange: () => void) {
  const mq = window.matchMedia(REDUCED)
  mq.addEventListener('change', onChange)
  return () => mq.removeEventListener('change', onChange)
}

export function useReducedMotion() {
  return useSyncExternalStore(
    subscribeReduced,
    () => window.matchMedia(REDUCED).matches,
    () => true,
  )
}

const easeOut = (t: number) => 1 - Math.pow(1 - t, 3)
const formatInt = (n: number) => Math.round(n).toLocaleString('en-US')

/** Number that counts up on first show and tweens between values after; static under reduced motion. */
export function CountUp({ value, format = formatInt, duration = 900 }: { value: number; format?: (n: number) => string; duration?: number }) {
  const reduced = useReducedMotion()
  const [shown, setShown] = useState(0)
  const from = useRef(0)
  useEffect(() => {
    if (reduced) {
      from.current = value
      return
    }
    const start = performance.now()
    const a = from.current
    let raf = 0
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration)
      const v = a + (value - a) * easeOut(t)
      from.current = v
      setShown(v)
      if (t < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [value, duration, reduced])
  return (
    <span className="a-num">
      <span aria-hidden>{format(reduced ? value : shown)}</span>
      <span className="visually-hidden">{format(value)}</span>
    </span>
  )
}

export function Skeleton({ w, h = 14, className = '' }: { w?: number | string; h?: number | string; className?: string }) {
  return <span className={`a-skel ${className}`} style={{ width: w, height: h }} aria-hidden />
}

/** Placeholder shaped like a typical Studio page while its data loads. */
export function PageSkeleton({ label = 'Loading' }: { label?: string }) {
  return (
    <div className="a-pageskel" role="status" aria-label={label}>
      <Skeleton w={110} h={10} />
      <Skeleton w="38%" h={34} />
      <div className="a-pageskel__row">
        {[0, 1, 2].map((i) => (
          <div key={i} className="a-pageskel__card">
            <Skeleton w="45%" h={10} />
            <Skeleton w="60%" h={28} />
            <Skeleton w="80%" h={10} />
          </div>
        ))}
      </div>
      <div className="a-pageskel__card a-pageskel__card--tall">
        <Skeleton w="30%" h={12} />
        <Skeleton w="100%" h={12} />
        <Skeleton w="92%" h={12} />
        <Skeleton w="70%" h={12} />
      </div>
    </div>
  )
}

// Layout -----------------------------------------------------------------------

export function PageHead({ eyebrow, title, sub, children }: { eyebrow?: string; title: string; sub?: ReactNode; children?: ReactNode }) {
  return (
    <header className="a-page__head">
      <div>
        {eyebrow && <p className="a-eyebrow">{eyebrow}</p>}
        <h1 className="a-title">{title}</h1>
        {sub && <p className="a-page__sub a-muted">{sub}</p>}
      </div>
      {children && <div className="a-page__head-actions">{children}</div>}
    </header>
  )
}

export function ComingSoon({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="a-page">
      <div className="a-locked">
        <p className="a-eyebrow">Coming soon</p>
        <h1 className="a-title">{title}</h1>
        <p className="a-muted">{children ?? 'This part of the Studio is on its way.'}</p>
        <Link href="/studio" className="a-btn a-btn--ghost">
          Back to the dashboard
        </Link>
      </div>
    </div>
  )
}

/** A page-level load failure with a retry. */
export function LoadFailed({ error, onRetry }: { error: ApiError; onRetry: () => void }) {
  return (
    <div className="a-card" role="alert">
      <p className="a-alert a-alert--error">{error.message}</p>
      <div className="a-actions">
        <button type="button" className="a-btn a-btn--ghost a-btn--sm" onClick={onRetry}>
          Try again
        </button>
      </div>
    </div>
  )
}

// Forms ------------------------------------------------------------------------

type FieldProps = {
  label: string
  hint?: ReactNode
  error?: string | null
  /** Shown instead of the hint, e.g. "Available". */
  ok?: string | null
  optional?: boolean
  wide?: boolean
  children: (props: { id: string; 'aria-describedby'?: string; 'aria-invalid'?: true }) => ReactNode
}

/** Label, hint and error wired to the control through `aria-describedby`. */
export function Field({ label, hint, error, ok, optional, wide, children }: FieldProps) {
  const id = useId()
  const describedBy = [error && `${id}-error`, ok && `${id}-ok`, hint && `${id}-hint`].filter(Boolean).join(' ') || undefined
  return (
    <div className={`a-field ${wide ? 'a-field--wide' : ''} ${error ? 'has-error' : ''}`}>
      <label className="a-field__label" htmlFor={id}>
        {label}
        {optional && <span className="a-muted"> (optional)</span>}
      </label>
      {children({ id, 'aria-describedby': describedBy, 'aria-invalid': error ? true : undefined })}
      {error && (
        <p id={`${id}-error`} className="a-field__error">
          {error}
        </p>
      )}
      {ok && !error && (
        <p id={`${id}-ok`} className="a-field__ok">
          {ok}
        </p>
      )}
      {hint && (
        <p id={`${id}-hint`} className="a-field__hint">
          {hint}
        </p>
      )}
    </div>
  )
}

/** Form-level error (interrupts) — always the API's own message. */
export function ErrorAlert({ error }: { error: ApiError | string | null | undefined }) {
  const message = typeof error === 'string' ? error : error?.message
  return (
    <div className="a-alert-slot" role="alert">
      {message && <p className="a-alert a-alert--error">{message}</p>}
    </div>
  )
}

// Dialog -----------------------------------------------------------------------

/**
 * Modal built on `<dialog>`: focus moves inside, Tab stays inside and the page behind is inert.
 * `onClose` undefined makes it blocking (Escape does nothing).
 */
export function Dialog({
  title,
  eyebrow,
  onClose,
  children,
}: {
  title: string
  eyebrow?: string
  onClose?: () => void
  children: ReactNode
}) {
  const ref = useRef<HTMLDialogElement>(null)
  const id = useId()
  const closeRef = useRef(onClose)
  useEffect(() => {
    closeRef.current = onClose
  })
  // Layout effect so the cleanup (close + focus back to the opener) runs before the node is removed.
  useLayoutEffect(() => {
    const dialog = ref.current
    if (!dialog) return
    const opener = document.activeElement as HTMLElement | null
    if (!dialog.open) dialog.showModal()
    const onCancel = (e: Event) => {
      e.preventDefault()
      closeRef.current?.()
    }
    dialog.addEventListener('cancel', onCancel)
    return () => {
      dialog.removeEventListener('cancel', onCancel)
      dialog.close()
      opener?.focus?.()
    }
  }, [])
  return (
    <dialog ref={ref} className="a-dialog__panel" aria-labelledby={`${id}-title`}>
      {eyebrow && <p className="a-eyebrow">{eyebrow}</p>}
      <h2 id={`${id}-title`} className="a-card__title a-card__title--lg">
        {title}
      </h2>
      {children}
    </dialog>
  )
}

// Toasts -----------------------------------------------------------------------

export function Toasts({ toasts }: { toasts: { id: number; tone: 'ok' | 'error'; text: string }[] }) {
  return (
    <div className="toasts" role="status" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className={`toast toast--${t.tone}`}>
          {t.text}
        </div>
      ))}
    </div>
  )
}

export const CHECK = (
  <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
    <path d="M5 12.5l4.5 4.5L19 7.5" />
  </svg>
)

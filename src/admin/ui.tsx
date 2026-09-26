import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useId,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import type { ListingStatus } from '../types/database'

// Toasts ---------------------------------------------------------------------

type Toast = { id: number; tone: 'ok' | 'error'; text: string }
const ToastContext = createContext<(text: string, tone?: Toast['tone']) => void>(() => {})

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const seq = useRef(0)
  const push = useCallback((text: string, tone: Toast['tone'] = 'ok') => {
    const id = ++seq.current
    setToasts((t) => [...t, { id, tone, text }])
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), tone === 'error' ? 6000 : 3200)
  }, [])
  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast toast--${t.tone}`}>
            {t.text}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast() {
  return useContext(ToastContext)
}

export function errorMessage(err: unknown) {
  if (err instanceof Error) return err.message
  if (typeof err === 'object' && err && 'message' in err) return String((err as { message: unknown }).message)
  return 'Something went wrong'
}

// Keyboard -------------------------------------------------------------------

/** Cmd/Ctrl+S triggers save while the component is mounted. */
export function useSaveShortcut(onSave: () => void, enabled = true) {
  const ref = useRef(onSave)
  ref.current = onSave
  useEffect(() => {
    if (!enabled) return
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 's') {
        e.preventDefault()
        ref.current()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [enabled])
}

/** Warns before leaving the tab with unsaved edits. */
export function useUnsavedGuard(dirty: boolean) {
  useEffect(() => {
    if (!dirty) return
    const onBefore = (e: BeforeUnloadEvent) => {
      e.preventDefault()
    }
    window.addEventListener('beforeunload', onBefore)
    return () => window.removeEventListener('beforeunload', onBefore)
  }, [dirty])
}

// Form fields ----------------------------------------------------------------

type FieldProps = {
  label: string
  hint?: ReactNode
  error?: string | null
  children: (id: string) => ReactNode
  wide?: boolean
}

export function Field({ label, hint, error, children, wide }: FieldProps) {
  const id = useId()
  return (
    <div className={`a-field ${wide ? 'a-field--wide' : ''} ${error ? 'has-error' : ''}`}>
      <label className="a-field__label" htmlFor={id}>
        {label}
      </label>
      {children(id)}
      {error ? <p className="a-field__error">{error}</p> : hint ? <p className="a-field__hint">{hint}</p> : null}
    </div>
  )
}

export function ColorField({
  label,
  value,
  onChange,
}: {
  label: string
  value: string
  onChange: (v: string) => void
}) {
  const valid = /^#[0-9a-f]{6}$/i.test(value)
  return (
    <Field label={label} error={value && !valid ? 'Use a 6-digit hex like #c4a574' : null}>
      {(id) => (
        <div className={`a-color ${value ? '' : 'is-empty'}`}>
          <input
            type="color"
            aria-label={`${label} picker`}
            value={valid ? value : '#000000'}
            onChange={(e) => onChange(e.target.value)}
          />
          <input id={id} className="a-input a-input--mono" value={value} onChange={(e) => onChange(e.target.value)} placeholder="Default" />
        </div>
      )}
    </Field>
  )
}

// Status ---------------------------------------------------------------------

export const STATUS_LABEL: Record<ListingStatus, string> = {
  draft: 'Draft',
  preview: 'Preview',
  published: 'Published',
}

export function StatusMark({ status }: { status: ListingStatus }) {
  return (
    <span className={`a-status a-status--${status}`}>
      <span className="a-status__dot" aria-hidden />
      {STATUS_LABEL[status]}
    </span>
  )
}

export function Spinner({ label = 'Loading' }: { label?: string }) {
  return (
    <div className="a-spinner" role="status" aria-label={label}>
      <span />
    </div>
  )
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="a-empty">
      <p className="a-empty__title">{title}</p>
      {children && <div className="a-empty__body">{children}</div>}
    </div>
  )
}

/** Two-step destructive action without a modal: click, then confirm within 4s. */
export function ConfirmButton({
  onConfirm,
  children,
  confirmLabel = 'Confirm delete',
  className = 'a-btn a-btn--ghost a-btn--danger',
  disabled,
}: {
  onConfirm: () => void
  children: ReactNode
  confirmLabel?: string
  className?: string
  disabled?: boolean
}) {
  const [armed, setArmed] = useState(false)
  useEffect(() => {
    if (!armed) return
    const t = window.setTimeout(() => setArmed(false), 4000)
    return () => window.clearTimeout(t)
  }, [armed])
  return (
    <button
      type="button"
      className={`${className} ${armed ? 'is-armed' : ''}`}
      disabled={disabled}
      onClick={() => {
        if (armed) {
          setArmed(false)
          onConfirm()
        } else setArmed(true)
      }}
    >
      {armed ? confirmLabel : children}
    </button>
  )
}

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="a-kbd">{children}</kbd>
}

export const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform)

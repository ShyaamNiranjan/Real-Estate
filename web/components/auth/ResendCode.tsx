'use client'

import { useEffect, useState } from 'react'

export const RESEND_AFTER_S = 30

/**
 * "Resend code", enabled 30 s after the last send. `sentAt` changes every time a code goes out,
 * which restarts the wait. The countdown itself isn't announced; the outcome is.
 */
export function ResendCode({
  sentAt,
  onResend,
}: {
  sentAt: number
  onResend: () => Promise<void>
}) {
  const [now, setNow] = useState(() => Date.now())
  const [busy, setBusy] = useState(false)
  const left = Math.max(0, RESEND_AFTER_S - Math.floor((now - sentAt) / 1000))

  useEffect(() => {
    if (left === 0) return
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [left, sentAt])

  const resend = async () => {
    if (left > 0 || busy) return
    setBusy(true)
    try {
      await onResend()
    } finally {
      setBusy(false)
      setNow(Date.now())
    }
  }

  return (
    <button type="button" className="ye-textbtn" onClick={resend} disabled={left > 0 || busy}>
      {busy ? 'Sending…' : left > 0 ? `Resend code in 0:${String(left).padStart(2, '0')}` : 'Resend code'}
    </button>
  )
}

'use client'

import { useEffect } from 'react'

export const REF_KEY = 'sw_ref'
export const isReferral = (value: string) => /^[A-Za-z0-9_.-]{1,64}$/.test(value)

/** Keeps a landing-page `?ref=` code in sessionStorage so sign-up can send it as `referral`. */
export function RefCapture() {
  useEffect(() => {
    const ref = new URLSearchParams(window.location.search).get('ref')
    if (!ref || !isReferral(ref)) return
    try {
      sessionStorage.setItem(REF_KEY, ref)
    } catch {}
  }, [])
  return null
}

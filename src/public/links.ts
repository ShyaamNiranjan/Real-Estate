export const SAFE_HREF = /^(https?:\/\/|\/(?!\/)|mailto:|tel:|#)/i

export function prefersReducedMotion() {
  return typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

/** Smooth-scrolls to an in-page anchor. Returns false when the target is not on the page. */
export function scrollToAnchor(id: string) {
  const el = document.getElementById(id)
  if (!el) return false
  el.scrollIntoView({ behavior: prefersReducedMotion() ? 'auto' : 'smooth', block: 'start' })
  return true
}

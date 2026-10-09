import Link from 'next/link'

export function YeMark() {
  return (
    <span className="ye-mark">
      scrollwalk<i aria-hidden />
    </span>
  )
}

export function YeFooter() {
  return (
    <footer className="ye-footer">
      <div className="ye-wrap ye-footer__inner">
        <div>
          <YeMark />
          <p>Homes you can walk through. Just scroll.</p>
        </div>
        <nav aria-label="Footer">
          <Link href="/#how">How it works</Link>
          <Link href="/#pricing">Pricing</Link>
          <Link href="/waitlist">Join the waitlist</Link>
          <Link href="/signup?start=free">Try it free</Link>
          <Link href="/login">Sign in</Link>
          <Link href="/terms">Terms</Link>
          <Link href="/privacy">Privacy</Link>
        </nav>
        <p className="ye-footer__base">© {new Date().getFullYear()} Scrollwalk · A YNIIDI company</p>
      </div>
    </footer>
  )
}

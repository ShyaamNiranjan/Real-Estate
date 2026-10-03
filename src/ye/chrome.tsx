import { Link } from 'react-router-dom'

/** Placeholder mark until the product name is chosen. */
export function YeMark() {
  return (
    <span className="ye-mark">
      YE<i aria-hidden />
    </span>
  )
}

export function YeFooter() {
  return (
    <footer className="ye-footer">
      <div className="ye-wrap ye-footer__inner">
        <div>
          <YeMark />
          <p>Listings your buyers can walk through.</p>
        </div>
        <nav aria-label="Footer">
          <a href="/#how">How it works</a>
          <a href="/#pricing">Pricing</a>
          <Link to="/signup?start=free">Try it free</Link>
          <Link to="/studio">Sign in</Link>
        </nav>
        <p className="ye-footer__base">© {new Date().getFullYear()} YNIIDI · Internal prototype, working name “YE”</p>
      </div>
    </footer>
  )
}

import { Link } from 'react-router-dom'

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
          <a href="/#how">How it works</a>
          <a href="/#pricing">Pricing</a>
          <Link to="/signup?start=free">Try it free</Link>
          <Link to="/studio">Sign in</Link>
        </nav>
        <p className="ye-footer__base">© {new Date().getFullYear()} Scrollwalk · A YNIIDI company</p>
      </div>
    </footer>
  )
}

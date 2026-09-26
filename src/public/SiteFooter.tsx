import { Link } from 'react-router-dom'
import { useSite } from '../lib/site'

export function SiteFooter() {
  const { settings } = useSite()
  return (
    <footer className="site-footer">
      <div className="site-footer__inner">
        <Link to="/" className="site-footer__brand">
          {settings.brand_name}
        </Link>
        <p className="site-footer__note">{settings.footer_note}</p>
        <div className="site-footer__meta">
          {settings.contact_email && <a href={`mailto:${settings.contact_email}`}>{settings.contact_email}</a>}
          {settings.contact_phone && <a href={`tel:${settings.contact_phone.replace(/\s+/g, '')}`}>{settings.contact_phone}</a>}
          <span>© {new Date().getFullYear()} YNIIDI</span>
        </div>
      </div>
    </footer>
  )
}

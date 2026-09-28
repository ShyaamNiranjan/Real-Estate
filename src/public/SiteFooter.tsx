import { Link, useLocation } from 'react-router-dom'
import { brandParts, useSite } from '../lib/site'
import { HOME_ANCHORS, SOCIAL_KEYS, SOCIAL_LABEL } from '../types/content'
import type { HomeSectionPreset } from '../types/database'
import { scrollToAnchor } from './links'

const QUICK_LINKS: { preset: HomeSectionPreset; label: string }[] = [
  { preset: 'collection', label: 'Collection' },
  { preset: 'walkthrough', label: 'Walk before you visit' },
  { preset: 'services', label: 'Services' },
  { preset: 'neighbourhoods', label: 'Neighbourhoods' },
  { preset: 'contact', label: 'Enquire' },
]

/** `presets` lists the home sections on the page; without it (other pages) every link is shown. */
export function SiteFooter({ presets }: { presets?: HomeSectionPreset[] }) {
  const { settings } = useSite()
  const { pathname } = useLocation()
  const { name, sub } = brandParts(settings.brand_name)
  const onHome = pathname === '/'
  const links = QUICK_LINKS.filter((l) => !presets || presets.includes(l.preset))
  const socials = SOCIAL_KEYS.filter((key) => settings.socials[key])
  const phone = settings.contact_phone

  return (
    <footer className="site-footer" id="site-footer">
      <div className="site-footer__inner">
        <div className="site-footer__top">
          <div className="site-footer__intro">
            <Link to="/" className="site-footer__brand" aria-label={`${settings.brand_name} home`}>
              <span className="site-footer__name">{name}</span>
              {sub && <span className="site-footer__sub">{sub}</span>}
            </Link>
            {settings.tagline && <p className="site-footer__line">{settings.tagline}</p>}
            {settings.footer_note && <p className="site-footer__note">{settings.footer_note}</p>}
          </div>

          {links.length > 0 && (
            <nav className="site-footer__col" aria-label="Footer">
              <p className="site-footer__label">Explore</p>
              <ul className="site-footer__list">
                {links.map((l) => {
                  const id = HOME_ANCHORS[l.preset]
                  return (
                    <li key={l.preset}>
                      {onHome ? (
                        <a
                          href={`#${id}`}
                          onClick={(e) => {
                            if (scrollToAnchor(id)) e.preventDefault()
                          }}
                        >
                          {l.label}
                        </a>
                      ) : (
                        <Link to={{ pathname: '/', hash: `#${id}` }}>{l.label}</Link>
                      )}
                    </li>
                  )
                })}
              </ul>
            </nav>
          )}

          {settings.address && (
            <div className="site-footer__col">
              <p className="site-footer__label">Office</p>
              <address className="site-footer__address">{settings.address}</address>
            </div>
          )}

          <div className="site-footer__col">
            <p className="site-footer__label">Contact</p>
            <ul className="site-footer__list">
              {settings.contact_email && (
                <li>
                  <a href={`mailto:${settings.contact_email}`}>{settings.contact_email}</a>
                </li>
              )}
              {phone && (
                <li>
                  <a href={`tel:${phone.replace(/\s+/g, '')}`}>{phone}</a>
                </li>
              )}
            </ul>
            {socials.length > 0 && (
              <ul className="site-footer__socials">
                {socials.map((key) => (
                  <li key={key}>
                    <a href={settings.socials[key]} target="_blank" rel="noreferrer">
                      {SOCIAL_LABEL[key]}
                    </a>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>

        <div className="site-footer__base">
          <p>
            {settings.rera_number && <span>RERA Reg. No. {settings.rera_number}</span>}
            <span>
              © {new Date().getFullYear()} {settings.brand_name}
            </span>
          </p>
          <p>
            {settings.demo_note && <span className="site-footer__demo">{settings.demo_note}</span>}
            <a href="https://yniidi.com" target="_blank" rel="noreferrer">
              Powered by YNIIDI
            </a>
          </p>
        </div>
      </div>
    </footer>
  )
}

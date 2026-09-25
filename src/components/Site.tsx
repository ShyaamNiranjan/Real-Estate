import { useEffect, useRef, useState } from 'react'
import { gsap } from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import { copy } from '../content/copy'

gsap.registerPlugin(ScrollTrigger)

export function Site() {
  const rootRef = useRef<HTMLElement>(null)
  const [scrolled, setScrolled] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > window.innerHeight * 0.85)
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  useEffect(() => {
    document.body.classList.toggle('nav-open', menuOpen)
    return () => document.body.classList.remove('nav-open')
  }, [menuOpen])

  useEffect(() => {
    const root = rootRef.current
    if (!root) return

    const ctx = gsap.context(() => {
      gsap.utils.toArray<HTMLElement>('.reveal').forEach((el) => {
        gsap.fromTo(
          el,
          { y: 28, opacity: 0 },
          {
            y: 0,
            opacity: 1,
            duration: 0.9,
            ease: 'power2.out',
            scrollTrigger: {
              trigger: el,
              start: 'top 88%',
              toggleActions: 'play none none reverse',
            },
          },
        )
      })

      gsap.fromTo(
        '.tile',
        { y: 36, opacity: 0 },
        {
          y: 0,
          opacity: 1,
          duration: 0.85,
          stagger: 0.1,
          ease: 'power2.out',
          scrollTrigger: {
            trigger: '.tiles',
            start: 'top 82%',
          },
        },
      )
    }, root)

    return () => ctx.revert()
  }, [])

  const scrollTo = (id: string) => {
    setMenuOpen(false)
    const el = document.getElementById(id)
    // Allow menu close paint before scrolling
    requestAnimationFrame(() => {
      el?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    })
  }

  return (
    <main className="site" ref={rootRef}>
      <header className={`nav ${scrolled || menuOpen ? 'is-solid' : ''}`}>
        <button
          type="button"
          className="nav__brand"
          onClick={() => {
            setMenuOpen(false)
            window.scrollTo({ top: 0, behavior: 'smooth' })
          }}
        >
          {copy.brand.name}
        </button>

        <nav className="nav__links" aria-label="Primary">
          {copy.brand.nav.map((item) => (
            <button
              key={item}
              type="button"
              className="nav__link"
              onClick={() => scrollTo(item.toLowerCase())}
            >
              {item}
            </button>
          ))}
        </nav>

        <button
          type="button"
          className={`nav__toggle ${menuOpen ? 'is-open' : ''}`}
          aria-expanded={menuOpen}
          aria-controls="mobile-nav"
          aria-label={menuOpen ? 'Close menu' : 'Open menu'}
          onClick={() => setMenuOpen((v) => !v)}
        >
          <span />
          <span />
        </button>
      </header>

      <div
        id="mobile-nav"
        className={`nav-drawer ${menuOpen ? 'is-open' : ''}`}
        aria-hidden={!menuOpen}
      >
        <nav className="nav-drawer__links" aria-label="Mobile">
          {copy.brand.nav.map((item) => (
            <button
              key={item}
              type="button"
              className="nav-drawer__link"
              onClick={() => scrollTo(item.toLowerCase())}
            >
              {item}
            </button>
          ))}
        </nav>
      </div>
      {menuOpen && (
        <button
          type="button"
          className="nav-backdrop"
          aria-label="Close menu"
          onClick={() => setMenuOpen(false)}
        />
      )}

      <section className="section section--intro" id="intro">
        <div className="section__inner reveal">
          <p className="eyebrow">{copy.site.intro.eyebrow}</p>
          <h2 className="section__title">{copy.site.intro.title}</h2>
          <p className="section__body">{copy.site.intro.body}</p>
        </div>
      </section>

      <section className="section section--residences" id="residences">
        <div className="section__inner">
          <div className="section__head reveal">
            <p className="eyebrow">Residences</p>
            <h2 className="section__title">Three compositions</h2>
          </div>
          <div className="tiles">
            {copy.site.residences.map((r) => (
              <article className="tile" key={r.name}>
                <div className="tile__media">
                  <img src={r.image} alt="" loading="lazy" />
                </div>
                <div className="tile__body">
                  <h3 className="tile__name">{r.name}</h3>
                  <p className="tile__meta">{r.meta}</p>
                  <p className="tile__blurb">{r.blurb}</p>
                  <p className="tile__price">{r.price}</p>
                </div>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="section section--amenities" id="amenities">
        <div className="section__inner">
          <div className="section__head reveal">
            <p className="eyebrow">Amenities</p>
            <h2 className="section__title">What the house holds</h2>
          </div>
          <div className="amenity-grid">
            {copy.site.amenities.map((a) => (
              <article className="amenity reveal" key={a.title}>
                <h3>{a.title}</h3>
                <p>{a.text}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="section section--location" id="location">
        <div className="location">
          <div
            className="location__visual reveal"
            style={{ backgroundImage: 'url(/frames/frame-07.jpg)' }}
            role="img"
            aria-label="Residence interior looking toward the pool"
          />
          <div className="location__copy reveal">
            <p className="eyebrow">Location</p>
            <h2 className="section__title">{copy.site.location.title}</h2>
            <p className="section__body">{copy.site.location.body}</p>
            <ul className="location__points">
              {copy.site.location.points.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      <section className="section section--enquire" id="enquire">
        <div className="enquire reveal">
          <h2 className="section__title">{copy.site.enquire.title}</h2>
          <p className="section__body">{copy.site.enquire.body}</p>
          <form
            className="enquire__form"
            onSubmit={(e) => {
              e.preventDefault()
            }}
          >
            <label>
              <span>Name</span>
              <input type="text" name="name" autoComplete="name" required />
            </label>
            <label>
              <span>Email</span>
              <input type="email" name="email" autoComplete="email" required />
            </label>
            <label className="enquire__full">
              <span>Message</span>
              <textarea name="message" rows={4} placeholder="Preferred dates, party size…" />
            </label>
            <button type="submit" className="btn">
              {copy.site.enquire.cta}
            </button>
          </form>
          <p className="enquire__note">{copy.site.enquire.note}</p>
        </div>
      </section>

      <footer className="footer">
        <p>{copy.site.footer.line}</p>
      </footer>
    </main>
  )
}

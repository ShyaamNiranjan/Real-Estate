import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { PLANS } from '../lib/prototype'
import { useRealtor } from '../lib/realtor'
import { FrameLoop } from '../public/FrameLoop'
import { YeFooter, YeMark } from './chrome'
import './ye.css'

const LANDSCAPE = { baseUrl: '/media/sequence', pattern: 'frame-{###}.jpg', count: 240 }
const PORTRAIT = { baseUrl: '/media/sequence-portrait-lite', pattern: 'frame-{###}.jpg', count: 120 }

const STEPS = [
  { n: '01', title: 'Film it', body: 'Walk the home slowly with a phone, gimbal or drone. Thirty to ninety seconds is ideal.' },
  { n: '02', title: 'Upload', body: 'Drop the video into YE Studio. It becomes a smooth walkthrough in the background.' },
  { n: '03', title: 'Tell the story', body: 'Add captions at the moments that matter, then pick sections and a style for the page.' },
  { n: '04', title: 'Publish and share', body: 'One link for your bio, your DMs or your website. Every enquiry comes straight to you.' },
]

const FEATURES = [
  { title: 'Scroll walkthroughs', body: 'Buyers move through the home at their own pace. Scroll slowly to linger, quickly to move on, back to look again.' },
  { title: 'Built for phones', body: 'Landscape footage turns sideways on upright phones, or sits between editorial bars. Vertical video plays as is.' },
  { title: 'Your brand, not ours', body: 'Your name, logo, colours and words. Buyers see a premium agency site, never a software badge.' },
  { title: 'Leads go to you', body: 'An enquiry form, your booking link and a WhatsApp button on every home. YE never contacts your buyers.' },
  { title: 'Bring your team', body: 'Invite agents who publish their own listings under one brand, with Owner and Agent roles.' },
  { title: 'Ready for any market', body: 'Local currency, square feet or metres, and the licence fields your country expects.' },
]

const FAQ = [
  {
    q: 'Do I have to replace my current website?',
    a: 'No. Many agents keep their site and point each View Property button at a YE page. Others use YE as their whole website. Both work from the same account.',
  },
  {
    q: 'What do I need to film a walkthrough?',
    a: 'A recent phone is enough. Walk slowly and steadily through the home in one take. A gimbal helps, and drones work well for arrivals.',
  },
  {
    q: 'Can I try it before paying?',
    a: 'Yes. Build one listing for free and walk through it yourself. Only you can see it until you subscribe and publish.',
  },
  {
    q: 'Who owns the leads?',
    a: 'You do. Enquiries go to your inbox, your booking link or your WhatsApp. Your pages only ever show your homes.',
  },
]

export function Landing() {
  const { base, listing } = useRealtor()
  const [scrolled, setScrolled] = useState(false)

  useEffect(() => {
    document.title = 'YE · Listings your buyers can walk through'
    const onScroll = () => setScrolled(window.scrollY > 24)
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  return (
    <div className="ye">
      <header className={`ye-nav ${scrolled ? 'is-scrolled' : ''}`}>
        <div className="ye-nav__inner">
          <Link to="/" className="ye-nav__brand" aria-label="YE home">
            <YeMark />
          </Link>
          <nav className="ye-nav__links" aria-label="Main">
            <a href="#how">How it works</a>
            <a href="#features">Features</a>
            <a href="#pricing">Pricing</a>
            <a href={base}>Example site</a>
          </nav>
          <div className="ye-nav__actions">
            <Link to="/studio" className="ye-nav__signin">
              Sign in
            </Link>
            <Link to="/signup?plan=agent" className="ye-btn ye-btn--primary ye-btn--sm">
              Get started
            </Link>
          </div>
        </div>
      </header>

      <main>
        <section className="ye-hero">
          <div className="ye-hero__glow" aria-hidden />
          <div className="ye-hero__inner">
            <div className="ye-hero__copy">
              <p className="ye-pill">For realtors who sell on Instagram</p>
              <h1 className="ye-hero__title">
                Listings your buyers can <em>walk through.</em>
              </h1>
              <p className="ye-hero__lede">
                YE turns a phone video into a scroll-controlled walkthrough on your own premium website. Share one link in your bio, your
                DMs, or behind the View Property button on the site you already have.
              </p>
              <div className="ye-hero__ctas">
                <Link to="/signup?plan=agent" className="ye-btn ye-btn--primary">
                  Get started
                </Link>
                <Link to="/signup?start=free" className="ye-btn ye-btn--ghost">
                  Try it free <span aria-hidden>→</span>
                </Link>
              </div>
              <p className="ye-hero__note">Free preview: build one listing on your own home. Only you can see it.</p>
            </div>

            <div className="ye-hero__visual">
              <div className="ye-browser">
                <div className="ye-browser__bar">
                  <span className="ye-browser__dots" aria-hidden>
                    <i />
                    <i />
                    <i />
                  </span>
                  <span className="ye-browser__url">ye.yniidi.com/your-name/lakeview-villa</span>
                </div>
                <div className="ye-browser__screen">
                  <FrameLoop source={LANDSCAPE} poster="/media/sequence/frame-001.jpg" />
                  <div className="ye-browser__caption">
                    <span>The threshold</span>
                    <p>Glass, oak and stone. The garden follows you in.</p>
                  </div>
                </div>
              </div>
              <div className="ye-phone" aria-hidden>
                <div className="ye-phone__screen">
                  <FrameLoop source={PORTRAIT} poster="/media/sequence-portrait-lite/frame-001.jpg" />
                </div>
              </div>
              <div className="ye-float ye-float--lead" aria-hidden>
                <span className="ye-float__dot" />
                <div>
                  <strong>New enquiry · Lakeview Villa</strong>
                  <small>Booked a viewing for Saturday</small>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section className="ye-ways" aria-labelledby="ways-title">
          <div className="ye-wrap">
            <p className="ye-eyebrow">Two ways to use YE</p>
            <h2 id="ways-title" className="ye-h2">
              Your whole website, or just the homes that need to <em>move.</em>
            </h2>
            <div className="ye-ways__grid">
              <article className="ye-card ye-way">
                <code className="ye-way__url">ye.yniidi.com/your-name</code>
                <h3>Your agency website</h3>
                <p>A complete site with your brand, your homes, services, neighbourhoods, testimonials and enquiries. Ready the day you sign up.</p>
                <a href={base} className="ye-link">
                  See an example site →
                </a>
              </article>
              <article className="ye-card ye-way">
                <code className="ye-way__url">ye.yniidi.com/your-name/lakeview-villa</code>
                <h3>Property pages, anywhere</h3>
                <p>Keep the website you have. Point any View Property button, bio link or DM at a page buyers can walk through.</p>
                <a href={listing('aurelia')} className="ye-link">
                  Walk through an example →
                </a>
              </article>
            </div>
          </div>
        </section>

        <section className="ye-how" id="how" aria-labelledby="how-title">
          <div className="ye-wrap">
            <p className="ye-eyebrow">How it works</p>
            <h2 id="how-title" className="ye-h2">
              From a phone video to a live walkthrough, <em>the same day.</em>
            </h2>
            <ol className="ye-steps">
              {STEPS.map((s) => (
                <li key={s.n} className="ye-step">
                  <span className="ye-step__n">{s.n}</span>
                  <h3>{s.title}</h3>
                  <p>{s.body}</p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        <section className="ye-showcase" aria-labelledby="showcase-title">
          <div className="ye-showcase__media" aria-hidden>
            <FrameLoop source={LANDSCAPE} poster="/media/sequence/frame-110.jpg" />
          </div>
          <div className="ye-showcase__veil" aria-hidden />
          <div className="ye-wrap ye-showcase__copy">
            <p className="ye-eyebrow">The buyer experience</p>
            <h2 id="showcase-title" className="ye-h2">
              The scroll is the <em>camera.</em>
            </h2>
            <p>
              Arrive at the gate, cross the threshold, find the light at the back of the house. Then enquire, having already seen every room.
            </p>
            <a href={listing('aurelia')} className="ye-btn ye-btn--light">
              Try the walkthrough
            </a>
          </div>
        </section>

        <section className="ye-features" id="features" aria-labelledby="features-title">
          <div className="ye-wrap">
            <p className="ye-eyebrow">Features</p>
            <h2 id="features-title" className="ye-h2">
              Everything a listing needs. <em>Nothing it doesn't.</em>
            </h2>
            <div className="ye-features__grid">
              {FEATURES.map((f, i) => (
                <article key={f.title} className="ye-feature">
                  <span className="ye-feature__n">{String(i + 1).padStart(2, '0')}</span>
                  <h3>{f.title}</h3>
                  <p>{f.body}</p>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section className="ye-pricing" id="pricing" aria-labelledby="pricing-title">
          <div className="ye-wrap">
            <p className="ye-eyebrow">Pricing</p>
            <h2 id="pricing-title" className="ye-h2">
              Simple plans. <em>Start free.</em>
            </h2>
            <p className="ye-sub">Prices are placeholders while pricing is finalised.</p>
            <div className="ye-plans">
              {PLANS.map((p) => (
                <article key={p.key} className={`ye-plan ${p.key === 'team' ? 'is-featured' : ''}`}>
                  {p.key === 'team' && <span className="ye-plan__tag">Most teams</span>}
                  <h3>{p.name}</h3>
                  <p className="ye-plan__price">
                    {p.price}
                    {p.price !== 'Custom' && <small>/month</small>}
                  </p>
                  <p className="ye-plan__blurb">{p.blurb}</p>
                  <ul>
                    <li>
                      {p.seats === 1 ? '1 user' : `Up to ${p.seats} users`} · {p.listings}
                    </li>
                    {p.features.map((f) => (
                      <li key={f}>{f}</li>
                    ))}
                  </ul>
                  <Link to={`/signup?plan=${p.key}`} className={`ye-btn ${p.key === 'team' ? 'ye-btn--primary' : 'ye-btn--ghost'} ye-btn--block`}>
                    {p.key === 'brokerage' ? 'Talk to us' : `Choose ${p.name}`}
                  </Link>
                </article>
              ))}
            </div>
            <div className="ye-freebar">
              <div>
                <strong>Not sure yet?</strong> Build one listing free and walk through it yourself before you pay.
              </div>
              <Link to="/signup?start=free" className="ye-link">
                Try it free →
              </Link>
            </div>
          </div>
        </section>

        <section className="ye-faq" aria-labelledby="faq-title">
          <div className="ye-wrap ye-faq__inner">
            <div>
              <p className="ye-eyebrow">Questions</p>
              <h2 id="faq-title" className="ye-h2">
                Good to <em>know.</em>
              </h2>
            </div>
            <div className="ye-faq__list">
              {FAQ.map((f) => (
                <details key={f.q} className="ye-faq__item">
                  <summary>{f.q}</summary>
                  <p>{f.a}</p>
                </details>
              ))}
            </div>
          </div>
        </section>

        <section className="ye-final" aria-labelledby="final-title">
          <div className="ye-wrap ye-final__inner">
            <h2 id="final-title" className="ye-h2">
              Your next listing could be <em>walkable</em> by tonight.
            </h2>
            <div className="ye-hero__ctas">
              <Link to="/signup?plan=agent" className="ye-btn ye-btn--primary">
                Get started
              </Link>
              <Link to="/signup?start=free" className="ye-btn ye-btn--ghost">
                Try it free <span aria-hidden>→</span>
              </Link>
            </div>
          </div>
        </section>
      </main>

      <YeFooter />
    </div>
  )
}

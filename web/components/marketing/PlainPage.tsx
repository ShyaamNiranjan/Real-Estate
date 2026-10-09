import Link from 'next/link'
import type { ReactNode } from 'react'
import { YeFooter, YeMark } from './chrome'

/** Simple branded page for legal placeholders and errors. */
export function PlainPage({ eyebrow, title, children }: { eyebrow: string; title: ReactNode; children: ReactNode }) {
  return (
    <div className="ye ye-plain">
      <header className="ye-plain__head">
        <Link href="/" aria-label="Scrollwalk home">
          <YeMark />
        </Link>
      </header>
      <main id="main" className="ye-plain__main">
        <p className="ye-eyebrow">{eyebrow}</p>
        <h1 className="ye-h2">{title}</h1>
        {children}
      </main>
      <YeFooter />
    </div>
  )
}

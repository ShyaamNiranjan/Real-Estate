import Link from 'next/link'
import type { ReactNode } from 'react'
import { YeMark } from '@/components/marketing/chrome'
import { FrameLoop } from '@/components/marketing/FrameLoop'

const PORTRAIT = { baseUrl: '/media/loop-portrait', count: 40 }

/** The split sign-in layout from the prototype's Signup screen (src/ye/Signup.tsx). */
export function AuthShell({ children }: { children: ReactNode }) {
  return (
    <div className="ye ye-signup">
      <div className="ye-signup__panel">
        <Link href="/" className="ye-signup__brand" aria-label="Scrollwalk home">
          <YeMark />
        </Link>
        <main id="main" className="ye-signup__main">
          {children}
        </main>
      </div>

      <aside className="ye-signup__art" aria-hidden>
        <div className="ye-signup__phone">
          <FrameLoop source={PORTRAIT} poster="/media/loop-portrait/01.jpg" />
        </div>
        <blockquote>
          “Buyers walked the whole house before they called. The viewing was just to confirm.”
          <cite>What we want every agent to say</cite>
        </blockquote>
      </aside>
    </div>
  )
}

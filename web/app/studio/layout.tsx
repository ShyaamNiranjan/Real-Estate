import type { Metadata } from 'next'
import { StudioShell } from '@/components/studio/StudioShell'
import '@/styles/studio-admin.css'
import '@/styles/studio-motion.css'
import '@/styles/studio.css'

export const metadata: Metadata = {
  title: { default: 'Studio', template: '%s · Studio · Scrollwalk' },
  robots: { index: false, follow: false },
}

export default function StudioLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="admin">
      <StudioShell>{children}</StudioShell>
    </div>
  )
}

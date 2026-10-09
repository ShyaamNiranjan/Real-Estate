import type { Metadata } from 'next'
import '@/styles/studio.css'
import { StudioHome } from './StudioHome'

export const metadata: Metadata = {
  title: 'Studio',
  robots: { index: false, follow: false },
}

export default function StudioPage() {
  return (
    <div className="admin">
      <StudioHome />
    </div>
  )
}

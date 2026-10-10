import type { Metadata } from 'next'
import { StudioIndex } from './Dashboard'

export const metadata: Metadata = { title: 'Dashboard' }

export default function StudioPage() {
  return <StudioIndex />
}

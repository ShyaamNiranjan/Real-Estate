import type { Metadata } from 'next'
import { ComingSoon } from '@/components/studio/ui'

export const metadata: Metadata = { title: 'Listings' }

export default function Page() {
  return <ComingSoon title="Listings">Creating and editing listings arrives in the next Studio update.</ComingSoon>
}

import type { Metadata } from 'next'
import { PlainPage } from '@/components/marketing/PlainPage'

export const metadata: Metadata = {
  title: 'Privacy Policy',
  robots: { index: false },
}

// Placeholder until the reviewed Privacy Policy is published (docs/SCOPE.md §13).
export default function PrivacyPage() {
  return (
    <PlainPage eyebrow="Legal" title="Privacy Policy">
      <p>Our Privacy Policy is being finalised and will be published here before launch.</p>
      <p>
        Questions in the meantime? Write to <a href="mailto:hello@scrollwalk.com">hello@scrollwalk.com</a>.
      </p>
    </PlainPage>
  )
}

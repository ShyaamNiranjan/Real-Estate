import type { Metadata } from 'next'
import { PlainPage } from '@/components/marketing/PlainPage'

export const metadata: Metadata = {
  title: 'Terms of Service',
  robots: { index: false },
}

// Placeholder until the reviewed Terms are published (docs/SCOPE.md §13).
export default function TermsPage() {
  return (
    <PlainPage eyebrow="Legal" title="Terms of Service">
      <p>Our Terms of Service are being finalised and will be published here before launch.</p>
      <p>
        Questions in the meantime? Write to <a href="mailto:hello@scrollwalk.com">hello@scrollwalk.com</a>.
      </p>
    </PlainPage>
  )
}

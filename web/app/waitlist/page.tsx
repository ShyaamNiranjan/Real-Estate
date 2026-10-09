import type { Metadata } from 'next'
import { AuthShell } from '@/components/auth/AuthShell'
import { WaitlistForm } from '@/components/marketing/WaitlistForm'

export const metadata: Metadata = {
  title: 'Join the waitlist',
  description: 'Scrollwalk is opening to a small group of agents first. Join the waitlist for early access.',
}

export default function WaitlistPage() {
  return (
    <AuthShell>
      <div className="ye-form ye-waitlist-page">
        <p className="ye-eyebrow">Early access</p>
        <h1 className="ye-signup__title">Be first through the door.</h1>
        <p className="ye-signup__lede">
          Homes your buyers can walk through, on your own premium website. We&rsquo;re opening Scrollwalk to a small group of agents first.
        </p>
        <WaitlistForm headingLevel="h2" />
      </div>
    </AuthShell>
  )
}

import type { Metadata } from 'next'
import { AuthShell } from '@/components/auth/AuthShell'
import { SignupFlow } from './SignupFlow'

export const metadata: Metadata = {
  title: 'Create your account',
  robots: { index: false },
}

export default async function SignupPage({ searchParams }: PageProps<'/signup'>) {
  const params = await searchParams
  const plan = typeof params.plan === 'string' ? params.plan : null
  const free = params.start === 'free'
  return (
    <AuthShell>
      <SignupFlow key={free ? 'free' : (plan ?? 'agent')} plan={plan} free={free} />
    </AuthShell>
  )
}

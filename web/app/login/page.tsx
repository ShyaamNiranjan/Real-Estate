import type { Metadata } from 'next'
import { AuthShell } from '@/components/auth/AuthShell'
import { LoginFlow } from './LoginFlow'

export const metadata: Metadata = {
  title: 'Sign in',
  robots: { index: false },
}

export default async function LoginPage({ searchParams }: PageProps<'/login'>) {
  const params = await searchParams
  const error = typeof params.error === 'string' ? params.error : null
  const next = typeof params.next === 'string' ? params.next : null
  return (
    <AuthShell>
      <LoginFlow googleError={error} next={next} />
    </AuthShell>
  )
}

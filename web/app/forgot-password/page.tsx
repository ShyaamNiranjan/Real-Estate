import type { Metadata } from 'next'
import { AuthShell } from '@/components/auth/AuthShell'
import { ForgotFlow } from './ForgotFlow'

export const metadata: Metadata = {
  title: 'Reset your password',
  robots: { index: false },
}

export default function ForgotPasswordPage() {
  return (
    <AuthShell>
      <ForgotFlow />
    </AuthShell>
  )
}

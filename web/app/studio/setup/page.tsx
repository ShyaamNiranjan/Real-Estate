import type { Metadata } from 'next'
import { SetupPage } from './SetupPage'

export const metadata: Metadata = { title: 'Set up' }

export default function Page() {
  return <SetupPage />
}

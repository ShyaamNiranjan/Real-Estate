'use client'

import { useRouter } from 'next/navigation'
import { useEffect } from 'react'
import { useSession } from '@/lib/session'

/** Sign-in screens send people who already have a session straight to the Studio. */
export function useSignedInRedirect(to = '/studio') {
  const { status } = useSession()
  const router = useRouter()
  useEffect(() => {
    if (status === 'signed-in') router.replace(to)
  }, [status, router, to])
}

'use client'

import { useSearchParams } from 'next/navigation'
import { ComingSoon } from '@/components/studio/ui'
import { useWorkspace, type SetupStepKey } from '@/lib/studio'
import { SetupGuide, STEP_TITLES } from '../SetupGuide'

export function SetupPage() {
  const { can } = useWorkspace()
  const step = useSearchParams().get('step')
  if (!can('site.edit_brand')) return <ComingSoon title="Set up">Your Admin sets up this workspace.</ComingSoon>
  return <SetupGuide start={step && step in STEP_TITLES ? (step as SetupStepKey) : null} />
}

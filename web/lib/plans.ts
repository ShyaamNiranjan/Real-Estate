export type PlanKey = 'agent' | 'team' | 'brokerage'

/**
 * Marketing copy for the plan cards. Limits follow docs/SCOPE.md §11 (placeholders, editable in
 * Super-Admin later); `price: null` means "not announced yet". Replace with `/billing/plans` when it exists.
 */
export const PLANS: {
  key: PlanKey
  name: string
  price: string | null
  blurb: string
  seats: number
  listings: string
  features: string[]
}[] = [
  {
    key: 'agent',
    name: 'Agent',
    price: null,
    blurb: 'For solo agents who want every listing to be walkable.',
    seats: 1,
    listings: 'Up to 15 active listings',
    features: ['Your agency website', 'Scroll walkthroughs', 'Enquiries, booking link and WhatsApp', 'Style presets'],
  },
  {
    key: 'team',
    name: 'Team',
    price: null,
    blurb: 'For teams sharing one brand and one inventory.',
    seats: 10,
    listings: 'Up to 50 active listings',
    features: ['Everything in Agent', 'Up to 10 team members', 'Custom roles and permissions', 'Listings by agent'],
  },
  {
    key: 'brokerage',
    name: 'Brokerage',
    price: 'Custom',
    blurb: 'For multi-office brokerages and white-label needs.',
    seats: 50,
    listings: 'Unlimited listings',
    features: ['Everything in Team', 'Dedicated onboarding', 'Priority support', 'Custom domain (after launch)'],
  },
]

export function planByKey(key: string | null | undefined) {
  return PLANS.find((p) => p.key === key) ?? null
}

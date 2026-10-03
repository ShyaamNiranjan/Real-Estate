import { useSyncExternalStore } from 'react'

/**
 * Internal prototype state. YE's real accounts, plans and billing do not exist yet, so the
 * signup flow, plan, country and setup progress are simulated in this browser only.
 */

export type Plan = 'free' | 'agent' | 'team' | 'brokerage'
export type StepKey = 'details' | 'property' | 'contact' | 'style' | 'team'

export type TeamMember = { name: string; email: string; role: 'Owner' | 'Agent' }

export type ProtoState = {
  plan: Plan
  country: string
  ownerName: string
  done: StepKey[]
  skipped: StepKey[]
  sitePublished: boolean
  complianceAck: boolean
  guideHidden: boolean
  team: TeamMember[]
}

const KEY = 'ye:prototype'

const DEFAULT: ProtoState = {
  plan: 'agent',
  country: 'US',
  ownerName: '',
  done: [],
  skipped: [],
  sitePublished: false,
  complianceAck: false,
  guideHidden: false,
  team: [],
}

let state: ProtoState = read()
const listeners = new Set<() => void>()

function read(): ProtoState {
  try {
    const raw = localStorage.getItem(KEY)
    return raw ? { ...DEFAULT, ...(JSON.parse(raw) as Partial<ProtoState>) } : DEFAULT
  } catch {
    return DEFAULT
  }
}

function commit(next: ProtoState) {
  state = next
  try {
    localStorage.setItem(KEY, JSON.stringify(next))
  } catch {
    // Private mode: the prototype still works for this tab.
  }
  listeners.forEach((l) => l())
}

export function setProto(patch: Partial<ProtoState>) {
  commit({ ...state, ...patch })
}

export function getProto() {
  return state
}

export function markDone(step: StepKey) {
  if (state.done.includes(step)) return
  commit({ ...state, done: [...state.done, step], skipped: state.skipped.filter((s) => s !== step) })
}

export function skipStep(step: StepKey) {
  if (state.skipped.includes(step)) return
  commit({ ...state, skipped: [...state.skipped, step] })
}

export function resumeStep(step: StepKey) {
  commit({ ...state, skipped: state.skipped.filter((s) => s !== step) })
}

export function resetProto(patch: Partial<ProtoState> = {}) {
  commit({ ...DEFAULT, ...patch })
}

export function useProto() {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb)
      return () => listeners.delete(cb)
    },
    () => state,
  )
}

export const PLANS: {
  key: Exclude<Plan, 'free'>
  name: string
  price: string
  blurb: string
  seats: number
  listings: string
  features: string[]
}[] = [
  {
    key: 'agent',
    name: 'Agent',
    price: '$—',
    blurb: 'For solo agents who want every listing to be walkable.',
    seats: 1,
    listings: 'Up to 15 active listings',
    features: ['Your agency website', 'Scroll walkthroughs', 'Enquiries, booking link and WhatsApp', 'Style presets'],
  },
  {
    key: 'team',
    name: 'Team',
    price: '$—',
    blurb: 'For teams sharing one brand and one inventory.',
    seats: 10,
    listings: 'Up to 50 active listings',
    features: ['Everything in Agent', 'Up to 10 team members', 'Owner and Agent roles', 'Listings by agent'],
  },
  {
    key: 'brokerage',
    name: 'Brokerage',
    price: 'Custom',
    blurb: 'For multi-office brokerages and white-label needs.',
    seats: 50,
    listings: 'Unlimited listings',
    features: ['Everything in Team', 'Custom domain', 'Dedicated onboarding', 'Priority support'],
  },
]

export function planName(plan: Plan) {
  return plan === 'free' ? 'Free preview' : (PLANS.find((p) => p.key === plan)?.name ?? plan)
}

export function seatLimit(plan: Plan) {
  return plan === 'free' ? 1 : (PLANS.find((p) => p.key === plan)?.seats ?? 1)
}

export type Country = {
  code: string
  name: string
  licenceLabel: string
  licenceShort: string
  hint: string
  equalHousing?: boolean
}

export const COUNTRIES: Country[] = [
  {
    code: 'US',
    name: 'United States',
    licenceLabel: 'Real estate licence number',
    licenceShort: 'Lic. #',
    hint: 'Usually required on agent websites in the US, with your brokerage name.',
    equalHousing: true,
  },
  {
    code: 'GB',
    name: 'United Kingdom',
    licenceLabel: 'Redress scheme membership',
    licenceShort: 'Redress scheme',
    hint: 'UK agents must belong to a redress scheme such as The Property Ombudsman.',
  },
  {
    code: 'AE',
    name: 'United Arab Emirates',
    licenceLabel: 'Broker registration number (BRN / ORN)',
    licenceShort: 'BRN',
    hint: 'Dubai also requires a permit number on every property advert.',
  },
  {
    code: 'IN',
    name: 'India',
    licenceLabel: 'RERA registration number',
    licenceShort: 'RERA Reg. No.',
    hint: 'Required by RERA in most states.',
  },
  {
    code: 'CA',
    name: 'Canada',
    licenceLabel: 'Licence or registration number',
    licenceShort: 'Reg. #',
    hint: 'Often required by your provincial regulator.',
  },
  {
    code: 'AU',
    name: 'Australia',
    licenceLabel: 'Licence number',
    licenceShort: 'Lic. #',
    hint: 'Required in most states and territories.',
  },
  {
    code: 'OTHER',
    name: 'Another country',
    licenceLabel: 'Licence or registration number',
    licenceShort: 'Reg. #',
    hint: 'Optional. Add it if your local rules require it.',
  },
]

export function countryInfo(code: string) {
  return COUNTRIES.find((c) => c.code === code) ?? COUNTRIES[COUNTRIES.length - 1]
}

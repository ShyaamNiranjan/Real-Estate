import { api } from './client'
import { unwrap } from './errors'
import type { components } from './schema'

export type WaitlistInput = components['schemas']['WaitlistIn']
export type WaitlistJoined = components['schemas']['Joined']

/** `POST /api/v1/waitlist` → always `202 {status: "joined"}`, so the list can't be probed. */
export function joinWaitlist(input: WaitlistInput): Promise<WaitlistJoined> {
  return unwrap(api.POST('/api/v1/waitlist', { body: input }))
}

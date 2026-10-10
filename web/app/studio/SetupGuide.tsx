'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useRef, useState, type FormEvent } from 'react'
import {
  ABOUT_KEYS,
  AboutFields,
  CONTACT_KEYS,
  ContactFields,
  STYLE_PRESETS,
  StylePicker,
  UsernameClaim,
  suggestUsername,
  useComplianceProfiles,
  useProfileDraft,
} from '@/components/studio/profile'
import { InviteForm } from '@/components/studio/InviteForm'
import { ErrorAlert } from '@/components/studio/ui'
import { api } from '@/lib/api/client'
import { unwrap, type ApiError } from '@/lib/api/errors'
import { useWorkspace, type SetupStepKey, type Workspace } from '@/lib/studio'

export const STEP_TITLES: Record<SetupStepKey, string> = {
  about_you: 'About you',
  contact: 'How buyers reach you',
  style: 'Your style',
  team: 'Invite your team',
}

export function guideSteps(teamPlan: boolean): SetupStepKey[] {
  return teamPlan ? ['about_you', 'contact', 'style', 'team'] : ['about_you', 'contact', 'style']
}

/** First step with neither done nor skipped, or null when every step has an answer. */
export function nextStep(ws: Workspace, teamPlan: boolean): SetupStepKey | null {
  return guideSteps(teamPlan).find((s) => !ws.setup[s]) ?? null
}

/** One big tile at a time. Continue saves the tile and marks it done; Skip marks it skipped. */
export function SetupGuide({ start }: { start?: SetupStepKey | null }) {
  const { workspace, teamPlan, setWorkspace, noteError, toast } = useWorkspace()
  const router = useRouter()
  const steps = guideSteps(teamPlan)
  const [step, setStep] = useState<SetupStepKey>(() => (start && steps.includes(start) ? start : (nextStep(workspace, teamPlan) ?? steps[0])))
  const [stepError, setStepError] = useState<ApiError | null>(null)
  const [marking, setMarking] = useState(false)
  const profile = useProfileDraft()
  const profiles = useComplianceProfiles()
  const headingRef = useRef<HTMLHeadingElement>(null)
  const index = steps.indexOf(step)

  const advance = (ws: Workspace) => {
    const after = steps.slice(index + 1).find((s) => !ws.setup[s]) ?? steps[index + 1]
    if (!after) {
      toast('Setup saved')
      router.push('/studio')
      return
    }
    setStep(after)
    requestAnimationFrame(() => headingRef.current?.focus())
  }

  const mark = async (status: 'done' | 'skipped') => {
    setMarking(true)
    setStepError(null)
    try {
      const ws = await unwrap(api.POST('/api/v1/workspace/setup', { body: { step, status } }))
      setWorkspace(ws)
      advance(ws)
    } catch (err) {
      setStepError(noteError(err))
    } finally {
      setMarking(false)
    }
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (step === 'about_you') {
      if (!(await profile.save(ABOUT_KEYS))) return
    } else if (step === 'contact') {
      if (!(await profile.save(CONTACT_KEYS))) return
    } else if (step === 'style') {
      if (!(await profile.save(['style_preset']))) return
    }
    await mark('done')
  }

  const busy = profile.busy || marking
  const preset = STYLE_PRESETS.find((s) => s.key === profile.draft.style_preset) ?? STYLE_PRESETS[0]

  return (
    <div className="a-page a-guide">
      <div className="a-guide__progress">
        <ol aria-hidden>
          {steps.map((s, i) => (
            <li key={s} className={i === index ? 'is-current' : workspace.setup[s] ? 'is-done' : ''} />
          ))}
        </ol>
        <span className="a-num">
          Step {index + 1} of {steps.length}
        </span>
        <Link href="/studio?dashboard=1" className="a-link a-link--muted" style={{ marginLeft: 'auto' }}>
          Go to the dashboard
        </Link>
      </div>

      <form className="a-card" key={step} onSubmit={submit} noValidate aria-labelledby="guide-title">
        <p className="a-eyebrow">Set up your workspace</p>
        <h1 id="guide-title" ref={headingRef} tabIndex={-1} className="a-title a-title--sm">
          {STEP_TITLES[step]}
        </h1>

        {step === 'about_you' && (
          <>
            <p className="a-muted">Your name and the details your country requires on listings. About a minute.</p>
            <div className="a-guide__grid">
              <AboutFields draft={profile.draft} set={profile.set} errors={profile.errors} profiles={profiles} team={workspace.kind === 'team'} />
              {workspace.username ? (
                <p className="a-field--wide a-muted">
                  Your link: <strong className="a-num">scrollwalk.com/{workspace.username}</strong>
                </p>
              ) : workspace.can_claim_username ? (
                <UsernameClaim
                  suggested={suggestUsername(profile.draft.display_name)}
                  onClaimed={(ws) => {
                    setWorkspace(ws)
                    toast(`scrollwalk.com/${ws.username} is yours`)
                  }}
                />
              ) : (
                <p className="a-field--wide a-muted">You’ll choose your scrollwalk.com link when you subscribe.</p>
              )}
            </div>
          </>
        )}

        {step === 'contact' && (
          <>
            <p className="a-muted">Add at least one way for buyers to reach you. You need one to publish.</p>
            <div className="a-guide__grid">
              <ContactFields draft={profile.draft} set={profile.set} errors={profile.errors} />
            </div>
          </>
        )}

        {step === 'style' && (
          <>
            <p className="a-muted">Pick a look for your site. Skip it and you get Noir, which already looks finished.</p>
            <div className="a-guide__grid">
              <StylePicker value={profile.draft.style_preset} onChange={(v) => profile.set('style_preset', v)} error={profile.errors.style_preset} />
              <div className="a-field--wide" aria-hidden>
                <div className="a-check" style={{ background: preset.background, color: preset.accent, display: 'grid', gap: 4 }}>
                  <span style={{ fontFamily: 'var(--font-display)', fontSize: '1.5rem' }}>{profile.draft.display_name || 'Your name'}</span>
                  <span style={{ color: preset.accent, opacity: 0.7, fontSize: '0.78rem' }}>Homes you can walk through</span>
                  <span style={{ width: 90, height: 6, borderRadius: 3, background: preset.primary }} />
                </div>
              </div>
            </div>
          </>
        )}

        {step === 'team' && (
          <>
            <p className="a-muted">Invite agents who publish listings under your brand. You can do this later from the Team page.</p>
            <InviteForm />
          </>
        )}

        <ErrorAlert error={profile.failure ?? stepError} />

        <div className="a-guide__foot">
          <div className="a-actions" style={{ marginTop: 0 }}>
            {index > 0 && (
              <button type="button" className="a-btn a-btn--ghost" onClick={() => setStep(steps[index - 1])}>
                Back
              </button>
            )}
          </div>
          <div className="a-actions" style={{ marginTop: 0 }}>
            <button type="button" className="a-link a-link--muted" disabled={busy} onClick={() => void mark('skipped')}>
              Skip for now
            </button>
            <button type="submit" className="a-btn a-btn--primary" disabled={busy}>
              {busy ? 'Saving…' : index === steps.length - 1 ? 'Finish' : 'Continue'}
            </button>
          </div>
        </div>
      </form>
    </div>
  )
}

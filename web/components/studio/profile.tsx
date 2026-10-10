'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '@/lib/api/client'
import { asApiError, unwrap, type ApiError } from '@/lib/api/errors'
import type { components } from '@/lib/api/schema'
import { useStudio, type Workspace } from '@/lib/studio'
import { Dialog, ErrorAlert, Field } from './ui'

type ProfilePatch = components['schemas']['ProfilePatch']
type Profiles = components['schemas']['ComplianceProfiles']
type Profile = components['schemas']['Profile']
export type StylePreset = NonNullable<ProfilePatch['style_preset']>

export type Draft = {
  display_name: string
  brokerage_name: string
  country_code: string
  compliance: Record<string, string>
  contact_email: string
  contact_phone: string
  whatsapp: string
  booking_url: string
  style_preset: StylePreset
  tagline: string
  bio: string
}

export const ABOUT_KEYS = ['display_name', 'brokerage_name', 'country_code', 'compliance'] as const
export const CONTACT_KEYS = ['contact_email', 'contact_phone', 'whatsapp', 'booking_url'] as const
export const SITE_KEYS = ['tagline', 'bio'] as const

export const STYLE_PRESETS: { key: StylePreset; name: string; mood: string; primary: string; accent: string; background: string }[] = [
  { key: 'noir', name: 'Noir', mood: 'Charcoal, champagne gold', primary: '#c4a574', accent: '#0c0e0d', background: '#f5f0e8' },
  { key: 'coastal', name: 'Coastal', mood: 'Deep sea, sand', primary: '#9fb8c4', accent: '#0f1c24', background: '#eef1f0' },
  { key: 'terracotta', name: 'Terracotta', mood: 'Warm clay, linen', primary: '#c9845e', accent: '#1d1714', background: '#f4ece4' },
  { key: 'evergreen', name: 'Evergreen', mood: 'Forest, sage', primary: '#a8b88f', accent: '#111915', background: '#eef0e9' },
]

/** Countries offered besides the ones with their own compliance profile and the EU. */
const OTHER_COUNTRIES = 'AR BR CH CL CO EG HK ID IL JP KE KR MA MX MY NG NO NZ PH PK QA SA SG TH TR TW UY VN ZA'.split(' ')

export function draftFrom(ws: Workspace): Draft {
  const p = ws.profile
  return {
    display_name: ws.display_name,
    brokerage_name: p.brokerage_name,
    country_code: ws.country_code ?? '',
    compliance: { ...p.compliance },
    contact_email: p.contact_email ?? '',
    contact_phone: p.contact_phone ?? '',
    whatsapp: p.whatsapp ?? '',
    booking_url: p.booking_url ?? '',
    style_preset: (STYLE_PRESETS.some((s) => s.key === p.style_preset) ? p.style_preset : 'noir') as StylePreset,
    tagline: p.tagline,
    bio: p.bio,
  }
}

export function patchFor(draft: Draft, keys: readonly (keyof Draft)[]): ProfilePatch {
  const patch: ProfilePatch = {}
  for (const key of keys) {
    const value = draft[key]
    if (key === 'country_code') {
      if (value) patch.country_code = value as string
    } else if (key === 'compliance') patch.compliance = value as Record<string, string>
    else if (key === 'style_preset') patch.style_preset = value as StylePreset
    else (patch as Record<string, unknown>)[key] = typeof value === 'string' ? value.trim() : value
  }
  return patch
}

/** Mirrors the API's `profile_for_country`. */
export function profileFor(profiles: Profiles | null, country: string): Profile | null {
  if (!profiles || !country) return null
  const code = country.toUpperCase()
  const byKey = (k: string) => profiles.profiles.find((p) => p.key === k) ?? null
  if (code !== 'EU' && code !== 'OTHER' && byKey(code)) return byKey(code)
  return byKey(profiles.eu_countries.includes(code) ? 'EU' : 'OTHER')
}

export function useComplianceProfiles() {
  const [profiles, setProfiles] = useState<Profiles | null>(null)
  useEffect(() => {
    let cancelled = false
    api
      .GET('/api/v1/workspace/compliance-profiles')
      .then(({ data }) => {
        if (!cancelled && data) setProfiles(data)
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [])
  return profiles
}

/** Draft state for profile fields plus a save that sends only the given keys. */
export function useProfileDraft() {
  const { workspace, setWorkspace, noteError } = useStudio()
  const [draft, setDraft] = useState<Draft>(() => draftFrom(workspace!))
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [failure, setFailure] = useState<ApiError | null>(null)
  const [busy, setBusy] = useState(false)

  const set = useCallback(<K extends keyof Draft>(key: K, value: Draft[K]) => {
    setDraft((d) => ({ ...d, [key]: value }))
    setErrors((e) => {
      if (!(key in e)) return e
      const next = { ...e }
      delete next[key]
      return next
    })
  }, [])

  const save = useCallback(
    async (keys: readonly (keyof Draft)[]) => {
      setBusy(true)
      setErrors({})
      setFailure(null)
      try {
        const ws = await unwrap(api.PATCH('/api/v1/workspace/profile', { body: patchFor(draft, keys) }))
        setWorkspace(ws)
        return ws
      } catch (err) {
        const e = noteError(err)
        setErrors(e.fields)
        // Field errors appear next to their inputs; anything else (or a field we don't show) goes on top.
        const shown = Object.keys(e.fields).filter((k) => k in draft || k.startsWith('compliance'))
        if (!shown.length) setFailure(e)
        return null
      } finally {
        setBusy(false)
      }
    },
    [draft, setWorkspace, noteError],
  )

  return { draft, set, errors, failure, busy, save, setDraft }
}

type FormProps = {
  draft: Draft
  set: <K extends keyof Draft>(key: K, value: Draft[K]) => void
  errors: Record<string, string>
}

export function AboutFields({ draft, set, errors, profiles, team }: FormProps & { profiles: Profiles | null; team?: boolean }) {
  const names = useMemo(() => {
    try {
      return new Intl.DisplayNames(['en'], { type: 'region' })
    } catch {
      return null
    }
  }, [])
  const label = useCallback((code: string) => names?.of(code) ?? code, [names])
  const own = (profiles?.profiles ?? []).filter((p) => p.key !== 'EU' && p.key !== 'OTHER')
  const eu = [...(profiles?.eu_countries ?? [])].sort((a, b) => label(a).localeCompare(label(b)))
  const rest = OTHER_COUNTRIES.filter((c) => !own.some((p) => p.key === c)).sort((a, b) => label(a).localeCompare(label(b)))
  const known = own.some((p) => p.key === draft.country_code) || eu.includes(draft.country_code) || rest.includes(draft.country_code)
  const profile = profileFor(profiles, draft.country_code)
  const fields = (profile?.fields ?? []).filter((f) => f.scope === 'workspace')

  return (
    <>
      <Field
        label={team ? 'Team or brokerage name' : 'Display name'}
        hint="Shown on your site and listings. You can change it any time."
        error={errors.display_name}
      >
        {(a) => (
          <input
            {...a}
            className="a-input"
            autoComplete="name"
            maxLength={120}
            value={draft.display_name}
            onChange={(e) => set('display_name', e.target.value)}
          />
        )}
      </Field>
      <Field label="Brokerage" optional error={errors.brokerage_name}>
        {(a) => (
          <input
            {...a}
            className="a-input"
            autoComplete="organization"
            value={draft.brokerage_name}
            onChange={(e) => set('brokerage_name', e.target.value)}
          />
        )}
      </Field>
      <Field label="Country" hint="Sets your currency, units and which licence details we ask for." error={errors.country_code}>
        {(a) => (
          <select {...a} className="a-input" value={draft.country_code} onChange={(e) => set('country_code', e.target.value)}>
            <option value="" disabled>
              Choose your country
            </option>
            {draft.country_code && !known && <option value={draft.country_code}>{label(draft.country_code)}</option>}
            <optgroup label="Popular">
              {own.map((p) => (
                <option key={p.key} value={p.key}>
                  {p.name}
                </option>
              ))}
            </optgroup>
            <optgroup label="European Union">
              {eu.map((c) => (
                <option key={c} value={c}>
                  {label(c)}
                </option>
              ))}
            </optgroup>
            <optgroup label="Other countries">
              {rest.map((c) => (
                <option key={c} value={c}>
                  {label(c)}
                </option>
              ))}
            </optgroup>
          </select>
        )}
      </Field>
      {fields.map((f) => (
        <Field
          key={f.key}
          label={f.label}
          optional={!f.required}
          hint={f.hint || undefined}
          error={errors[`compliance.${f.key}`] ?? errors[f.key] ?? (fields.length === 1 ? errors.compliance : undefined)}
        >
          {(a) => (
            <input
              {...a}
              className="a-input"
              required={f.required}
              value={draft.compliance[f.key] ?? ''}
              onChange={(e) => set('compliance', { ...draft.compliance, [f.key]: e.target.value })}
            />
          )}
        </Field>
      ))}
    </>
  )
}

export function ContactFields({ draft, set, errors }: FormProps) {
  return (
    <>
      <Field label="Email for enquiries" optional error={errors.contact_email}>
        {(a) => (
          <input
            {...a}
            className="a-input"
            type="email"
            inputMode="email"
            autoComplete="email"
            spellCheck={false}
            value={draft.contact_email}
            onChange={(e) => set('contact_email', e.target.value)}
          />
        )}
      </Field>
      <Field label="Phone" optional error={errors.contact_phone}>
        {(a) => (
          <input
            {...a}
            className="a-input"
            type="tel"
            autoComplete="tel"
            value={draft.contact_phone}
            onChange={(e) => set('contact_phone', e.target.value)}
          />
        )}
      </Field>
      <Field label="WhatsApp number" optional hint="With the country code, e.g. +1 555 010 0199." error={errors.whatsapp}>
        {(a) => (
          <input {...a} className="a-input" type="tel" value={draft.whatsapp} onChange={(e) => set('whatsapp', e.target.value)} />
        )}
      </Field>
      <Field label="Booking link" optional hint="A Calendly or similar link for viewings." error={errors.booking_url}>
        {(a) => (
          <input
            {...a}
            className="a-input"
            type="url"
            inputMode="url"
            spellCheck={false}
            placeholder="https://"
            value={draft.booking_url}
            onChange={(e) => set('booking_url', e.target.value)}
          />
        )}
      </Field>
    </>
  )
}

export function StylePicker({ value, onChange, error }: { value: StylePreset; onChange: (v: StylePreset) => void; error?: string }) {
  return (
    <fieldset className="a-fieldset a-field--wide">
      <legend>Style preset</legend>
      <div className="a-presets" role="radiogroup">
        {STYLE_PRESETS.map((s) => (
          <label key={s.key} className={`a-preset ${value === s.key ? 'is-on' : ''}`}>
            <input
              type="radio"
              name="style_preset"
              className="visually-hidden"
              value={s.key}
              checked={value === s.key}
              onChange={() => onChange(s.key)}
            />
            <span className="a-preset__swatch" style={{ background: s.background }} aria-hidden>
              <i style={{ background: s.accent }} />
              <i style={{ background: s.primary }} />
            </span>
            <strong>{s.name}</strong>
            <small>{s.mood}</small>
          </label>
        ))}
      </div>
      {error && <p className="a-field__error">{error}</p>}
    </fieldset>
  )
}

const REASON: Record<string, string> = {
  too_short: 'Use at least 3 characters.',
  too_long: 'Use 30 characters or fewer.',
  invalid_characters: 'Use lowercase letters, numbers and hyphens only.',
  reserved: 'That name is reserved. Try another.',
  taken: 'That name is taken. Try one of these:',
}

type Check = components['schemas']['UsernameCheck']

/** Username field with a debounced availability check, suggestions and the permanent-link confirmation. */
export function UsernameClaim({ suggested, onClaimed }: { suggested: string; onClaimed: (ws: Workspace) => void }) {
  const { noteError, readOnly } = useStudio()
  const [value, setValue] = useState(suggested)
  const [check, setCheck] = useState<Check | null>(null)
  const [checkError, setCheckError] = useState<ApiError | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState<ApiError | null>(null)
  const name = value.trim().toLowerCase()

  useEffect(() => {
    if (!name) return
    let cancelled = false
    const t = window.setTimeout(() => {
      unwrap(api.GET('/api/v1/workspace/username/check', { params: { query: { username: name } } }))
        .then((c) => {
          if (cancelled) return
          setCheck(c)
          setCheckError(null)
        })
        .catch((err) => {
          if (cancelled) return
          setCheck(null)
          setCheckError(asApiError(err))
        })
    }, 300)
    return () => {
      cancelled = true
      window.clearTimeout(t)
    }
  }, [name])

  const current = check && check.username === name ? check : null
  const available = Boolean(current?.available)

  const claim = async () => {
    setBusy(true)
    setFailure(null)
    try {
      const ws = await unwrap(api.POST('/api/v1/workspace/username', { body: { username: name, confirm_permanent: true } }))
      setConfirming(false)
      onClaimed(ws)
    } catch (err) {
      setFailure(noteError(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="a-field--wide">
      <Field
        label="Your link"
        hint="Lowercase letters, numbers and hyphens. This can't be changed later."
        error={!name ? null : (checkError?.message ?? (current && !current.available ? (REASON[current.reason ?? ''] ?? 'That name isn’t available.') : null))}
        ok={available ? `scrollwalk.com/${name} is available.` : null}
      >
        {(a) => (
          <div className="a-username">
            <span aria-hidden>scrollwalk.com/</span>
            <input
              {...a}
              className="a-input"
              autoCapitalize="none"
              autoComplete="off"
              spellCheck={false}
              maxLength={30}
              value={value}
              onChange={(e) => setValue(e.target.value.toLowerCase())}
            />
          </div>
        )}
      </Field>
      {current && !current.available && current.suggestions.length > 0 && (
        <div className="a-chips" aria-label="Suggestions">
          {current.suggestions.map((s) => (
            <button key={s} type="button" className="a-chip" onClick={() => setValue(s)}>
              {s}
            </button>
          ))}
        </div>
      )}
      <div className="a-actions">
        <button type="button" className="a-btn a-btn--ghost a-btn--sm" disabled={!available || readOnly} onClick={() => setConfirming(true)}>
          Claim this link
        </button>
      </div>
      {confirming && (
        <Dialog eyebrow="Your link" title="This will be your link forever" onClose={() => setConfirming(false)}>
          <p className="a-muted">
            <strong className="a-num">scrollwalk.com/{name}</strong> is permanent. You can change your display name any time, but not this link.
          </p>
          <ErrorAlert error={failure} />
          <div className="a-actions">
            <button type="button" className="a-btn a-btn--primary" disabled={busy} onClick={() => void claim()}>
              {busy ? 'Claiming…' : 'Yes, claim it'}
            </button>
            <button type="button" className="a-btn a-btn--ghost" onClick={() => setConfirming(false)}>
              Change it
            </button>
          </div>
        </Dialog>
      )}
    </div>
  )
}

export function suggestUsername(name: string) {
  return name
    .toLowerCase()
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 30)
}
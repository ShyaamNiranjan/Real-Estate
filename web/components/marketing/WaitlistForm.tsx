'use client'

import { useRef, useState, type FormEvent } from 'react'
import { Field, FormAlert, SubmitButton, isEmail } from '@/components/forms'
import { asApiError, type ApiError } from '@/lib/api/errors'
import { joinWaitlist } from '@/lib/api/waitlist'

type Errors = Partial<Record<'name' | 'email' | 'instagram_handle' | 'market', string>>

const HANDLE = /^[A-Za-z0-9._]{1,30}$/

export function WaitlistForm({ headingLevel = 'h3' }: { headingLevel?: 'h2' | 'h3' }) {
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [instagram, setInstagram] = useState('')
  const [market, setMarket] = useState('')
  const [errors, setErrors] = useState<Errors>({})
  const [failure, setFailure] = useState<ApiError | null>(null)
  const [busy, setBusy] = useState(false)
  const [joined, setJoined] = useState<string | null>(null)
  const nameRef = useRef<HTMLInputElement>(null)
  const emailRef = useRef<HTMLInputElement>(null)
  const instagramRef = useRef<HTMLInputElement>(null)
  const doneRef = useRef<HTMLDivElement>(null)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (busy) return
    const handle = instagram.trim().replace(/^@+/, '')
    const next: Errors = {}
    if (!name.trim()) next.name = 'Add your name.'
    if (!isEmail(email)) next.email = 'Enter a valid email address, like you@agency.com.'
    if (handle && !HANDLE.test(handle)) next.instagram_handle = 'Use letters, numbers, full stops and underscores only.'
    setErrors(next)
    setFailure(null)
    if (next.name) return nameRef.current?.focus()
    if (next.email) return emailRef.current?.focus()
    if (next.instagram_handle) return instagramRef.current?.focus()

    setBusy(true)
    try {
      await joinWaitlist({ name: name.trim(), email: email.trim(), instagram_handle: handle, market: market.trim() })
      setJoined(email.trim())
      requestAnimationFrame(() => doneRef.current?.focus())
    } catch (err) {
      const apiError = asApiError(err)
      setErrors(apiError.fields as Errors)
      setFailure(apiError)
    } finally {
      setBusy(false)
    }
  }

  const Heading = headingLevel

  if (joined) {
    return (
      <div className="ye-waitlist__done" ref={doneRef} tabIndex={-1} role="status">
        <span className="ye-done__badge" aria-hidden>
          ✓
        </span>
        <Heading className="ye-waitlist__done-title">You&rsquo;re on the list.</Heading>
        <p>
          We&rsquo;ll write to <strong>{joined}</strong> as soon as your invite is ready. Keep an eye on your inbox for a
          confirmation.
        </p>
      </div>
    )
  }

  return (
    <form className="ye-waitlist__form" onSubmit={submit} noValidate aria-label="Join the waitlist">
      <div className="ye-waitlist__row">
        <Field
          ref={nameRef}
          label="Your name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          autoComplete="name"
          error={errors.name}
          required
          maxLength={80}
        />
        <Field
          ref={emailRef}
          label="Work email"
          type="email"
          inputMode="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          autoComplete="email"
          spellCheck={false}
          autoCapitalize="none"
          error={errors.email}
          required
          maxLength={254}
        />
      </div>
      <div className="ye-waitlist__row">
        <Field
          ref={instagramRef}
          label="Instagram handle"
          optional
          prefix="@"
          value={instagram}
          onChange={(e) => setInstagram(e.target.value)}
          autoComplete="off"
          spellCheck={false}
          autoCapitalize="none"
          error={errors.instagram_handle}
          maxLength={31}
        />
        <Field
          label="Where do you sell?"
          optional
          value={market}
          onChange={(e) => setMarket(e.target.value)}
          placeholder="City or region, e.g. Miami"
          autoComplete="address-level2"
          error={errors.market}
          maxLength={80}
        />
      </div>
      <FormAlert error={failure && !Object.keys(failure.fields).length ? failure : null} />
      <SubmitButton busy={busy} busyLabel="Joining…">
        Join the waitlist
      </SubmitButton>
      <p className="ye-waitlist__fine">We&rsquo;ll only use these details to contact you about early access.</p>
    </form>
  )
}

'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useEffect, useId, useRef, useState, type FormEvent } from 'react'
import { CodeStep } from '@/components/auth/CodeStep'
import { GoogleButton, OrDivider } from '@/components/auth/GoogleButton'
import { useSignedInRedirect } from '@/components/auth/useSignedInRedirect'
import { Field, FormAlert, PasswordField, SubmitButton, isEmail, passwordProblem, PASSWORD_MAX } from '@/components/forms'
import { api } from '@/lib/api/client'
import { asApiError, unwrap, type ApiError } from '@/lib/api/errors'
import { planByKey } from '@/lib/plans'
import { useSession } from '@/lib/session'

type Errors = Partial<Record<'display_name' | 'email' | 'password' | 'accept_terms', string>>

export function SignupFlow({ plan, free }: { plan: string | null; free: boolean }) {
  useSignedInRedirect()
  const router = useRouter()
  const { signedIn } = useSession()
  const chosen = planByKey(plan) ?? planByKey('agent')!

  const [step, setStep] = useState<'form' | 'code'>('form')
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [terms, setTerms] = useState(false)
  const [errors, setErrors] = useState<Errors>({})
  const [failure, setFailure] = useState<ApiError | null>(null)
  const [busy, setBusy] = useState(false)
  const [sentAt, setSentAt] = useState(0)

  const nameRef = useRef<HTMLInputElement>(null)
  const emailRef = useRef<HTMLInputElement>(null)
  const passwordRef = useRef<HTMLInputElement>(null)
  const termsRef = useRef<HTMLInputElement>(null)
  const focusEmailOnReturn = useRef(false)
  const termsId = useId()

  useEffect(() => {
    if (step === 'form' && focusEmailOnReturn.current) {
      focusEmailOnReturn.current = false
      emailRef.current?.focus()
      emailRef.current?.select()
    }
  }, [step])

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (busy) return
    const next: Errors = {}
    if (!name.trim()) next.display_name = 'Add your name.'
    if (!isEmail(email)) next.email = 'Enter a valid email address, like you@agency.com.'
    const pw = passwordProblem(password)
    if (pw) next.password = pw
    if (!terms) next.accept_terms = 'Please agree to the Terms of Service and Privacy Policy to continue.'
    setErrors(next)
    setFailure(null)
    if (next.display_name) return nameRef.current?.focus()
    if (next.email) return emailRef.current?.focus()
    if (next.password) return passwordRef.current?.focus()
    if (next.accept_terms) return termsRef.current?.focus()

    setBusy(true)
    try {
      await unwrap(
        api.POST('/api/v1/auth/signup', {
          body: { email: email.trim(), password, display_name: name.trim(), accept_terms: true },
        }),
      )
      setSentAt(Date.now())
      setStep('code')
    } catch (err) {
      const apiError = asApiError(err)
      setErrors(apiError.fields as Errors)
      setFailure(apiError)
    } finally {
      setBusy(false)
    }
  }

  if (step === 'code') {
    return (
      <CodeStep
        eyebrow="Verify your email"
        title="Check your inbox."
        lede={
          <>
            We sent a 6-digit code to <strong>{email.trim()}</strong>. Enter it below to finish creating your account.
          </>
        }
        email={email.trim()}
        purpose="verify"
        sentAt={sentAt}
        onSent={() => setSentAt(Date.now())}
        submitLabel="Verify and continue"
        busyLabel="Verifying…"
        onSubmit={async (code) => {
          const me = await unwrap(api.POST('/api/v1/auth/verify', { body: { email: email.trim(), code } }))
          signedIn(me)
          router.replace('/studio')
        }}
        onChangeEmail={() => {
          focusEmailOnReturn.current = true
          setStep('form')
        }}
      />
    )
  }

  const fieldErrorsOnly = failure && Object.keys(failure.fields).length > 0

  return (
    <form className="ye-form" onSubmit={submit} noValidate>
      <p className="ye-eyebrow">{free ? 'Free preview' : `${chosen.name} plan`}</p>
      <h1 className="ye-signup__title">{free ? 'Build your first listing free.' : 'Create your workspace.'}</h1>
      <p className="ye-signup__lede">
        {free
          ? 'One listing with a walkthrough, on your own home. Only you can see it until you subscribe.'
          : 'Your agency site and Studio, ready in a minute. You can change plans any time.'}
      </p>

      <GoogleButton />
      <p className="ye-signup__note ye-signup__note--center">
        By continuing with Google, you agree to the <Link href="/terms">Terms of Service</Link> and{' '}
        <Link href="/privacy">Privacy Policy</Link>.
      </p>
      <OrDivider />

      <Field
        ref={nameRef}
        label="Your name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        autoComplete="name"
        error={errors.display_name}
        maxLength={80}
        required
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
      />
      <PasswordField
        ref={passwordRef}
        label="Password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        autoComplete="new-password"
        hint="At least 8 characters."
        error={errors.password}
        maxLength={PASSWORD_MAX}
        required
      />

      <div className={`ye-check ${errors.accept_terms ? 'is-invalid' : ''}`}>
        <input
          ref={termsRef}
          id={termsId}
          type="checkbox"
          checked={terms}
          onChange={(e) => {
            setTerms(e.target.checked)
            if (e.target.checked) setErrors((x) => ({ ...x, accept_terms: undefined }))
          }}
          aria-invalid={errors.accept_terms ? true : undefined}
          aria-describedby={errors.accept_terms ? `${termsId}-error` : undefined}
          required
        />
        <label htmlFor={termsId}>
          I agree to the{' '}
          <Link href="/terms" target="_blank" rel="noopener">
            Terms of Service
          </Link>{' '}
          and{' '}
          <Link href="/privacy" target="_blank" rel="noopener">
            Privacy Policy
          </Link>
          <span className="visually-hidden"> (open in a new tab)</span>.
        </label>
        {errors.accept_terms && (
          <p id={`${termsId}-error`} className="ye-field__error">
            {errors.accept_terms}
          </p>
        )}
      </div>

      <FormAlert error={fieldErrorsOnly ? null : failure} />
      <SubmitButton busy={busy} busyLabel="Creating your account…">
        {free ? 'Create free account' : 'Create account'}
      </SubmitButton>

      <p className="ye-signup__switch">
        Already have an account? <Link href="/login">Sign in</Link>
      </p>
      <p className="ye-signup__switch">
        {free ? (
          <>
            Ready to publish now? <Link href="/signup?plan=agent">Choose a plan</Link>
          </>
        ) : (
          <>
            Want to try first? <Link href="/signup?start=free">Build one listing free</Link>
          </>
        )}
      </p>
    </form>
  )
}

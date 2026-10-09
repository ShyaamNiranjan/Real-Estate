'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { CodeStep } from '@/components/auth/CodeStep'
import { GoogleButton, OrDivider } from '@/components/auth/GoogleButton'
import { useSignedInRedirect } from '@/components/auth/useSignedInRedirect'
import { Field, FormAlert, PasswordField, SubmitButton, isEmail, PASSWORD_MAX } from '@/components/forms'
import { api } from '@/lib/api/client'
import { asApiError, unwrap, type ApiError } from '@/lib/api/errors'
import { safeNext, useSession } from '@/lib/session'

const GOOGLE_ERRORS: Record<string, string> = {
  google_cancelled: 'Google sign-in was cancelled. Try again, or use your email and password.',
  google_failed: 'We couldn’t sign you in with Google. Please try again.',
  google_unavailable: 'Google sign-in isn’t available right now. Use your email and password instead.',
}

type Errors = Partial<Record<'email' | 'password', string>>

export function LoginFlow({ googleError, next }: { googleError: string | null; next: string | null }) {
  const destination = safeNext(next)
  useSignedInRedirect(destination)
  const router = useRouter()
  const { signedIn } = useSession()

  const [step, setStep] = useState<'form' | 'code'>('form')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [errors, setErrors] = useState<Errors>({})
  const [failure, setFailure] = useState<ApiError | string | null>(
    googleError ? (GOOGLE_ERRORS[googleError] ?? null) : null,
  )
  const [busy, setBusy] = useState(false)
  const [sentAt, setSentAt] = useState(0)
  const emailRef = useRef<HTMLInputElement>(null)
  const passwordRef = useRef<HTMLInputElement>(null)
  const focusEmailOnReturn = useRef(false)

  useEffect(() => {
    // Drop ?error= from the address bar so a reload doesn't show it again.
    if (googleError) router.replace(next ? `/login?next=${encodeURIComponent(next)}` : '/login', { scroll: false })
  }, [googleError, next, router])

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
    const nextErrors: Errors = {}
    if (!isEmail(email)) nextErrors.email = 'Enter the email address you signed up with.'
    if (!password) nextErrors.password = 'Enter your password.'
    setErrors(nextErrors)
    setFailure(null)
    if (nextErrors.email) return emailRef.current?.focus()
    if (nextErrors.password) return passwordRef.current?.focus()

    setBusy(true)
    try {
      const me = await unwrap(api.POST('/api/v1/auth/login', { body: { email: email.trim(), password } }))
      signedIn(me)
      router.replace(destination)
    } catch (err) {
      const apiError = asApiError(err)
      if (apiError.code === 'email_not_verified') {
        setSentAt(Date.now())
        setStep('code')
      } else {
        setErrors(apiError.fields as Errors)
        setFailure(apiError)
        if (apiError.code === 'invalid_credentials') {
          setPassword('')
          passwordRef.current?.focus()
        }
      }
      setBusy(false)
    }
  }

  if (step === 'code') {
    return (
      <CodeStep
        eyebrow="Verify your email"
        title="One more step."
        lede={
          <>
            Your email isn&rsquo;t verified yet, so we sent a 6-digit code to <strong>{email.trim()}</strong>.
          </>
        }
        email={email.trim()}
        purpose="verify"
        sentAt={sentAt}
        onSent={() => setSentAt(Date.now())}
        submitLabel="Verify and sign in"
        busyLabel="Verifying…"
        onSubmit={async (code) => {
          const me = await unwrap(api.POST('/api/v1/auth/verify', { body: { email: email.trim(), code } }))
          signedIn(me)
          router.replace(destination)
        }}
        onChangeEmail={() => {
          focusEmailOnReturn.current = true
          setPassword('')
          setStep('form')
        }}
      />
    )
  }

  return (
    <form className="ye-form" onSubmit={submit} noValidate>
      <p className="ye-eyebrow">Sign in</p>
      <h1 className="ye-signup__title">Welcome back.</h1>
      <p className="ye-signup__lede">Sign in to your Scrollwalk Studio.</p>

      <GoogleButton />
      <OrDivider />

      <Field
        ref={emailRef}
        label="Email"
        type="email"
        inputMode="email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        autoComplete="username"
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
        autoComplete="current-password"
        error={errors.password}
        maxLength={PASSWORD_MAX}
        required
      />
      <p className="ye-form__aside">
        <Link href="/forgot-password" className="ye-textlink">
          Forgot your password?
        </Link>
      </p>

      <FormAlert error={failure} />
      <SubmitButton busy={busy} busyLabel="Signing in…">
        Sign in
      </SubmitButton>

      <p className="ye-signup__switch">
        New to Scrollwalk? <Link href="/signup">Create an account</Link>
      </p>
    </form>
  )
}

'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { CodeStep } from '@/components/auth/CodeStep'
import { useSignedInRedirect } from '@/components/auth/useSignedInRedirect'
import { Field, FormAlert, PasswordField, SubmitButton, isEmail, passwordProblem, PASSWORD_MAX } from '@/components/forms'
import { api } from '@/lib/api/client'
import { ApiError, asApiError, unwrap } from '@/lib/api/errors'
import { useSession } from '@/lib/session'

export function ForgotFlow() {
  useSignedInRedirect()
  const router = useRouter()
  const { signedIn } = useSession()

  const [step, setStep] = useState<'email' | 'reset'>('email')
  const [email, setEmail] = useState('')
  const [emailError, setEmailError] = useState<string | null>(null)
  const [password, setPassword] = useState('')
  const [passwordError, setPasswordError] = useState<string | null>(null)
  const [failure, setFailure] = useState<ApiError | null>(null)
  const [busy, setBusy] = useState(false)
  const [sentAt, setSentAt] = useState(0)
  const emailRef = useRef<HTMLInputElement>(null)
  const passwordRef = useRef<HTMLInputElement>(null)
  const focusEmailOnReturn = useRef(false)

  useEffect(() => {
    if (step === 'email' && focusEmailOnReturn.current) {
      focusEmailOnReturn.current = false
      emailRef.current?.focus()
      emailRef.current?.select()
    }
  }, [step])

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (busy) return
    setFailure(null)
    if (!isEmail(email)) {
      setEmailError('Enter the email address you signed up with.')
      return emailRef.current?.focus()
    }
    setEmailError(null)
    setBusy(true)
    try {
      await unwrap(api.POST('/api/v1/auth/password/forgot', { body: { email: email.trim() } }))
      setSentAt(Date.now())
      setPassword('')
      setStep('reset')
    } catch (err) {
      const apiError = asApiError(err)
      if (apiError.fields.email) setEmailError(apiError.fields.email)
      else setFailure(apiError)
    } finally {
      setBusy(false)
    }
  }

  if (step === 'reset') {
    return (
      <CodeStep
        eyebrow="Reset password"
        title="Choose a new password."
        lede={
          <>
            If there&rsquo;s a Scrollwalk account for <strong>{email.trim()}</strong>, we&rsquo;ve emailed it a 6-digit code. Enter it with
            your new password.
          </>
        }
        email={email.trim()}
        purpose="reset"
        sentAt={sentAt}
        onSent={() => setSentAt(Date.now())}
        submitLabel="Save password and sign in"
        busyLabel="Saving…"
        autoSubmit={false}
        onSubmit={async (code) => {
          const problem = passwordProblem(password)
          setPasswordError(problem)
          if (problem) {
            passwordRef.current?.focus()
            throw new ApiError(422, 'validation_error', 'Choose a password of at least 8 characters.', { password: problem })
          }
          try {
            const me = await unwrap(api.POST('/api/v1/auth/password/reset', { body: { email: email.trim(), code, password } }))
            signedIn(me)
            router.replace('/studio')
          } catch (err) {
            const apiError = asApiError(err)
            if (apiError.fields.password) setPasswordError(apiError.fields.password)
            throw apiError
          }
        }}
        onChangeEmail={() => {
          focusEmailOnReturn.current = true
          setStep('email')
        }}
      >
        <PasswordField
          ref={passwordRef}
          label="New password"
          value={password}
          onChange={(e) => {
            setPassword(e.target.value)
            if (passwordError) setPasswordError(null)
          }}
          autoComplete="new-password"
          hint="At least 8 characters. You’ll be signed out on your other devices."
          error={passwordError}
          maxLength={PASSWORD_MAX}
          required
        />
      </CodeStep>
    )
  }

  return (
    <form className="ye-form" onSubmit={submit} noValidate>
      <p className="ye-eyebrow">Reset password</p>
      <h1 className="ye-signup__title">Forgot your password?</h1>
      <p className="ye-signup__lede">Enter your email and we&rsquo;ll send you a 6-digit code to choose a new one.</p>
      <Field
        ref={emailRef}
        label="Email"
        type="email"
        inputMode="email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        autoComplete="email"
        spellCheck={false}
        autoCapitalize="none"
        error={emailError}
        required
      />
      <FormAlert error={failure} />
      <SubmitButton busy={busy} busyLabel="Sending…">
        Send code
      </SubmitButton>
      <p className="ye-signup__switch">
        Remembered it? <Link href="/login">Back to sign in</Link>
      </p>
    </form>
  )
}

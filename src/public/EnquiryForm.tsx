import { useState, type FormEvent } from 'react'
import { submitEnquiry } from '../lib/api'

type Props = {
  listingId: string | null
  listingTitle?: string
  tone?: 'light' | 'dark'
}

type Status = 'idle' | 'sending' | 'sent' | 'error'

export function EnquiryForm({ listingId, listingTitle, tone = 'light' }: Props) {
  const [status, setStatus] = useState<Status>('idle')
  const [error, setError] = useState<string | null>(null)

  const onSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    const form = e.currentTarget
    const data = new FormData(form)
    // Honeypot: real visitors never see this field.
    if (String(data.get('company') ?? '')) {
      setStatus('sent')
      return
    }
    setStatus('sending')
    setError(null)
    try {
      await submitEnquiry({
        listing_id: listingId,
        name: String(data.get('name') ?? ''),
        email: String(data.get('email') ?? ''),
        phone: String(data.get('phone') ?? ''),
        message: String(data.get('message') ?? ''),
      })
      form.reset()
      setStatus('sent')
    } catch (err) {
      console.error(err)
      setError('We could not send that just now. Please try again, or email us directly.')
      setStatus('error')
    }
  }

  if (status === 'sent') {
    return (
      <div className={`enquiry enquiry--${tone} enquiry--sent`} role="status">
        <p className="enquiry__thanks">Thank you.</p>
        <p className="enquiry__thanks-body">
          We have your note{listingTitle ? ` about ${listingTitle}` : ''} and will reply within one working day.
        </p>
      </div>
    )
  }

  return (
    <form className={`enquiry enquiry--${tone}`} onSubmit={onSubmit} noValidate={false}>
      <label className="field">
        <span className="field__label">Name</span>
        <input name="name" type="text" autoComplete="name" required maxLength={120} />
      </label>
      <label className="field">
        <span className="field__label">Email</span>
        <input name="email" type="email" autoComplete="email" required maxLength={200} />
      </label>
      <label className="field">
        <span className="field__label">Phone <em>optional</em></span>
        <input name="phone" type="tel" autoComplete="tel" maxLength={40} />
      </label>
      <label className="field field--full">
        <span className="field__label">Message</span>
        <textarea
          name="message"
          rows={4}
          maxLength={4000}
          placeholder={listingTitle ? `Preferred dates, questions about ${listingTitle}…` : 'Tell us what you are looking for…'}
        />
      </label>
      <label className="enquiry__trap" aria-hidden>
        Company
        <input name="company" type="text" tabIndex={-1} autoComplete="off" />
      </label>
      <div className="enquiry__foot">
        <button type="submit" className="button" disabled={status === 'sending'}>
          {status === 'sending' ? 'Sending…' : 'Send enquiry'}
          <span className="arrow" aria-hidden />
        </button>
        {error && (
          <p className="enquiry__error" role="alert">
            {error}
          </p>
        )}
      </div>
    </form>
  )
}

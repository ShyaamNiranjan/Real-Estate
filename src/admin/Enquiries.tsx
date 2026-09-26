import { useEffect, useMemo, useState } from 'react'
import { formatDateTime } from '../lib/format'
import { useDocumentTitle } from '../lib/site'
import type { EnquiryStatus } from '../types/database'
import { listEnquiries, setEnquiryStatus, type EnquiryWithListing } from './api'
import { EmptyState, Spinner, errorMessage, useToast } from './ui'

const STATUSES: EnquiryStatus[] = ['new', 'read', 'closed']
const LABEL: Record<EnquiryStatus, string> = { new: 'New', read: 'Read', closed: 'Closed' }

export function Enquiries() {
  useDocumentTitle('Enquiries')
  const toast = useToast()
  const [rows, setRows] = useState<EnquiryWithListing[] | null>(null)
  const [filter, setFilter] = useState<EnquiryStatus | 'all'>('new')
  const [selected, setSelected] = useState<string | null>(null)

  useEffect(() => {
    listEnquiries()
      .then(setRows)
      .catch((err) => {
        toast(errorMessage(err), 'error')
        setRows([])
      })
  }, [toast])

  const visible = useMemo(() => (rows ?? []).filter((r) => filter === 'all' || r.status === filter), [rows, filter])
  const current = rows?.find((r) => r.id === selected) ?? null

  const setStatus = async (id: string, status: EnquiryStatus) => {
    setRows((r) => r?.map((x) => (x.id === id ? { ...x, status } : x)) ?? r)
    try {
      await setEnquiryStatus(id, status)
    } catch (err) {
      toast(errorMessage(err), 'error')
    }
  }

  const open = (row: EnquiryWithListing) => {
    setSelected(row.id)
    if (row.status === 'new') void setStatus(row.id, 'read')
  }

  return (
    <div className="a-page">
      <header className="a-page__head">
        <div>
          <p className="a-eyebrow">Inbox</p>
          <h1 className="a-title">Enquiries</h1>
        </div>
      </header>

      <div className="a-toolbar">
        <div className="a-tabs" role="tablist">
          {(['new', 'read', 'closed', 'all'] as const).map((f) => (
            <button key={f} type="button" role="tab" aria-selected={filter === f} className="a-tab" onClick={() => setFilter(f)}>
              {f === 'all' ? 'All' : LABEL[f]}
              <span className="a-tab__count">{(rows ?? []).filter((r) => f === 'all' || r.status === f).length}</span>
            </button>
          ))}
        </div>
      </div>

      {rows === null ? (
        <Spinner />
      ) : visible.length === 0 ? (
        <EmptyState title={filter === 'new' ? 'Inbox zero' : 'Nothing here'}>
          <p>Enquiries from listing pages and the home page arrive here.</p>
        </EmptyState>
      ) : (
        <div className="a-inbox">
          <ul className="a-inbox__list">
            {visible.map((r) => (
              <li key={r.id}>
                <button type="button" className={`a-inbox__row ${selected === r.id ? 'is-on' : ''} ${r.status === 'new' ? 'is-new' : ''}`} onClick={() => open(r)}>
                  <span className="a-inbox__name">{r.name}</span>
                  <span className="a-inbox__time">{formatDateTime(r.created_at)}</span>
                  <span className="a-inbox__about">{r.listings?.title ?? 'General enquiry'}</span>
                  <span className="a-inbox__snippet">{r.message ?? '—'}</span>
                </button>
              </li>
            ))}
          </ul>

          <div className="a-inbox__detail">
            {current ? (
              <article className="a-card">
                <p className="a-eyebrow">{current.listings?.title ?? 'General enquiry'}</p>
                <h2 className="a-card__title a-card__title--lg">{current.name}</h2>
                <dl className="a-dl">
                  <div>
                    <dt>Email</dt>
                    <dd>
                      <a className="a-link" href={`mailto:${current.email}?subject=${encodeURIComponent(`Re: ${current.listings?.title ?? 'Your enquiry'}`)}`}>
                        {current.email}
                      </a>
                    </dd>
                  </div>
                  {current.phone && (
                    <div>
                      <dt>Phone</dt>
                      <dd>
                        <a className="a-link" href={`tel:${current.phone}`}>
                          {current.phone}
                        </a>
                      </dd>
                    </div>
                  )}
                  <div>
                    <dt>Received</dt>
                    <dd>{formatDateTime(current.created_at)}</dd>
                  </div>
                </dl>
                <p className="a-message">{current.message || 'No message.'}</p>
                <div className="a-seg" role="radiogroup" aria-label="Status">
                  {STATUSES.map((s) => (
                    <label key={s} className={`a-seg__opt ${current.status === s ? 'is-on' : ''}`}>
                      <input type="radio" name="enq-status" checked={current.status === s} onChange={() => void setStatus(current.id, s)} />
                      {LABEL[s]}
                    </label>
                  ))}
                </div>
              </article>
            ) : (
              <EmptyState title="Select an enquiry" />
            )}
          </div>
        </div>
      )}
    </div>
  )
}

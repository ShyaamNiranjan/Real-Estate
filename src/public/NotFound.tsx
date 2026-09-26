import { Link } from 'react-router-dom'
import { useDocumentTitle } from '../lib/site'

export function NotFound({
  title = 'This address leads nowhere.',
  body = 'The residence may have been sold or withdrawn. The rest of the collection is still here.',
}: {
  title?: string
  body?: string
}) {
  useDocumentTitle('Not found')
  return (
    <div className="page page--empty">
      <div className="hero__grain" aria-hidden />
      <div className="empty">
        <p className="eyebrow">404</p>
        <h1 className="empty__title">{title}</h1>
        <p className="empty__body">{body}</p>
        <Link to="/" className="button button--light" viewTransition>
          Return to the collection
          <span className="arrow" aria-hidden />
        </Link>
      </div>
    </div>
  )
}

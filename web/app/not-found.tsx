import Link from 'next/link'
import { PlainPage } from '@/components/marketing/PlainPage'

export default function NotFound() {
  return (
    <PlainPage
      eyebrow="Not found"
      title={
        <>
          This door doesn&rsquo;t <em>open.</em>
        </>
      }
    >
      <p>The page you were looking for isn&rsquo;t here. It may have moved, or the link may be mistyped.</p>
      <div className="ye-hero__ctas">
        <Link href="/" className="ye-btn ye-btn--primary">
          Back to Scrollwalk
        </Link>
      </div>
    </PlainPage>
  )
}

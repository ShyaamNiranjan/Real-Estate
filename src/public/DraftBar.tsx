import { Link } from 'react-router-dom'
import { useProto } from '../lib/prototype'

/** Until the realtor clicks Publish in Studio, their site is a preview only they can see. */
export function SiteDraftBar() {
  const proto = useProto()
  if (proto.plan !== 'free' && proto.sitePublished) return null
  return (
    <div className="preview-bar" role="status">
      <span>
        <strong>{proto.plan === 'free' ? 'Private preview' : 'Not published'}</strong> —{' '}
        {proto.plan === 'free' ? 'subscribe to set up and publish your site.' : 'only you can see this site until you publish it.'}
      </span>
      <Link to={proto.plan === 'free' ? '/studio/plan' : '/studio'}>{proto.plan === 'free' ? 'See plans' : 'Open Studio'}</Link>
    </div>
  )
}

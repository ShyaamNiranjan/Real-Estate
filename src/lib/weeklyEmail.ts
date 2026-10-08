import { fmtDuration, fmtInt, fmtPct, sourceLabel, type Summary } from './analyticsData'

const esc = (s: string) => s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]!)

/** Email-client-safe HTML (tables + inline styles) for the Monday summary sent through Resend. */
export function weeklyEmailHtml(opts: {
  brand: string
  firstName: string
  summary: Summary
  titles: Record<string, string>
  studioUrl: string
}) {
  const { summary: s, brand, firstName, titles, studioUrl } = opts
  const top = s.listings.slice(0, 3)
  const source = s.sources[0]
  const change = s.previous.views ? Math.round(((s.totals.views - s.previous.views) / s.previous.views) * 100) : null
  const stat = (label: string, value: string) =>
    `<td style="padding:14px 10px;text-align:center;border:1px solid #e6e1d7;background:#fff"><div style="font:600 10px/1.4 Arial,sans-serif;letter-spacing:.14em;text-transform:uppercase;color:#9a7b4f">${label}</div><div style="font:400 28px/1.2 Georgia,serif;color:#16181a;margin-top:6px">${value}</div></td>`
  const rows = top
    .map(
      (l) =>
        `<tr><td style="padding:10px 0;border-bottom:1px solid #eee;font:14px/1.4 Arial,sans-serif;color:#16181a">${esc(titles[l.id] ?? 'Listing')}</td><td style="padding:10px 0;border-bottom:1px solid #eee;font:14px Arial,sans-serif;color:#52565a;text-align:right">${fmtInt(l.views)} ${l.views === 1 ? 'view' : 'views'} · ${l.enquiries} ${l.enquiries === 1 ? 'enquiry' : 'enquiries'}</td></tr>`,
    )
    .join('')
  return `<!doctype html><html><body style="margin:0;background:#f3f1ec">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f3f1ec;padding:32px 12px"><tr><td align="center">
<table role="presentation" width="560" cellpadding="0" cellspacing="0" style="max-width:560px;width:100%">
<tr><td style="padding:0 0 18px;font:600 12px Arial,sans-serif;letter-spacing:.3em;color:#16181a">YE</td></tr>
<tr><td style="background:#fff;padding:28px 28px 8px;border:1px solid #e6e1d7;border-bottom:0">
<div style="font:400 26px/1.25 Georgia,serif;color:#16181a">Your week, ${esc(firstName || brand)}</div>
<p style="font:15px/1.6 Arial,sans-serif;color:#52565a;margin:10px 0 0">${fmtInt(s.totals.visitors)} people visited your listings in the last 7 days${change === null ? '' : `, ${change >= 0 ? 'up' : 'down'} ${Math.abs(change)}% on the week before`}.</p>
</td></tr>
<tr><td style="background:#fff;padding:18px 28px;border:1px solid #e6e1d7;border-top:0;border-bottom:0">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
${stat('Views', fmtInt(s.totals.views))}${stat('Enquiries', String(s.totals.enquiries))}${stat('Watched it all', s.walkthrough.started ? fmtPct(s.walkthrough.finishRate) : '—')}
</tr></table></td></tr>
<tr><td style="background:#fff;padding:8px 28px 4px;border:1px solid #e6e1d7;border-top:0;border-bottom:0">
<div style="font:600 10px Arial,sans-serif;letter-spacing:.14em;text-transform:uppercase;color:#9a7b4f;margin:8px 0 4px">Top listings</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0">${rows || '<tr><td style="font:14px Arial,sans-serif;color:#8a8c8b;padding:10px 0">No listing views this week.</td></tr>'}</table>
</td></tr>
<tr><td style="background:#fff;padding:16px 28px 28px;border:1px solid #e6e1d7;border-top:0">
<p style="font:14px/1.6 Arial,sans-serif;color:#52565a;margin:0 0 18px">${source ? `Most visitors came from <strong>${esc(sourceLabel(source.name))}</strong>. ` : ''}People spent ${fmtDuration(s.totals.avgTimeMs)} on a listing on average.</p>
<a href="${esc(studioUrl)}" style="display:inline-block;background:#16181a;color:#fff;text-decoration:none;font:600 13px Arial,sans-serif;padding:12px 20px">Open full analytics</a>
</td></tr>
<tr><td style="padding:18px 4px;font:12px/1.6 Arial,sans-serif;color:#8a8c8b">Sent every Monday by YE for ${esc(brand)}. You can turn this off in Analytics.</td></tr>
</table></td></tr></table></body></html>`
}

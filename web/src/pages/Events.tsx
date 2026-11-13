import type { DoorEvent } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { useTenant } from '../auth/TenantContext'
import { SitePicker, useSite, useSites } from '../components/sites'
import { ErrorText, Loading, PageHeader, StatusBadge } from '../components/ui'
import { useLoad } from '../lib/useLoad'
import { describe } from '../lib/words'

/** What happened at the site's doors, newest first. The door-mode bookkeeping (locked, unlocked) is left out unless asked for. */
export function EventsPage() {
  const { api } = useAuth()
  const { current } = useTenant()
  const sites = useSites()
  const [site, pick] = useSite(sites.data)
  const events = useLoad(() => (site ? api.get<DoorEvent[]>(`/tenants/${current!.id}/sites/${site.id}/events?limit=200`) : Promise.resolve([])), [api, current?.id, site?.id])
  if (sites.error || events.error) return <ErrorText>{sites.error || events.error}</ErrorText>
  if (!sites.data || !events.data) return <Loading what="events" />
  const shown = events.data.filter((e) => !['Door/State/DoorMode', 'Door/State/DoorPhysicalState', 'IdPoint/Activity'].includes(e.topic))
  return (
    <>
      <PageHeader title="Events">
        <SitePicker sites={sites.data} site={site} onPick={pick} />
        <button className="ph-btn ph-btn-secondary" onClick={() => void events.reload()}>Refresh</button>
      </PageHeader>
      {shown.length === 0 ? <div className="ph-empty"><p>Nothing has happened at {site?.name}’s doors yet.</p></div> : (
        <div className="ph-table-wrap">
          <table className="ph-table pe-table">
            <thead><tr><th>When</th><th>What</th><th>Door</th><th>Who</th></tr></thead>
            <tbody>
              {shown.map((e) => {
                const d = describe(e)
                return (
                  <tr key={`${e.controller_id}-${e.seq}`} className={`ph-edge ph-edge-${d.tone}`}>
                    <td className="pe-who" data-label="When">{new Date(e.occurred_at).toLocaleString()}</td>
                    <td data-label="What"><StatusBadge tone={d.tone}>{d.text}</StatusBadge></td>
                    <td data-label="Door">{e.door ?? <span className="ph-hint">Unknown door</span>}</td>
                    <td data-label="Who">{e.cardholder ?? ''}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}

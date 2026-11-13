import { useAuth } from '../auth/AuthContext'
import { useTenant } from '../auth/TenantContext'
import { ErrorText, Loading, PageHeader } from '../components/ui'
import { useLoad } from '../lib/useLoad'

interface Entry { at: string; actor: string; action: string; target_type: string; target_id: string; detail: Record<string, unknown> }

/** Every change and every remote action, newest first (decision 18: kept, never changed). */
export function AuditPage() {
  const { api } = useAuth()
  const { current } = useTenant()
  const log = useLoad(() => api.get<Entry[]>(`/tenants/${current!.id}/audit`), [api, current?.id])
  if (log.error) return <ErrorText>{log.error}</ErrorText>
  if (!log.data) return <Loading what="the audit trail" />
  return (
    <>
      <PageHeader title="Audit trail" as="h2" />
      <div className="ph-table-wrap">
        <table className="ph-table pe-table">
          <thead><tr><th>When</th><th>Who</th><th>What</th></tr></thead>
          <tbody>
            {log.data.map((e, i) => (
              <tr key={i}>
                <td className="pe-who" data-label="When">{new Date(e.at).toLocaleString()}</td>
                <td data-label="Who">{e.actor}</td>
                <td data-label="What">{e.action.replace('.', ': ').replace('_', ' ')}{typeof e.detail.name === 'string' ? ` (${e.detail.name})` : ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}

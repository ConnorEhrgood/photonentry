import { Link } from 'react-router-dom'
import type { Controller } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { useTenant } from '../auth/TenantContext'
import { ErrorText, Loading, PageHeader, StatusBadge } from '../components/ui'
import { useLoad } from '../lib/useLoad'
import { controllerState } from './Doors'

/** The integrator's first page: every customer of theirs, and whether any of its controllers needs someone. */
export function CustomersPage() {
  const { api } = useAuth()
  const { tenants, select } = useTenant()
  const all = useLoad(async () => Promise.all(tenants.map(async (t) => {
    try { return { t, controllers: await api.get<Controller[]>(`/tenants/${t.id}/controllers`) } } catch { return { t, controllers: null } }
  })), [api, tenants])
  if (all.error) return <ErrorText>{all.error}</ErrorText>
  if (!all.data) return <Loading what="customers" />
  return (
    <>
      <PageHeader title="Customers" />
      <div className="ph-table-wrap">
        <table className="ph-table pe-table">
          <thead><tr><th>Customer</th><th>Controllers</th><th>Need attention</th><th></th></tr></thead>
          <tbody>
            {all.data.map(({ t, controllers }) => {
              const bad = (controllers ?? []).filter((c) => controllerState(c).tone === 'error').length
              return (
                <tr key={t.id} className={`ph-edge ph-edge-${controllers === null ? 'warning' : bad ? 'error' : 'ok'}`}>
                  <td className="pe-who" data-label="Customer"><strong>{t.name}</strong>{t.status === 'suspended' && <> <StatusBadge tone="warning">Plan needs attention</StatusBadge></>}</td>
                  <td data-label="Controllers">{controllers === null ? 'Not available' : controllers.length}</td>
                  <td data-label="Attention">{bad ? <StatusBadge tone="error">{bad}</StatusBadge> : <StatusBadge tone="ok">None</StatusBadge>}</td>
                  <td data-label=""><Link className="ph-btn ph-btn-secondary ph-btn-sm" to="/overview" onClick={() => select(t.id)}>Open</Link></td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </>
  )
}

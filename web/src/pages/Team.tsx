import type { Member } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { useTenant } from '../auth/TenantContext'
import { DIRECTORY_URL } from '../components/Layout'
import { ErrorText, Loading, PageHeader } from '../components/ui'
import { useLoad } from '../lib/useLoad'

const ROLE: Record<string, string> = { owner: 'Owner', admin: 'Admin', operator: 'Operator', viewer: 'Viewer' }

/** Who may use PhotonEntry here, and as what. People and roles are managed in the PhotonID directory ("Manage organization"). */
export function TeamPage() {
  const { api } = useAuth()
  const { current } = useTenant()
  const team = useLoad(() => api.get<Member[]>(`/tenants/${current!.id}/members`), [api, current?.id])
  if (team.error) return <ErrorText>{team.error}</ErrorText>
  if (!team.data) return <Loading what="the team" />
  return (
    <>
      <PageHeader title="Team" as="h2"><a className="ph-btn ph-btn-secondary" href={DIRECTORY_URL} target="_blank" rel="noopener">Manage in PhotonID</a></PageHeader>
      <div className="ph-table-wrap">
        <table className="ph-table pe-table">
          <thead><tr><th>Name</th><th>Role</th><th>Where</th></tr></thead>
          <tbody>
            {team.data.map((m) => (
              <tr key={m.person_id}>
                <td className="pe-who" data-label="Name">{m.name || m.email}{m.pending && <span className="ph-hint"> (invited)</span>}</td>
                <td data-label="Role">{ROLE[m.role] ?? m.role}</td>
                <td data-label="Where">{'all' in m.scope ? 'Every site' : `${m.scope.sites.length} site(s)`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}

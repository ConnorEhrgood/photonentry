import { useSearchParams } from 'react-router-dom'
import type { Site } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { useTenant } from '../auth/TenantContext'
import { useLoad, type Loaded } from '../lib/useLoad'

/** The organization's sites this person reaches (the API leaves out the rest). */
export function useSites(): Loaded<Site[]> {
  const { api } = useAuth()
  const { current } = useTenant()
  return useLoad(() => api.get<Site[]>(`/tenants/${current!.id}/sites`), [api, current?.id])
}

/** Most pages work on one site at a time: the one in `?site=`, else the first. */
export function useSite(sites: Site[] | null): [Site | null, (id: string) => void] {
  const [params, setParams] = useSearchParams()
  const site = sites?.find((s) => s.id === params.get('site')) ?? sites?.[0] ?? null
  return [site, (id) => setParams((p) => { p.set('site', id); return p }, { replace: true })]
}

export function SitePicker({ sites, site, onPick }: { sites: Site[]; site: Site | null; onPick: (id: string) => void }) {
  if (sites.length < 2) return site ? <span className="ph-hint">{site.name}</span> : null
  return (
    <select aria-label="Site" className="ph-input pe-site-picker" value={site?.id ?? ''} onChange={(e) => onPick(e.target.value)}>
      {sites.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
    </select>
  )
}

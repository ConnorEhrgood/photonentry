import { useLocation, useMatch, useNavigate, useSearchParams } from 'react-router-dom'
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

/** Most pages work on one site at a time: the one in the address (/org/<slug>/site/<site-slug>/…), else `?site=<id>`, else the first. */
export function useSite(sites: Site[] | null): [Site | null, (id: string) => void] {
  const [params, setParams] = useSearchParams()
  const inSite = useMatch('/org/:orgSlug/site/:siteSlug/*')
  const { pathname } = useLocation()
  const nav = useNavigate()
  const slug = inSite?.params.siteSlug
  const site = (slug ? sites?.find((s) => s.slug === slug) : sites?.find((s) => s.id === params.get('site'))) ?? sites?.[0] ?? null
  const pick = (id: string) => {
    const next = sites?.find((s) => s.id === id)
    if (slug && next) nav(pathname.replace(`/site/${slug}`, `/site/${next.slug}`), { replace: true })
    else setParams((p) => { p.set('site', id); return p }, { replace: true })
  }
  return [site, pick]
}

export function SitePicker({ sites, site, onPick }: { sites: Site[]; site: Site | null; onPick: (id: string) => void }) {
  if (sites.length < 2) return site ? <span className="ph-hint">{site.name}</span> : null
  return (
    <select aria-label="Site" className="ph-input pe-site-picker" value={site?.id ?? ''} onChange={(e) => onPick(e.target.value)}>
      {sites.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
    </select>
  )
}

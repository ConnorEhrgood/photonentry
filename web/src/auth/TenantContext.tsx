import { createContext, useContext, useMemo, useState, type ReactNode } from 'react'
import { useLocation, useMatch, useNavigate } from 'react-router-dom'
import type { TenantAccess } from '../api/types'
import { useAuth } from './AuthContext'

/** The suite's addresses (photon-suite ARCHITECTURE §6): an organization is /org/<slug>/…, a site /org/<slug>/site/<site-slug>/…. The slug is the
 *  directory's; until the directory has sent one, the organization's id stands in. */
export const orgKey = (t: Pick<TenantAccess, 'id' | 'slug'>) => t.slug || t.id

interface TenantState {
  tenants: TenantAccess[]
  /** The organization in the address; outside an /org/ address, the one used last (if still theirs), else the first. */
  current: TenantAccess | null
  /** The address names an organization this person cannot reach (or none exists): show "not found", never another customer. */
  missing: boolean
  /** The address names one of an organization's former slugs: the address it has now. */
  moved: string | null
  /** Open another organization on the same page (its site part dropped: sites are the organization's own). */
  select: (id: string) => void
  /** An address inside the current organization (and site, when the address names one): path('/doors') is /org/<slug>/doors. */
  path: (p: string) => string
  /** True if the signed-in person may use `capability` in the current organization. This is the server's own answer (role, scope and fine limits
   *  already applied) and only decides what the app shows; the API checks again on every request. */
  can: (capability: string) => boolean
}

const Ctx = createContext<TenantState | null>(null)
const KEY = 'pe:tenant'

export function useTenant(): TenantState {
  const v = useContext(Ctx)
  if (!v) throw new Error('useTenant outside TenantProvider')
  return v
}

export const remember = (id: string) => { try { localStorage.setItem(KEY, id) } catch { /* private mode: the choice just won't persist */ } }

export function TenantProvider({ children }: { children: ReactNode }) {
  const { me } = useAuth()
  const tenants = useMemo(() => me?.tenants ?? [], [me])
  const nav = useNavigate()
  const { pathname, search } = useLocation()
  const inOrg = useMatch('/org/:orgSlug/*')
  const inSite = useMatch('/org/:orgSlug/site/:siteSlug/*')
  const slug = inOrg?.params.orgSlug ?? null
  const siteSlug = inSite?.params.siteSlug ?? null
  const [picked] = useState<string | null>(() => { try { return localStorage.getItem(KEY) } catch { return null } })

  const value = useMemo<TenantState>(() => {
    const named = slug === null ? null : tenants.find((t) => orgKey(t) === slug || t.id === slug) ?? null
    const formerly = slug === null || named ? null : tenants.find((t) => t.former_slugs?.includes(slug)) ?? null
    const current = slug !== null ? named : tenants.find((t) => t.id === picked) ?? tenants[0] ?? null
    const prefix = current ? `/org/${orgKey(current)}${siteSlug ? `/site/${siteSlug}` : ''}` : ''
    return {
      tenants, current,
      missing: slug !== null && !named && !formerly,
      moved: formerly && slug !== null ? pathname.replace(`/org/${slug}`, `/org/${orgKey(formerly)}`) + search : null,
      select: (id) => {
        const t = tenants.find((x) => x.id === id)
        if (!t) return
        remember(id)
        const page = slug !== null ? pathname.replace(/^\/org\/[^/]+(\/site\/[^/]+)?/, '') : ''
        nav(`/org/${orgKey(t)}${page || '/'}`)
      },
      path: (p) => `${prefix}${p}`,
      can: (capability) => !!current && current.capabilities.includes(capability),
    }
  }, [tenants, slug, siteSlug, picked, pathname, search, nav])

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

import { useCallback } from 'react'
import { Link, Navigate, Outlet, useMatch } from 'react-router-dom'
import { config } from '../config'
import { useAuth } from '../auth/AuthContext'
import { orgKey, useTenant } from '../auth/TenantContext'
import { AppShell, type NavGroup, type NavItem } from '../shell/AppShell'
import { loadApps } from '../shell/AppSwitcher'
import { settingsTabs } from '../pages/Hubs'
import logo from '../assets/photon-logo.png'
import { LockdownBanner, useActiveLockdowns } from './Lockdown'

/** "Manage organization": people, sites and products are managed in the PhotonID directory app, not here. */
export const DIRECTORY_URL = config.directoryAppUrl

/** Someone who works on more than one customer: an integrator (partner staff), or Photon staff acting as one. They get the Customers list first. */
export const isIntegrator = (tenants: { source: string }[]): boolean => tenants.length > 1 || tenants.some((t) => t.source === 'partner')

export function Layout() {
  const { me, signOut, source } = useAuth()
  const { tenants, current, select, can, path, missing, moved } = useTenant()
  const inSite = useMatch('/org/:orgSlug/site/:siteSlug/*')
  const orgSlug = current ? orgKey(current) : null
  const siteSlug = inSite?.params.siteSlug ?? null
  // The suite's app switcher: every product, opening on this same organization and site (never another customer; photonid docs/HOME-PLAN.md §3).
  const lockdowns = useActiveLockdowns()
  const loadSwitcher = useCallback(async () => loadApps(config.directoryApiUrl, await source.getAccessToken(), orgSlug!, siteSlug), [source, orgSlug, siteSlug])
  if (moved) return <Navigate to={moved} replace />
  if (missing) return <OrgNotFound />
  if (!current) return <NoOrganization />

  // Daily work in the sidebar (DESIGN.md: about eight items at most); what a role cannot use is left out, and the API refuses it anyway.
  const items: (NavItem & { cap?: string })[] = [
    ...(isIntegrator(tenants) ? [{ to: '/customers', label: 'Customers', icon: 'clients' as const }] : []),
    { to: path('/overview'), label: 'Overview', icon: 'overview', cap: 'entry.view' },
    { to: path('/doors'), label: 'Doors', icon: 'door', cap: 'entry.view' },
    { to: path('/people'), label: 'People', icon: 'people', cap: 'entry.cardholders.view' },
    { to: path('/access'), label: 'Access', icon: 'access', cap: 'entry.view' },
    { to: path('/events'), label: 'Events', icon: 'events', cap: 'entry.events.view' },
    { to: path('/visitors'), label: 'Visitors', icon: 'bookings', cap: 'entry.visitors.manage' },
    { to: path('/my-doors'), label: 'My doors', icon: 'claim', cap: 'entry.unlock.own' },
  ]
  const groups: NavGroup[] = [{ items: items.filter((i) => !i.cap || can(i.cap)).map(({ cap: _cap, ...i }) => i) }]
  const footer: NavItem[] = settingsTabs(can).length > 0 ? [{ to: path('/settings'), label: 'Settings', icon: 'settings' }] : []
  const who = me?.name || me?.email || 'Account'
  const ends = current.expires_at ? new Date(current.expires_at) : null

  return (
    <AppShell
      apps={{ current: 'entry', load: loadSwitcher, homeUrl: `${DIRECTORY_URL.replace(/\/$/, '')}/` }}
      product="PhotonEntry"
      home={groups[0].items[0]?.to ?? '/'}
      groups={groups}
      footer={footer}
      switcher={tenants.length > 1 ? (
        <select aria-label="Customer" className="ph-input" value={current.id} onChange={(e) => select(e.target.value)}>
          {tenants.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
        </select>
      ) : <span className="ph-hint">{current.name}</span>}
      banner={lockdowns.length > 0 ? <LockdownBanner lockdowns={lockdowns} /> : current.status === 'suspended' ? (
        <div className="ph-banner ph-banner-warning" role="alert">
          This organization’s PhotonEntry plan needs attention: new doors and cardholders are paused. Every door and credential keeps working.
        </div>
      ) : ends ? (
        <div className="ph-banner ph-banner-info" role="status">Your access to {current.name} ends {ends.toLocaleString()}.</div>
      ) : undefined}
      account={{
        name: who,
        detail: me?.email && me.email !== who ? me.email : undefined,
        actions: [
          { label: 'Manage organization', onClick: () => window.open(DIRECTORY_URL, '_blank', 'noopener') },
          { label: 'Sign out', onClick: () => void signOut() },
        ],
      }}
    >
      <Outlet />
    </AppShell>
  )
}

/** The address names an organization this person cannot reach, or none at all: said plainly, never another customer shown instead. */
function OrgNotFound() {
  return (
    <div className="ph-auth">
      <div className="ph-card">
        <img className="ph-auth-logo" src={logo} alt="Photon" />
        <h1>We can’t open that organization</h1>
        <p>It may not exist, or this account may not have access to it in PhotonEntry.</p>
        <Link className="ph-btn ph-btn-secondary" to="/">Go to your organizations</Link>
      </div>
    </div>
  )
}

/** Signed in, but with no access to any organization in PhotonEntry. */
function NoOrganization() {
  const { me, signOut } = useAuth()
  return (
    <div className="ph-auth">
      <div className="ph-card">
        <img className="ph-auth-logo" src={logo} alt="Photon" />
        <h1>No access to PhotonEntry yet</h1>
        <p>{me?.email ? <>You are signed in as <strong>{me.email}</strong>, which</> : <>This account</>} isn’t a member of any organization that has PhotonEntry.
          Ask an administrator of your organization, or your Photon partner, to add you, or switch to another account.</p>
        <p className="ph-hint">People and products are managed in <a href={DIRECTORY_URL}>Manage organization</a>.</p>
        <button className="ph-btn ph-btn-secondary" onClick={() => void signOut()}>Sign out</button>
      </div>
    </div>
  )
}

import { Navigate, NavLink, Outlet } from 'react-router-dom'
import { useTenant } from '../auth/TenantContext'
import { PageHeader } from '../components/ui'

/** A page title over a row of tabs, one route per tab. */
function Hub({ title, tabs }: { title: string; tabs: { to: string; label: string; end?: boolean }[] }) {
  return (
    <>
      <PageHeader title={title} />
      <nav className="ph-tabs" aria-label={title}>
        {tabs.map((t) => <NavLink key={t.to} to={t.to} end={t.end}>{t.label}</NavLink>)}
      </nav>
      <Outlet />
    </>
  )
}

/** The Settings tabs this person may use; they follow what the role can do. */
export function settingsTabs(can: (capability: string) => boolean): { to: string; label: string }[] {
  const tabs = []
  if (can('entry.members.view')) tabs.push({ to: '/settings/team', label: 'Team' })
  if (can('entry.config.manage')) tabs.push({ to: '/settings/guard', label: 'PhotonGuard' }, { to: '/settings/console', label: 'PhotonConsole' })
  if (can('entry.audit.view')) tabs.push({ to: '/settings/audit', label: 'Audit trail' })
  return tabs
}

export function SettingsHub() {
  const { can } = useTenant()
  return <Hub title="Settings" tabs={settingsTabs(can)} />
}

export function SettingsIndex() {
  const { can } = useTenant()
  const tabs = settingsTabs(can)
  return tabs.length ? <Navigate to={tabs[0].to} replace /> : <NotForYou />
}

/** The API says no for anything outside a person's role; this is what they see if they follow a link there anyway. */
export function NotForYou() {
  return <div className="ph-empty"><p>Your role doesn’t include this page.</p></div>
}

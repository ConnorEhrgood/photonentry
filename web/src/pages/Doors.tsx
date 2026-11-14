import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { Controller, Door, Schedule } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { useTenant } from '../auth/TenantContext'
import { SitePicker, useSite, useSites } from '../components/sites'
import { ConfirmButton, ErrorText, Loading, PageHeader, StatusBadge } from '../components/ui'
import { ago } from '../lib/format'
import { useLoad } from '../lib/useLoad'
import { IntercomsSection } from './Intercoms'

/** How a controller is doing, in a word: offline, refusing its settings, applying them, or fine. Never colour alone (DESIGN.md). */
export function controllerState(c: Controller, now = Date.now()): { tone: 'ok' | 'info' | 'warning' | 'error'; text: string } {
  if (c.state === 'disabled') return { tone: 'warning', text: 'Out of service' }
  if (!c.last_seen || now - new Date(c.last_seen).getTime() > 120_000) return { tone: 'error', text: c.last_seen ? `Offline since ${ago(c.last_seen, now)}` : 'Never connected' }
  if (c.settings.error) return { tone: 'error', text: 'Settings refused' }
  if (!c.settings.current) return { tone: 'info', text: c.settings.latest === 0 ? 'Not published yet' : 'Applying settings' }
  return { tone: 'ok', text: 'Online' }
}

/** The site at a glance: its controllers, how each is doing, and the way to set the site up. */
export function OverviewPage() {
  const { api } = useAuth()
  const { current, can } = useTenant()
  const sites = useSites()
  const [site, pick] = useSite(sites.data)
  const controllers = useLoad(() => api.get<Controller[]>(`/tenants/${current!.id}/controllers`), [api, current?.id])
  const doors = useLoad(() => (site ? api.get<Door[]>(`/tenants/${current!.id}/sites/${site.id}/doors`) : Promise.resolve([])), [api, current?.id, site?.id])
  if (sites.error || controllers.error) return <ErrorText>{sites.error || controllers.error}</ErrorText>
  if (!sites.data || !controllers.data) return <Loading what="the overview" />
  const here = controllers.data.filter((c) => c.site_id === site?.id)
  const trouble = here.filter((c) => controllerState(c).tone === 'error').length
  return (
    <>
      <PageHeader title="Overview">
        <SitePicker sites={sites.data} site={site} onPick={pick} />
        {can('entry.config.manage') && site && <Link className="ph-btn" to={`/setup?site=${site.id}`}>Set up this site</Link>}
      </PageHeader>
      <div className="ph-stat-grid">
        <div className={`ph-stat ph-edge ph-edge-${here.length ? 'ok' : 'info'}`}><b>{here.length}</b><span>Controllers</span></div>
        <div className="ph-stat ph-edge"><b>{doors.data?.length ?? '…'}</b><span>Doors</span></div>
        <div className={`ph-stat ph-edge ph-edge-${trouble ? 'error' : 'ok'}`}><b>{trouble}</b><span>Need attention</span></div>
      </div>
      {here.length === 0 ? (
        <div className="ph-empty"><p>No controllers at {site?.name} yet.</p>
          {can('entry.config.manage') && site && <Link className="ph-btn" to={`/setup?site=${site.id}`}>Set up {site.name}</Link>}</div>
      ) : (
        <div className="ph-table-wrap">
          <table className="ph-table pe-table">
            <thead><tr><th>Controller</th><th>State</th><th>Doors</th><th>Settings</th></tr></thead>
            <tbody>
              {here.map((c) => {
                const st = controllerState(c)
                return (
                  <tr key={c.id} className={`ph-edge ph-edge-${st.tone}`}>
                    <td className="pe-who" data-label="Controller"><strong>{c.name || c.device.model}</strong><br /><span className="ph-hint">{c.device.model} {c.device.serial}</span></td>
                    <td data-label="State"><StatusBadge tone={st.tone}>{st.text}</StatusBadge></td>
                    <td data-label="Doors">{c.inventory?.doors.length ?? 0}</td>
                    <td data-label="Settings">{c.settings.latest ? `version ${c.settings.applied} of ${c.settings.latest}` : 'none yet'}{c.settings.error && <><br /><span className="ph-error">{c.settings.error}</span></>}</td>
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

/** The site's doors: who may open them is on Access; here, opening one remotely and locking the site down. */
export function DoorsPage() {
  const { api } = useAuth()
  const { current, can } = useTenant()
  const t = current!.id
  const sites = useSites()
  const [site, pick] = useSite(sites.data)
  const doors = useLoad(() => (site ? api.get<Door[]>(`/tenants/${t}/sites/${site.id}/doors`) : Promise.resolve([])), [api, t, site?.id])
  const schedules = useLoad(() => (site ? api.get<Schedule[]>(`/tenants/${t}/sites/${site.id}/schedules`) : Promise.resolve([])), [api, t, site?.id])
  const [note, setNote] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  if (sites.error || doors.error) return <ErrorText>{sites.error || doors.error}</ErrorText>
  if (!sites.data || !doors.data) return <Loading what="doors" />
  const unlocking = (d: Door) => schedules.data?.find((s) => s.id === d.unlock_schedule_id)?.name
  const act = async (what: () => Promise<unknown>, done: string) => {
    setError(null)
    try { await what(); setNote(done) } catch (e) { setNote(null); setError(e instanceof Error ? e.message : String(e)) }
  }
  return (
    <>
      <PageHeader title="Doors">
        <SitePicker sites={sites.data} site={site} onPick={pick} />
        {can('entry.lockdown') && site && doors.data.length > 0 && (
          <>
            <ConfirmButton danger label="Lock down" confirm={`Lock every door at ${site.name}?`}
              onConfirm={() => act(() => api.post(`/tenants/${t}/sites/${site.id}/lockdown`, { on: true }), `Lockdown sent to every door at ${site.name}. Exits stay free.`)} />
            <ConfirmButton label="End lockdown" confirm="End the lockdown?"
              onConfirm={() => act(() => api.post(`/tenants/${t}/sites/${site.id}/lockdown`, { on: false }), 'Lockdown ended.')} />
          </>
        )}
      </PageHeader>
      {note && <p className="ph-banner ph-banner-info" role="status">{note}</p>}
      <ErrorText>{error}</ErrorText>
      {doors.data.length === 0 ? (
        <div className="ph-empty"><p>No doors at {site?.name} yet.</p>{can('entry.config.manage') && site && <Link className="ph-btn" to={`/setup?site=${site.id}`}>Set up {site.name}</Link>}</div>
      ) : (
        <div className="ph-table-wrap">
          <table className="ph-table pe-table">
            <thead><tr><th>Door</th><th>Unlocked by schedule</th><th>Timing</th><th></th></tr></thead>
            <tbody>
              {doors.data.map((d) => (
                <tr key={d.id}>
                  <td className="pe-who" data-label="Door"><strong>{d.name}</strong></td>
                  <td data-label="Schedule">{unlocking(d) ?? <span className="ph-hint">No: locked unless someone has access</span>}</td>
                  <td data-label="Timing">{d.access_time_s} s to open; alarm after {d.open_too_long_s} s</td>
                  <td data-label="">{can('entry.door.unlock') && (
                    <button className="ph-btn ph-btn-secondary ph-btn-sm" onClick={() => void act(() => api.post(`/tenants/${t}/doors/${d.id}/action`, { action: 'access' }), `${d.name}: opening for ${d.access_time_s} seconds.`)}>
                      Open now
                    </button>
                  )}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {can('entry.config.manage') && site && doors.data.length > 0 && <IntercomsSection base={`/tenants/${t}/sites/${site.id}`} doors={doors.data} />}
    </>
  )
}

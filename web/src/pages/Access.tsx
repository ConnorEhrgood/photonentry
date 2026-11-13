import { useState } from 'react'
import type { Controller, Door, Group, Holiday, Published, Schedule } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { useTenant } from '../auth/TenantContext'
import { SitePicker, useSite, useSites } from '../components/sites'
import { ErrorText, Loading, PageHeader, StatusBadge } from '../components/ui'
import { useLoad } from '../lib/useLoad'
import { GroupDialog, HolidaysEditor, ScheduleDialog } from './AccessEdit'
import { ConfirmButton } from '../components/ui'
import { windows } from '../lib/words'

/** Who may open which door when: the site's access groups, the schedules they use, the holidays, and publishing to the controllers. */
export function AccessPage() {
  const { api } = useAuth()
  const { current, can } = useTenant()
  const t = current!.id
  const sites = useSites()
  const [site, pick] = useSite(sites.data)
  const base = site ? `/tenants/${t}/sites/${site.id}` : ''
  const data = useLoad(async () => {
    if (!site) return null
    const [groups, schedules, doors, holidays, controllers] = await Promise.all([
      api.get<Group[]>(`${base}/groups`), api.get<Schedule[]>(`${base}/schedules`), api.get<Door[]>(`${base}/doors`),
      api.get<{ days: Holiday[] }>(`${base}/holidays`), api.get<Controller[]>(`/tenants/${t}/controllers`),
    ])
    return { groups, schedules, doors, holidays: holidays.days, controllers: controllers.filter((c) => c.site_id === site.id) }
  }, [api, t, site?.id])
  const [published, setPublished] = useState<Published | null>(null)
  const [editing, setEditing] = useState<{ what: 'schedule'; item: Schedule | null } | { what: 'group'; item: Group | null } | null>(null)
  const [changed, setChanged] = useState(false)
  const [problems, setProblems] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  if (sites.error || data.error) return <ErrorText>{sites.error || data.error}</ErrorText>
  if (!sites.data || !data.data) return <Loading what="access" />
  const { groups, schedules, doors, holidays, controllers } = data.data
  const door = (id: string) => doors.find((d) => d.id === id)?.name ?? 'a removed door'
  const sched = (id: string | null) => (id ? schedules.find((s) => s.id === id)?.name ?? 'a removed schedule' : 'at all times')
  const behind = controllers.filter((c) => !c.settings.current).length
  const edit = can('entry.config.manage')
  const saved = async () => { setChanged(true); setPublished(null); await data.reload() }
  const remove = async (path: string) => {
    setError(null)
    try { await api.del(path); await saved() } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
  }
  const publish = async () => {
    setError(null)
    setProblems([])
    try { setPublished(await api.post<Published>(`${base}/publish`)); setChanged(false); await data.reload() } catch (e) {
      const list = (e as { data?: { problems?: string[] } }).data?.problems
      if (list) setProblems(list)
      else setError(e instanceof Error ? e.message : String(e))
    }
  }
  return (
    <>
      <PageHeader title="Access">
        <SitePicker sites={sites.data} site={site} onPick={pick} />
        {can('entry.config.manage') && <button className="ph-btn" onClick={() => void publish()}>Publish to the doors</button>}
      </PageHeader>
      {changed && <p className="ph-banner ph-banner-warning" role="status">Saved. The doors keep their current settings until you publish.</p>}
      {behind > 0 && !published && !changed && <p className="ph-banner ph-banner-info" role="status">{behind === 1 ? 'A controller is' : `${behind} controllers are`} not up to date with the last publish.</p>}
      {published && <p className="ph-banner ph-banner-ok" role="status">
        Published: {published.controllers.filter((c) => c.changed).length} controller(s) get new settings{published.controllers.some((c) => !c.changed) ? '; the rest had nothing new' : ''}.</p>}
      {problems.length > 0 && <ul className="ph-error" role="alert">{problems.map((p) => <li key={p}>{p}</li>)}</ul>}
      <ErrorText>{error}</ErrorText>

      <section aria-labelledby="groups-h" className="pe-section">
        <div className="ph-page-header"><h2 id="groups-h">Access groups</h2>
          {edit && <div className="ph-actions"><button className="ph-btn ph-btn-secondary ph-btn-sm" onClick={() => setEditing({ what: 'group', item: null })}>Add an access group</button></div>}</div>
        {groups.length === 0 ? <p className="ph-hint">None yet.</p> : (
          <div className="pe-cards">
            {groups.map((g) => (
              <div key={g.id} className="ph-card">
                <h3>{g.name}</h3>
                <ul>{g.rules.map((r, i) => <li key={i}>{r.doors.map(door).join(', ')}: <strong>{sched(r.schedule_id)}</strong></li>)}</ul>
                {edit && <div className="ph-actions">
                  <button className="ph-btn ph-btn-ghost ph-btn-sm" onClick={() => setEditing({ what: 'group', item: g })}>Change</button>
                  <ConfirmButton small danger label="Remove" confirm={`Remove ${g.name}? Its people lose these doors.`} onConfirm={() => remove(`${base}/groups/${g.id}`)} />
                </div>}
              </div>
            ))}
          </div>
        )}
      </section>

      <section aria-labelledby="sched-h" className="pe-section">
        <div className="ph-page-header"><h2 id="sched-h">Schedules</h2>
          {edit && <div className="ph-actions"><button className="ph-btn ph-btn-secondary ph-btn-sm" onClick={() => setEditing({ what: 'schedule', item: null })}>Add a schedule</button></div>}</div>
        {schedules.length === 0 ? <p className="ph-hint">None yet.</p> : (
          <ul className="pe-plain">
            {schedules.map((s) => (
              <li key={s.id} className="pe-item"><span><strong>{s.name}:</strong> {windows(s.windows)}</span>
                {s.on_holidays === 'off' ? <StatusBadge tone="info">Off on holidays</StatusBadge> : <StatusBadge tone="ok">Holidays too</StatusBadge>}
                {edit && <>
                  <button className="ph-btn ph-btn-ghost ph-btn-sm" onClick={() => setEditing({ what: 'schedule', item: s })}>Change</button>
                  <ConfirmButton small danger label="Remove" confirm={`Remove ${s.name}?`} onConfirm={() => remove(`${base}/schedules/${s.id}`)} />
                </>}</li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="hol-h" className="pe-section">
        <div className="ph-page-header"><h2 id="hol-h">Holidays</h2></div>
        {edit ? <HolidaysEditor base={base} days={holidays} onSaved={saved} /> : holidays.length === 0 ? <p className="ph-hint">None.</p> : (
          <ul className="pe-plain pe-columns">
            {holidays.map((h) => <li key={h.day}>{new Date(`${h.day}T12:00:00`).toLocaleDateString(undefined, { weekday: 'short', year: 'numeric', month: 'short', day: 'numeric' })}: {h.name}</li>)}
          </ul>
        )}
      </section>
      {editing?.what === 'schedule' && <ScheduleDialog base={base} schedule={editing.item} onClose={() => setEditing(null)} onSaved={saved} />}
      {editing?.what === 'group' && <GroupDialog base={base} group={editing.item} doors={doors} schedules={schedules} onClose={() => setEditing(null)} onSaved={saved} />}
    </>
  )
}

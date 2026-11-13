import { useState } from 'react'
import type { Controller, Door, Group, Holiday, Published, Schedule } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { useTenant } from '../auth/TenantContext'
import { SitePicker, useSite, useSites } from '../components/sites'
import { ErrorText, Loading, PageHeader, StatusBadge } from '../components/ui'
import { useLoad } from '../lib/useLoad'
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
  const [problems, setProblems] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  if (sites.error || data.error) return <ErrorText>{sites.error || data.error}</ErrorText>
  if (!sites.data || !data.data) return <Loading what="access" />
  const { groups, schedules, doors, holidays, controllers } = data.data
  const door = (id: string) => doors.find((d) => d.id === id)?.name ?? 'a removed door'
  const sched = (id: string | null) => (id ? schedules.find((s) => s.id === id)?.name ?? 'a removed schedule' : 'at all times')
  const behind = controllers.filter((c) => !c.settings.current).length
  const publish = async () => {
    setError(null)
    setProblems([])
    try { setPublished(await api.post<Published>(`${base}/publish`)); await data.reload() } catch (e) {
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
      {behind > 0 && !published && <p className="ph-banner ph-banner-info" role="status">{behind === 1 ? 'A controller is' : `${behind} controllers are`} not up to date with the last publish.</p>}
      {published && <p className="ph-banner ph-banner-ok" role="status">
        Published: {published.controllers.filter((c) => c.changed).length} controller(s) get new settings{published.controllers.some((c) => !c.changed) ? '; the rest had nothing new' : ''}.</p>}
      {problems.length > 0 && <ul className="ph-error" role="alert">{problems.map((p) => <li key={p}>{p}</li>)}</ul>}
      <ErrorText>{error}</ErrorText>

      <section aria-labelledby="groups-h" className="pe-section">
        <h2 id="groups-h">Access groups</h2>
        {groups.length === 0 ? <p className="ph-hint">None yet.</p> : (
          <div className="pe-cards">
            {groups.map((g) => (
              <div key={g.id} className="ph-card">
                <h3>{g.name}</h3>
                <ul>{g.rules.map((r, i) => <li key={i}>{r.doors.map(door).join(', ')}: <strong>{sched(r.schedule_id)}</strong></li>)}</ul>
              </div>
            ))}
          </div>
        )}
      </section>

      <section aria-labelledby="sched-h" className="pe-section">
        <h2 id="sched-h">Schedules</h2>
        {schedules.length === 0 ? <p className="ph-hint">None yet.</p> : (
          <ul className="pe-plain">
            {schedules.map((s) => (
              <li key={s.id} className="pe-item"><span><strong>{s.name}:</strong> {windows(s.windows)}</span>
                {s.on_holidays === 'off' ? <StatusBadge tone="info">Off on holidays</StatusBadge> : <StatusBadge tone="ok">Holidays too</StatusBadge>}</li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="hol-h" className="pe-section">
        <h2 id="hol-h">Holidays</h2>
        {holidays.length === 0 ? <p className="ph-hint">None.</p> : (
          <ul className="pe-plain pe-columns">
            {holidays.map((h) => <li key={h.day}>{new Date(`${h.day}T12:00:00`).toLocaleDateString(undefined, { weekday: 'short', year: 'numeric', month: 'short', day: 'numeric' })}: {h.name}</li>)}
          </ul>
        )}
      </section>
    </>
  )
}

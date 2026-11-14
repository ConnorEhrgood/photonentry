import { useState } from 'react'
import type { Door, Group, Holiday, Schedule, Window } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { ConfirmButton, ErrorText, Modal } from '../components/ui'

const DAYS: [string, string][] = [['mo', 'Mon'], ['tu', 'Tue'], ['we', 'Wed'], ['th', 'Thu'], ['fr', 'Fri'], ['sa', 'Sat'], ['su', 'Sun']]
const WEEKDAYS = ['mo', 'tu', 'we', 'th', 'fr']

/** "24:00" is a valid end (the end of the day); the time input cannot hold it, so the form uses "00:00" for an end and sends "24:00". */
const toInput = (t: string) => (t === '24:00' ? '00:00' : t)
const fromEnd = (t: string) => (t === '00:00' ? '24:00' : t)

function problems(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

/** A schedule: weekly windows, and whether it is off on the site's holidays. */
export function ScheduleDialog({ base, schedule, onClose, onSaved }: { base: string; schedule: Schedule | null; onClose: () => void; onSaved: () => Promise<void> }) {
  const { api } = useAuth()
  const [name, setName] = useState(schedule?.name ?? '')
  const [windows, setWindows] = useState<Window[]>(schedule?.windows ?? [{ days: WEEKDAYS, start: '08:00', end: '18:00' }])
  const [offOnHolidays, setOffOnHolidays] = useState((schedule?.on_holidays ?? 'off') === 'off')
  const [error, setError] = useState<string | null>(null)
  const set = (i: number, w: Partial<Window>) => setWindows(windows.map((x, j) => (j === i ? { ...x, ...w } : x)))
  const bad = windows.some((w) => w.days.length === 0 || (w.end !== '24:00' && w.end <= w.start))
  const save = async () => {
    setError(null)
    const body = { name: name.trim(), windows, on_holidays: offOnHolidays ? 'off' : 'normal' }
    try {
      if (schedule) await api.put(`${base}/schedules/${schedule.id}`, body)
      else await api.post(`${base}/schedules`, body)
      await onSaved()
      onClose()
    } catch (e) { setError(problems(e)) }
  }
  return (
    <Modal title={schedule ? `Change ${schedule.name}` : 'Add a schedule'} onClose={onClose} wide>
      <div className="ph-field"><label htmlFor="sch-name">Name</label><input id="sch-name" className="ph-input" value={name} onChange={(e) => setName(e.target.value)} /></div>
      {windows.map((w, i) => (
        <fieldset key={i} className="pe-fieldset">
          <legend>Window {i + 1}</legend>
          <div className="pe-days" role="group" aria-label={`Days of window ${i + 1}`}>
            {DAYS.map(([key, label]) => (
              <label key={key} className="ph-check">
                <input type="checkbox" checked={w.days.includes(key)} onChange={(e) => set(i, { days: e.target.checked ? [...w.days, key] : w.days.filter((d) => d !== key) })} /> {label}
              </label>
            ))}
          </div>
          <div className="pe-row">
            <div className="ph-field"><label htmlFor={`from-${i}`}>From</label>
              <input id={`from-${i}`} type="time" className="ph-input" value={w.start} onChange={(e) => set(i, { start: e.target.value })} /></div>
            <div className="ph-field"><label htmlFor={`to-${i}`}>Until</label>
              <input id={`to-${i}`} type="time" className="ph-input" value={toInput(w.end)} onChange={(e) => set(i, { end: fromEnd(e.target.value) })} />
              <span className="ph-hint">00:00 means midnight, the end of the day.</span></div>
          </div>
          {windows.length > 1 && <button className="ph-btn ph-btn-ghost ph-btn-sm" onClick={() => setWindows(windows.filter((_, j) => j !== i))}>Remove this window</button>}
        </fieldset>
      ))}
      <button className="ph-btn ph-btn-secondary ph-btn-sm" onClick={() => setWindows([...windows, { days: ['sa'], start: '09:00', end: '13:00' }])}>Add a window</button>
      <label className="ph-check"><input type="checkbox" checked={offOnHolidays} onChange={(e) => setOffOnHolidays(e.target.checked)} /> Off on the site’s holidays</label>
      {bad && <p className="ph-error">Each window needs at least one day, and ends after it starts.</p>}
      <ErrorText>{error}</ErrorText>
      <div className="ph-modal-footer">
        <button className="ph-btn" disabled={!name.trim() || bad} onClick={() => void save()}>Save</button>
        <button className="ph-btn ph-btn-ghost" onClick={onClose}>Cancel</button>
      </div>
    </Modal>
  )
}

interface DraftRule { doors: string[]; schedule_id: string }

/** An access group: which doors, under which schedule (or at all times), rule by rule. */
export function GroupDialog({ base, group, doors, schedules, onClose, onSaved }: {
  base: string; group: Group | null; doors: Door[]; schedules: Schedule[]; onClose: () => void; onSaved: () => Promise<void>
}) {
  const { api } = useAuth()
  const [name, setName] = useState(group?.name ?? '')
  const [rules, setRules] = useState<DraftRule[]>(group?.rules.map((r) => ({ doors: r.doors, schedule_id: r.schedule_id ?? '' })) ?? [{ doors: [], schedule_id: '' }])
  const [forVisitors, setForVisitors] = useState(!!group?.for_visitors)
  const [error, setError] = useState<string | null>(null)
  const set = (i: number, r: Partial<DraftRule>) => setRules(rules.map((x, j) => (j === i ? { ...x, ...r } : x)))
  const bad = rules.some((r) => r.doors.length === 0)
  const save = async () => {
    setError(null)
    const body = { name: name.trim(), rules: rules.map((r) => ({ doors: r.doors, schedule_id: r.schedule_id || null })), for_visitors: forVisitors }
    try {
      if (group) await api.put(`${base}/groups/${group.id}`, body)
      else await api.post(`${base}/groups`, body)
      await onSaved()
      onClose()
    } catch (e) { setError(problems(e)) }
  }
  return (
    <Modal title={group ? `Change ${group.name}` : 'Add an access group'} onClose={onClose} wide>
      <div className="ph-field"><label htmlFor="grp-name">Name</label><input id="grp-name" className="ph-input" value={name} onChange={(e) => setName(e.target.value)} /></div>
      {rules.map((r, i) => (
        <fieldset key={i} className="pe-fieldset">
          <legend>Rule {i + 1}</legend>
          <div role="group" aria-label={`Doors of rule ${i + 1}`} className="pe-days">
            {doors.map((d) => (
              <label key={d.id} className="ph-check">
                <input type="checkbox" checked={r.doors.includes(d.id)} onChange={(e) => set(i, { doors: e.target.checked ? [...r.doors, d.id] : r.doors.filter((x) => x !== d.id) })} /> {d.name}
              </label>
            ))}
          </div>
          <div className="ph-field"><label htmlFor={`when-${i}`}>When</label>
            <select id={`when-${i}`} className="ph-input" value={r.schedule_id} onChange={(e) => set(i, { schedule_id: e.target.value })}>
              <option value="">At all times</option>
              {schedules.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select></div>
          {rules.length > 1 && <button className="ph-btn ph-btn-ghost ph-btn-sm" onClick={() => setRules(rules.filter((_, j) => j !== i))}>Remove this rule</button>}
        </fieldset>
      ))}
      <button className="ph-btn ph-btn-secondary ph-btn-sm" onClick={() => setRules([...rules, { doors: [], schedule_id: '' }])}>Add a rule</button>
      <label className="ph-check"><input type="checkbox" checked={forVisitors} onChange={(e) => setForVisitors(e.target.checked)} /> Visitors’ passes may use this group
        <span className="ph-hint"> (front-desk operators can then give it to visitors, for up to 31 days)</span></label>
      {bad && <p className="ph-error">Each rule opens at least one door.</p>}
      <ErrorText>{error}</ErrorText>
      <div className="ph-modal-footer">
        <button className="ph-btn" disabled={!name.trim() || bad || doors.length === 0} onClick={() => void save()}>Save</button>
        <button className="ph-btn ph-btn-ghost" onClick={onClose}>Cancel</button>
      </div>
    </Modal>
  )
}

/** The site's holidays: add or remove a day, or add a year's US holidays in one go. Saved as a whole (PUT). */
export function HolidaysEditor({ base, days, onSaved }: { base: string; days: Holiday[]; onSaved: () => Promise<void> }) {
  const { api } = useAuth()
  const [day, setDay] = useState('')
  const [name, setName] = useState('')
  const [year, setYear] = useState(String(new Date().getFullYear() + 1))
  const [kind, setKind] = useState('us-business')
  const [error, setError] = useState<string | null>(null)
  const save = async (next: Holiday[]) => {
    setError(null)
    try { await api.put(`${base}/holidays`, { days: next }); await onSaved() } catch (e) { setError(problems(e)) }
  }
  const addYear = async () => {
    try {
      const list = await api.get<Holiday[]>(`/holidays/${kind}/${year}`)
      const have = new Set(days.map((d) => d.day))
      await save([...days, ...list.filter((h) => !have.has(h.day))])
    } catch (e) { setError(problems(e)) }
  }
  return (
    <div className="pe-holiday-edit">
      <div className="pe-row">
        <div className="ph-field"><label htmlFor="hol-day">Day</label><input id="hol-day" type="date" className="ph-input" value={day} onChange={(e) => setDay(e.target.value)} /></div>
        <div className="ph-field"><label htmlFor="hol-name">Name</label><input id="hol-name" className="ph-input" placeholder="Spring break" value={name} onChange={(e) => setName(e.target.value)} /></div>
      </div>
      <button className="ph-btn ph-btn-secondary ph-btn-sm" disabled={!day || days.some((d) => d.day === day)}
        onClick={() => void save([...days, { day, name: name.trim() }]).then(() => { setDay(''); setName('') })}>Add the day</button>
      <div className="pe-row">
        <div className="ph-field"><label htmlFor="hol-kind">US holidays</label>
          <select id="hol-kind" className="ph-input" value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="us-business">Business (7 days)</option><option value="us-federal">Federal (11 days)</option>
          </select></div>
        <div className="ph-field"><label htmlFor="hol-year">Year</label><input id="hol-year" type="number" min={2000} max={2100} className="ph-input" value={year} onChange={(e) => setYear(e.target.value)} /></div>
      </div>
      <button className="ph-btn ph-btn-secondary ph-btn-sm" onClick={() => void addYear()}>Add that year’s holidays</button>
      <ErrorText>{error}</ErrorText>
      <ul className="pe-plain pe-columns">
        {days.map((h) => (
          <li key={h.day} className="pe-item">
            <span>{new Date(`${h.day}T12:00:00`).toLocaleDateString(undefined, { weekday: 'short', year: 'numeric', month: 'short', day: 'numeric' })}: {h.name}</span>
            <ConfirmButton small label="Remove" confirm="Remove?" onConfirm={() => save(days.filter((d) => d.day !== h.day))} />
          </li>
        ))}
      </ul>
    </div>
  )
}

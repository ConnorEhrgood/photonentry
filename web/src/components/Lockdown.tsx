import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import type { Door, Lockdown } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { useTenant } from '../auth/TenantContext'
import { ago } from '../lib/format'
import { useLoad } from '../lib/useLoad'
import { ErrorText, Modal, StatusBadge } from './ui'

/** How often the banner checks for lockdowns: it is a safety notice, so it must not wait for the next page. */
export const LOCKDOWN_POLL_MS = 15_000

const STATE: Record<string, { tone: 'ok' | 'info' | 'warning' | 'error'; text: string }> = {
  done: { tone: 'ok', text: 'Confirmed' }, sent: { tone: 'info', text: 'Waiting for the controller' },
  failed: { tone: 'error', text: 'The controller refused' }, expired: { tone: 'error', text: 'Not confirmed in time' },
  not_sent: { tone: 'error', text: 'Controller out of service' },
}

/** The organization's sites that are locked down now, checked again every few seconds. */
export function useActiveLockdowns() {
  const { api } = useAuth()
  const { current, can } = useTenant()
  const allowed = !!current && can('entry.view')
  const found = useLoad(() => (allowed ? api.get<Lockdown[]>(`/tenants/${current!.id}/lockdowns/active`) : Promise.resolve([])), [api, current?.id, allowed])
  const { reload } = found
  useEffect(() => {
    if (!allowed) return
    const t = setInterval(() => void reload(), LOCKDOWN_POLL_MS)
    return () => clearInterval(t)
  }, [allowed, reload])
  return found.data ?? []
}

/** On every page while a site is locked down: where, why, since when, and by whom. */
export function LockdownBanner({ lockdowns }: { lockdowns: Lockdown[] }) {
  const { path } = useTenant()
  return (
    <div className="ph-banner ph-banner-error pe-lockdown-banner" role="alert">
      {lockdowns.map((l) => (
        <p key={l.id}>
          <strong>{l.site} is locked down</strong>{l.whole_site ? '' : ` (${l.doors.length} door${l.doors.length === 1 ? '' : 's'})`}: {l.reason}.
          {' '}Since {ago(l.started_at)}, by {l.started_by}. <Link to={path(`/doors?site=${l.site_id}`)}>See the doors</Link>
        </p>
      ))}
    </div>
  )
}

/** The site's lockdown on the Doors page: each door's state, and the way to end it. */
export function LockdownPanel({ lockdown, canEnd, onEnd }: { lockdown: Lockdown; canEnd: boolean; onEnd: () => void }) {
  return (
    <section className="ph-card pe-lockdown" aria-labelledby="lockdown-h">
      <h2 id="lockdown-h">Locked down <StatusBadge tone="error">{lockdown.whole_site ? 'Whole site' : 'Some doors'}</StatusBadge></h2>
      <p>{lockdown.reason}. Started {ago(lockdown.started_at)} by {lockdown.started_by}. Credentials, schedules and remote unlocks are ignored
        until it ends; exits and fire release work as always.</p>
      <ul className="pe-plain">
        {lockdown.doors.map((d) => (
          <li key={d.door_id} className="pe-item"><span>{d.door}</span>
            <StatusBadge tone={STATE[d.state]?.tone ?? 'info'}>{STATE[d.state]?.text ?? d.state}</StatusBadge></li>
        ))}
      </ul>
      {canEnd && <div className="ph-actions"><button className="ph-btn" onClick={onEnd}>End the lockdown</button></div>}
    </section>
  )
}

/** Start a lockdown (the whole site, or some doors) or end one: both need a reason, kept in the audit trail. */
export function LockdownDialog({ base, siteName, doors, ending, onClose, onDone }: {
  base: string; siteName: string; doors: Door[]; ending: boolean; onClose: () => void; onDone: () => Promise<void>
}) {
  const { api } = useAuth()
  const [reason, setReason] = useState('')
  const [whole, setWhole] = useState(true)
  const [chosen, setChosen] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const ready = reason.trim().length > 0 && (ending || whole || chosen.length > 0) && !busy
  const go = async () => {
    setError(null)
    setBusy(true)
    try {
      await api.post(`${base}/lockdown`, { on: !ending, reason: reason.trim(), ...(ending || whole ? {} : { door_ids: chosen }) })
      await onDone()
      onClose()
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) } finally { setBusy(false) }
  }
  return (
    <Modal title={ending ? `End the lockdown at ${siteName}` : `Lock down ${siteName}`} onClose={onClose}>
      {!ending && (
        <>
          <p className="ph-hint">Locked-down doors stay locked: cards, PINs, schedules and remote unlocks are ignored until the lockdown ends. Exits and
            fire release always work.</p>
          <fieldset className="pe-fieldset">
            <legend>Which doors</legend>
            <label className="ph-check"><input type="radio" name="scope" checked={whole} onChange={() => setWhole(true)} /> Every door at {siteName}</label>
            <label className="ph-check"><input type="radio" name="scope" checked={!whole} onChange={() => setWhole(false)} /> Some doors</label>
            {!whole && (
              <div className="pe-days" role="group" aria-label="Doors to lock down">
                {doors.map((d) => (
                  <label key={d.id} className="ph-check"><input type="checkbox" checked={chosen.includes(d.id)}
                    onChange={(e) => setChosen(e.target.checked ? [...chosen, d.id] : chosen.filter((x) => x !== d.id))} /> {d.name}</label>
                ))}
              </div>
            )}
          </fieldset>
        </>
      )}
      <div className="ph-field">
        <label htmlFor="lockdown-reason">{ending ? 'Why it can end' : 'Why'}</label>
        <input id="lockdown-reason" className="ph-input" maxLength={200} value={reason} onChange={(e) => setReason(e.target.value)}
          placeholder={ending ? 'For example: all clear from police' : 'For example: threat reported in the parking lot'} />
        <span className="ph-hint">Kept in the audit trail, and shown to everyone at the site.</span>
      </div>
      <ErrorText>{error}</ErrorText>
      <div className="ph-modal-footer">
        <button className={`ph-btn${ending ? '' : ' ph-btn-danger'}`} disabled={!ready} onClick={() => void go()}>{ending ? 'End the lockdown' : 'Lock down now'}</button>
        <button className="ph-btn ph-btn-ghost" onClick={onClose}>Cancel</button>
      </div>
    </Modal>
  )
}

import { useState } from 'react'
import type { CommissioningRecord, DoorCommissioning, Licenses, SiteCommissioning } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { useTenant } from '../auth/TenantContext'
import { ConfirmButton, ErrorText, Loading, Modal, PageHeader, StatusBadge } from '../components/ui'
import { useLoad } from '../lib/useLoad'

const STATES: Record<string, string> = { PA: 'Pennsylvania', OH: 'Ohio', WV: 'West Virginia', ZZ: 'Elsewhere' }
const WHY: Record<string, string> = { never: 'Needs commissioning', voided: 'Needs commissioning again', moved: 'Rewired: needs commissioning' }
const day = (iso: string) => new Date(`${iso.slice(0, 10)}T12:00:00`).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
const message = (e: unknown) => (e instanceof Error ? e.message : String(e))

/** A door's commissioning state, in a word (never colour alone). */
export function CommissioningBadge({ d }: { d: DoorCommissioning | undefined }) {
  if (!d) return null
  return d.in_service ? <StatusBadge tone="ok">In service</StatusBadge> : <StatusBadge tone="warning">{WHY[d.why] ?? 'Needs commissioning'}</StatusBadge>
}

/** The signed record (and the door's earlier ones), and the way to need it again. */
export function RecordDialog({ base, d, choices, canVoid, onClose, onChanged }: {
  base: string; d: DoorCommissioning; choices: SiteCommissioning; canVoid: boolean; onClose: () => void; onChanged: () => Promise<void>
}) {
  const { api } = useAuth()
  const history = useLoad(() => api.get<CommissioningRecord[]>(`${base}/doors/${d.door_id}/commissioning`), [api, base, d.door_id])
  const [reason, setReason] = useState('')
  const [error, setError] = useState<string | null>(null)
  const r = d.record
  return (
    <Modal title={`${d.door}: commissioning`} onClose={onClose} wide>
      <p><CommissioningBadge d={d} /></p>
      {r && (
        <dl className="pe-setup pe-record">
          <dt>Signed</dt><dd>{day(r.signed_at)} by {r.signed_by}{r.voided_at ? ` · no longer in force (${r.void_reason})` : ''}</dd>
          <dt>Installer</dt><dd>{r.installer}</dd>
          {r.license && <><dt>License</dt><dd>{r.license}</dd></>}
          <dt>Where</dt><dd>{STATES[r.jurisdiction]} · {r.ahj_reference}</dd>
          <dt>Lock</dt><dd>{r.lock_type_label}; as wired, {r.failure_state === 'fail_safe' ? 'it unlocks' : 'it stays locked'} on power loss</dd>
          <dt>Egress</dt><dd>{r.egress}</dd>
          <dt>Special locking</dt><dd>{choices.special_locking[r.special_locking] ?? r.special_locking}{r.reader_ul_verified ? ' · UL-verified reader' : ''}</dd>
          <dt>Fire release</dt><dd>{r.fire_release === 'tested' ? `Tested ${day(r.fire_tested_on!)} by ${r.fire_tested_by}` : 'None at this door'}</dd>
          <dt>Checked</dt><dd>Request-to-exit and door contact</dd>
          {r.notes && <><dt>Notes</dt><dd>{r.notes}</dd></>}
        </dl>
      )}
      {canVoid && d.in_service && (
        <div className="pe-row">
          <div className="ph-field"><label htmlFor="void-reason">Needs commissioning again because</label>
            <input id="void-reason" className="ph-input" maxLength={200} placeholder="For example: new lock fitted" value={reason} onChange={(e) => setReason(e.target.value)} /></div>
          <div className="ph-field pe-end">
            <ConfirmButton label="Needs commissioning again" confirm="Take it out of service?" disabled={!reason.trim()}
              onConfirm={async () => { setError(null); try { await api.post(`${base}/doors/${d.door_id}/commissioning/void`, { reason }); await onChanged(); onClose() } catch (e) { setError(message(e)) } }} />
          </div>
        </div>
      )}
      <ErrorText>{error}</ErrorText>
      {history.data && history.data.length > 1 && (
        <details><summary>Earlier records ({history.data.length - 1})</summary>
          <ul className="pe-plain">{history.data.slice(1).map((h) => (
            <li key={h.id} className="pe-item"><span>{day(h.signed_at)}: {h.lock_type_label}, by {h.signed_by}{h.void_reason ? ` · ended: ${h.void_reason}` : ''}</span></li>
          ))}</ul>
        </details>
      )}
      <div className="ph-modal-footer"><button className="ph-btn" onClick={onClose}>Close</button></div>
    </Modal>
  )
}

/** The installer records the door (ARCHITECTURE §7.2) and signs it in their own name. */
export function CommissionDialog({ base, d, choices, onClose, onSaved }: {
  base: string; d: DoorCommissioning; choices: SiteCommissioning; onClose: () => void; onSaved: () => Promise<void>
}) {
  const { api } = useAuth()
  const { current } = useTenant()
  const licenses = useLoad(() => api.get<Licenses>(`/tenants/${current!.id}/licenses`), [api, current?.id])
  const [f, setF] = useState({
    jurisdiction: choices.jurisdiction as string, lock_type: '', failure_state: '', egress: '', special_locking: 'none', reader_ul_verified: false,
    fire_release: '', fire_tested_on: '', fire_tested_by: '', rex_checked: false, contact_checked: false, ahj_reference: '', installer: '',
    license_id: '', notes: '',
  })
  const [problems, setProblems] = useState<string[]>([])
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value })
  const tick = (k: 'rex_checked' | 'contact_checked' | 'reader_ul_verified') => (e: { target: { checked: boolean } }) => setF({ ...f, [k]: e.target.checked })
  const needed = choices.required_license[f.jurisdiction]
  const usable = (licenses.data?.licenses ?? []).filter((l) => l.state === f.jurisdiction && !l.expired)
  const save = async () => {
    setProblems([])
    const body = { ...f, license_id: f.license_id || null, fire_tested_on: f.fire_release === 'tested' ? f.fire_tested_on || null : null }
    try { await api.post(`${base}/doors/${d.door_id}/commissioning`, body); await onSaved(); onClose() } catch (e) {
      const data = (e as { data?: { problems?: string[] } }).data
      setProblems(data?.problems ?? [message(e)])
    }
  }
  return (
    <Modal title={`Commission ${d.door}`} onClose={onClose} wide>
      <p className="ph-hint">A door is in service once its installer records how it was installed and checked, and signs it. The record names you.</p>
      <div className="pe-row">
        <div className="ph-field"><label htmlFor="c-state">State</label>
          <select id="c-state" className="ph-input" value={f.jurisdiction} onChange={set('jurisdiction')}>
            {Object.entries(STATES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></div>
        <div className="ph-field"><label htmlFor="c-ahj">AHJ reference or permit number</label><input id="c-ahj" className="ph-input" value={f.ahj_reference} onChange={set('ahj_reference')} /></div>
      </div>
      <fieldset className="pe-fieldset"><legend>The lock</legend>
        <div className="pe-row">
          <div className="ph-field"><label htmlFor="c-lock">Lock type</label>
            <select id="c-lock" className="ph-input" value={f.lock_type} onChange={set('lock_type')}><option value="">Choose…</option>
              {Object.entries(choices.lock_types).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></div>
          <div className="ph-field"><label htmlFor="c-fail">As wired, on power loss</label>
            <select id="c-fail" className="ph-input" value={f.failure_state} onChange={set('failure_state')}><option value="">Choose…</option>
              <option value="fail_secure">Fail-secure (stays locked)</option><option value="fail_safe">Fail-safe (unlocks)</option></select></div>
        </div>
        <div className="ph-field"><label htmlFor="c-egress">Egress hardware</label><input id="c-egress" className="ph-input" placeholder="For example: lever, free egress" value={f.egress} onChange={set('egress')} /></div>
        <div className="pe-row">
          <div className="ph-field"><label htmlFor="c-special">Special locking</label>
            <select id="c-special" className="ph-input" value={f.special_locking} onChange={set('special_locking')}>
              {Object.entries(choices.special_locking).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></div>
          {f.special_locking !== 'none' && <label className="ph-check pe-end"><input type="checkbox" checked={f.reader_ul_verified} onChange={tick('reader_ul_verified')} /> The reader on the controller is UL-verified</label>}
        </div>
      </fieldset>
      <fieldset className="pe-fieldset"><legend>Checks</legend>
        <div className="ph-field"><label htmlFor="c-fire">Fire release</label>
          <select id="c-fire" className="ph-input" value={f.fire_release} onChange={set('fire_release')}><option value="">Choose…</option>
            <option value="tested">Tested</option><option value="none_present">None at this door</option></select></div>
        {f.fire_release === 'tested' && (
          <div className="pe-row">
            <div className="ph-field"><label htmlFor="c-fire-on">Tested on</label><input id="c-fire-on" type="date" className="ph-input" value={f.fire_tested_on} onChange={set('fire_tested_on')} /></div>
            <div className="ph-field"><label htmlFor="c-fire-by">Tested by</label><input id="c-fire-by" className="ph-input" value={f.fire_tested_by} onChange={set('fire_tested_by')} /></div>
          </div>
        )}
        <label className="ph-check"><input type="checkbox" checked={f.rex_checked} onChange={tick('rex_checked')} /> Request-to-exit checked</label>
        <label className="ph-check"><input type="checkbox" checked={f.contact_checked} onChange={tick('contact_checked')} /> Door contact checked</label>
      </fieldset>
      <fieldset className="pe-fieldset"><legend>The installer</legend>
        <div className="pe-row">
          <div className="ph-field"><label htmlFor="c-installer">Name</label><input id="c-installer" className="ph-input" value={f.installer} onChange={set('installer')} /></div>
          <div className="ph-field"><label htmlFor="c-license">License{needed ? ' (required here)' : ''}</label>
            <select id="c-license" className="ph-input" value={f.license_id} onChange={set('license_id')}>
              <option value="">{needed ? 'Choose…' : 'None needed here'}</option>
              {usable.map((l) => <option key={l.id} value={l.id}>{l.kind_label} {l.number}, {l.holder}</option>)}</select>
            {needed && usable.length === 0 && <span className="ph-hint">No current {STATES[f.jurisdiction]} license is recorded: add it under Settings, Licenses.</span>}</div>
        </div>
      </fieldset>
      <div className="ph-field"><label htmlFor="c-notes">Notes</label><textarea id="c-notes" className="ph-input" rows={2} value={f.notes} onChange={set('notes')} /></div>
      {problems.length > 0 && <ul className="ph-error" role="alert">{problems.map((p) => <li key={p}>{p}</li>)}</ul>}
      <div className="ph-modal-footer">
        <button className="ph-btn" onClick={() => void save()}>Sign and put in service</button>
        <button className="ph-btn ph-btn-ghost" onClick={onClose}>Cancel</button>
      </div>
    </Modal>
  )
}

/** Settings, Licenses: the partner's (its staff record them) and the organization's own. */
export function LicensesPage() {
  const { api } = useAuth()
  const { current } = useTenant()
  const base = `/tenants/${current!.id}/licenses`
  const list = useLoad(() => api.get<Licenses>(base), [api, base])
  const [f, setF] = useState({ owner: 'organization', state: 'WV', kind: '', holder: '', number: '', expires_on: '' })
  const [error, setError] = useState<string | null>(null)
  if (list.error) return <ErrorText>{list.error}</ErrorText>
  if (!list.data) return <Loading what="licenses" />
  const L = list.data
  const owners = [...(L.can_manage_partner ? ['partner'] : []), ...(L.can_manage_organization ? ['organization'] : [])]
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value, ...(k === 'state' ? { kind: '' } : {}) })
  const owner = owners.includes(f.owner) ? f.owner : owners[0]
  const add = async () => {
    setError(null)
    try {
      await api.post(base, { ...f, owner, expires_on: f.expires_on || null })
      setF({ ...f, holder: '', number: '', expires_on: '' })
      await list.reload()
    } catch (e) { setError(message(e)) }
  }
  return (
    <>
      <PageHeader title="Licenses" as="h2" />
      <p className="ph-hint">The licenses commissioning records name (in West Virginia the installer’s SP-LV is required). A partner’s licenses are recorded
        once by its staff and serve every customer; an organization that installs its own doors records its own. Not legal advice: check with the state boards.</p>
      {L.licenses.length === 0 ? <p className="ph-hint">No licenses recorded.</p> : (
        <ul className="pe-plain">
          {L.licenses.map((l) => (
            <li key={l.id} className="pe-item">
              <span><strong>{l.holder}</strong> · {l.state} {l.kind_label} {l.number}{l.expires_on ? ` · to ${day(l.expires_on)}` : ''} <span className="ph-hint">({l.owner === 'partner' ? 'partner' : 'this organization'})</span></span>
              {l.expired ? <StatusBadge tone="error">Expired</StatusBadge> : l.expiring ? <StatusBadge tone="warning">Expires soon</StatusBadge> : null}
              {((l.owner === 'partner' && L.can_manage_partner) || (l.owner === 'organization' && L.can_manage_organization)) && (
                <ConfirmButton small label="Remove" confirm="Remove?" onConfirm={async () => { await api.del(`${base}/${l.id}`); await list.reload() }} />
              )}
            </li>
          ))}
        </ul>
      )}
      {owners.length > 0 && (
        <section className="ph-card" aria-labelledby="lic-h">
          <h3 id="lic-h">Add a license</h3>
          <div className="pe-row">
            {owners.length > 1 && <div className="ph-field"><label htmlFor="lic-owner">Whose</label>
              <select id="lic-owner" className="ph-input" value={owner} onChange={set('owner')}><option value="partner">The partner’s</option><option value="organization">This organization’s</option></select></div>}
            <div className="ph-field"><label htmlFor="lic-state">State</label>
              <select id="lic-state" className="ph-input" value={f.state} onChange={set('state')}>{['PA', 'OH', 'WV'].map((s) => <option key={s} value={s}>{STATES[s]}</option>)}</select></div>
            <div className="ph-field"><label htmlFor="lic-kind">Kind</label>
              <select id="lic-kind" className="ph-input" value={f.kind} onChange={set('kind')}><option value="">Choose…</option>
                {Object.entries(L.kinds[f.state] ?? {}).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></div>
          </div>
          <div className="pe-row">
            <div className="ph-field"><label htmlFor="lic-holder">Holder (as on the license)</label><input id="lic-holder" className="ph-input" value={f.holder} onChange={set('holder')} /></div>
            <div className="ph-field"><label htmlFor="lic-number">Number</label><input id="lic-number" className="ph-input" value={f.number} onChange={set('number')} /></div>
            <div className="ph-field"><label htmlFor="lic-expires">Expires</label><input id="lic-expires" type="date" className="ph-input" value={f.expires_on} onChange={set('expires_on')} /></div>
          </div>
          <ErrorText>{error}</ErrorText>
          <div className="ph-actions"><button className="ph-btn" disabled={!f.kind || !f.holder.trim() || !f.number.trim()} onClick={() => void add()}>Add</button></div>
        </section>
      )}
    </>
  )
}

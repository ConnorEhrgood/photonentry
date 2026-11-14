import { useState } from 'react'
import { ApiError } from '../api/client'
import type { Door, Intercom, IntercomSetup, VoxStation } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { ConfirmButton, ErrorText, Loading, Modal, StatusBadge } from '../components/ui'
import { ago } from '../lib/format'
import { useLoad } from '../lib/useLoad'

/** The models PhotonEntry sets up (api/app/akuvox.py MODELS). */
export const MODELS = ['S532', 'S535', 'S539', 'E18', 'E16V2', 'E12V2', 'X912', 'X915V2', 'R29', 'R20']

function message(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

/** Has the intercom fetched its settings? Until it has, the installer still has to type the setup values into it. */
function fetched(i: Intercom) {
  return i.last_fetch_at
    ? <StatusBadge tone="ok">Set up {ago(i.last_fetch_at)}</StatusBadge>
    : <StatusBadge tone="info">Waiting for the intercom</StatusBadge>
}

/** A site's intercoms (admins only): the door each is at, whether it has fetched its settings, and what the installer types into it. */
export function IntercomsSection({ base, doors }: { base: string; doors: Door[] }) {
  const { api } = useAuth()
  const list = useLoad(() => api.get<Intercom[]>(`${base}/intercoms`), [api, base])
  const [editing, setEditing] = useState<Intercom | 'new' | null>(null)
  const [setupOf, setSetupOf] = useState<Intercom | null>(null)
  const [error, setError] = useState<string | null>(null)
  if (list.error) return <ErrorText>{list.error}</ErrorText>
  if (!list.data) return <Loading what="intercoms" />
  return (
    <section className="pe-section" aria-labelledby="ic-h">
      <div className="pe-head">
        <h2 id="ic-h">Intercoms</h2>
        <button className="ph-btn ph-btn-secondary ph-btn-sm" onClick={() => setEditing('new')}>Add an intercom</button>
      </div>
      <p className="ph-hint">An intercom reads cards for the door’s controller and takes calls; the person answering can open the door from the call.
        PhotonEntry sets it up: add it here, then type its setup values into it once.</p>
      <ErrorText>{error}</ErrorText>
      {list.data.length === 0 ? <p className="ph-hint">No intercoms at this site.</p> : (
        <div className="ph-table-wrap">
          <table className="ph-table pe-table">
            <thead><tr><th>Intercom</th><th>Door</th><th>Model</th><th>Settings</th><th></th></tr></thead>
            <tbody>
              {list.data.map((i) => (
                <tr key={i.id}>
                  <td className="pe-who" data-label="Intercom"><strong>{i.name}</strong><span className="ph-hint"> {i.mac}</span></td>
                  <td data-label="Door">{i.door}</td>
                  <td data-label="Model">Akuvox {i.model}</td>
                  <td data-label="Settings">{fetched(i)}{!i.relay_target && <span className="ph-hint"> The controller has not said where the intercom reaches it.</span>}</td>
                  <td data-label=""><div className="pe-actions-cell">
                    <button className="ph-btn ph-btn-ghost ph-btn-sm" onClick={() => setSetupOf(i)}>Setup values</button>
                    <button className="ph-btn ph-btn-ghost ph-btn-sm" onClick={() => setEditing(i)}>Change</button>
                    <ConfirmButton small label="Remove" confirm="Remove?" onConfirm={async () => {
                      setError(null)
                      try { await api.del(`${base}/intercoms/${i.id}`); await list.reload() } catch (e) { setError(message(e)) }
                    }} />
                  </div></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {editing && <IntercomDialog base={base} doors={doors} intercom={editing === 'new' ? null : editing} onClose={() => setEditing(null)}
        onSaved={async (made) => { await list.reload(); if (made) setSetupOf(made) }} />}
      {setupOf && <SetupDialog base={base} intercom={setupOf} onClose={() => setSetupOf(null)} />}
    </section>
  )
}

/** Add or change an intercom. A new one opens its setup values straight away. */
export function IntercomDialog({ base, doors, intercom, onClose, onSaved }: {
  base: string; doors: Door[]; intercom: Intercom | null; onClose: () => void; onSaved: (made: Intercom | null) => Promise<void>
}) {
  const { api } = useAuth()
  // PhotonVox's door stations, when the organization has connected it (404: not connected; the account is then typed in).
  const stations = useLoad(async () => {
    try { return await api.get<VoxStation[]>(`${base.split('/sites/')[0]}/integrations/vox/stations`) } catch (e) {
      if (e instanceof ApiError && e.status === 404) return null
      throw e
    }
  }, [api, base])
  const [f, setF] = useState({
    name: intercom?.name ?? '', door_id: intercom?.door_id ?? doors[0]?.id ?? '', model: intercom?.model ?? 'S532', mac: intercom?.mac ?? '',
    sip_server: intercom?.sip_server ?? '', sip_port: String(intercom?.sip_port ?? 5061), sip_transport: intercom?.sip_transport ?? 'tls',
    sip_user: intercom?.sip_user ?? '', sip_password: '', relay_address: intercom?.relay_address ?? '', vox_station_id: intercom?.vox_station_id ?? '',
  })
  const fromVox = !!f.vox_station_id
  const [error, setError] = useState<string | null>(null)
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value })
  const save = async () => {
    setError(null)
    const { sip_password, sip_port, sip_server, sip_transport, sip_user, ...rest } = f
    const body: Record<string, unknown> = { ...rest, name: f.name.trim() }
    if (!fromVox) {                                                       // a door station's account is PhotonVox's, never typed
      Object.assign(body, { sip_server, sip_transport, sip_user, sip_port: Number(sip_port) })
      if (!intercom || sip_password) body.sip_password = sip_password    // unchanged unless typed
    }
    if (!intercom && !fromVox) delete body.vox_station_id
    try {
      if (intercom) { await api.patch(`${base}/intercoms/${intercom.id}`, body); await onSaved(null) }
      else await onSaved(await api.post<Intercom>(`${base}/intercoms`, body))
      onClose()
    } catch (e) { setError(message(e)) }
  }
  return (
    <Modal title={intercom ? `Change ${intercom.name}` : 'Add an intercom'} onClose={onClose} wide>
      <div className="pe-row">
        <div className="ph-field"><label htmlFor="ic-name">Name</label><input id="ic-name" className="ph-input" placeholder="Front door intercom" value={f.name} onChange={set('name')} /></div>
        <div className="ph-field"><label htmlFor="ic-door">Door</label>
          <select id="ic-door" className="ph-input" value={f.door_id} onChange={set('door_id')}>{doors.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</select></div>
      </div>
      <div className="pe-row">
        <div className="ph-field"><label htmlFor="ic-model">Akuvox model</label>
          <select id="ic-model" className="ph-input" value={f.model} onChange={set('model')}>{MODELS.map((m) => <option key={m}>{m}</option>)}</select></div>
        <div className="ph-field"><label htmlFor="ic-mac">MAC address</label><input id="ic-mac" className="ph-input" placeholder="0C:11:05:AA:BB:CC" value={f.mac} onChange={set('mac')} />
          <span className="ph-hint">On the label on its back, or its web page.</span></div>
      </div>
      <fieldset className="pe-fieldset">
        <legend>Calls</legend>
        {stations.data && (
          <div className="ph-field"><label htmlFor="ic-station">Door station in PhotonVox</label>
            <select id="ic-station" className="ph-input" value={f.vox_station_id} onChange={set('vox_station_id')}>
              <option value="">None: type its phone account</option>
              {stations.data.map((st) => <option key={st.id} value={st.id}>{st.name} ({st.extension})</option>)}
            </select>
            {fromVox && <span className="ph-hint">Its phone account comes from PhotonVox and is kept current.</span>}</div>
        )}
        {stations.error && <p className="ph-hint" role="status">PhotonVox’s door stations can’t be listed right now: {stations.error}</p>}
        {!fromVox && (
          <>
            <div className="pe-row">
              <div className="ph-field"><label htmlFor="ic-sip-server">Server</label><input id="ic-sip-server" className="ph-input" value={f.sip_server} onChange={set('sip_server')} /></div>
              <div className="ph-field"><label htmlFor="ic-sip-port">Port</label><input id="ic-sip-port" type="number" min={1} max={65535} className="ph-input" value={f.sip_port} onChange={set('sip_port')} /></div>
              <div className="ph-field"><label htmlFor="ic-sip-transport">Transport</label>
                <select id="ic-sip-transport" className="ph-input" value={f.sip_transport} onChange={set('sip_transport')}>
                  <option value="tls">TLS</option><option value="tcp">TCP</option><option value="udp">UDP</option></select></div>
            </div>
            <div className="pe-row">
              <div className="ph-field"><label htmlFor="ic-sip-user">User</label><input id="ic-sip-user" className="ph-input" value={f.sip_user} onChange={set('sip_user')} /></div>
              <div className="ph-field"><label htmlFor="ic-sip-pass">Password</label>
                <input id="ic-sip-pass" type="password" autoComplete="new-password" className="ph-input" value={f.sip_password} onChange={set('sip_password')}
                  placeholder={intercom?.sip_password_set ? 'Unchanged' : ''} /></div>
            </div>
          </>
        )}
      </fieldset>
      <details>
        <summary>Advanced</summary>
        <div className="ph-field"><label htmlFor="ic-relay">Controller address for unlocking (address:port)</label>
          <input id="ic-relay" className="ph-input" placeholder={intercom?.relay_target || '10.152.0.20:8742'} value={f.relay_address} onChange={set('relay_address')} />
          <span className="ph-hint">Leave empty to use the address the door’s controller reports.</span></div>
      </details>
      <ErrorText>{error}</ErrorText>
      <div className="ph-modal-footer">
        <button className="ph-btn" disabled={!f.name.trim() || !f.door_id || !f.mac.trim()} onClick={() => void save()}>Save</button>
        <button className="ph-btn ph-btn-ghost" onClick={onClose}>Cancel</button>
      </div>
    </Modal>
  )
}

/** What the installer types into the intercom once. Seeing it is recorded in the audit trail. */
export function SetupDialog({ base, intercom, onClose }: { base: string; intercom: Intercom; onClose: () => void }) {
  const { api } = useAuth()
  const setup = useLoad(() => api.get<IntercomSetup>(`${base}/intercoms/${intercom.id}/setup`), [api, base, intercom.id])
  return (
    <Modal title={`Set up ${intercom.name}`} onClose={onClose} wide>
      {setup.error ? <ErrorText>{setup.error}</ErrorText> : !setup.data ? <Loading what="the setup values" /> : (
        <>
          <ol className="pe-howto">
            <li>Connect the intercom to the door’s network and open its web page (user admin, password admin when new).</li>
            <li>On its <strong>Autop</strong> page, turn PnP off, set the manual provisioning address below, and set it to check every hour.</li>
            <li>Restart it. It fetches its settings within a minute; this page then says “Set up”.</li>
          </ol>
          <dl className="pe-setup">
            <dt>Provisioning address</dt><dd><code className="pe-code pe-secret">{setup.data.provision_url}</code></dd>
            <dt>Its web page afterward</dt><dd>User <code className="pe-code">{setup.data.admin_user}</code>, password <code className="pe-code pe-secret">{setup.data.admin_password}</code></dd>
            <dt>Opening the door from a call</dt><dd>The person answering presses <kbd>{setup.data.unlock_code}</kbd>.</dd>
          </dl>
          <p className="ph-hint">Its settings replace the admin password, so keep this one. Anyone with the provisioning address can read this intercom’s settings: don’t share it.</p>
        </>
      )}
      <div className="ph-modal-footer"><button className="ph-btn" onClick={onClose}>Done</button></div>
    </Modal>
  )
}

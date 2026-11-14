import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import logo from '../assets/photon-logo.png'
import type { PassPage, VisitorPass } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { useTenant } from '../auth/TenantContext'
import { SitePicker, useSite, useSites } from '../components/sites'
import { ConfirmButton, ErrorText, Loading, Modal, PageHeader, StatusBadge } from '../components/ui'
import { useLoad } from '../lib/useLoad'

const STATE: Record<VisitorPass['state'], { tone: 'ok' | 'info' | 'warning' | 'error'; text: string }> = {
  active: { tone: 'ok', text: 'Active' }, upcoming: { tone: 'info', text: 'Upcoming' }, over: { tone: 'info', text: 'Over' }, revoked: { tone: 'error', text: 'Revoked' },
}
const when = (iso: string) => new Date(iso).toLocaleString(undefined, { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
/** A datetime-local value (the browser's local time) for a moment `hours` from now, to the minute (a pass made at the desk works at once). */
const local = (hours: number) => {
  const d = new Date(Date.now() + hours * 3_600_000)
  d.setSeconds(0, 0)
  return new Date(d.getTime() - d.getTimezoneOffset() * 60_000).toISOString().slice(0, 16)
}

/** Visitors' passes at a site: the front desk issues one (a PIN, and a link for the visitor), and revokes it. */
export function VisitorsPage() {
  const { api } = useAuth()
  const { current } = useTenant()
  const t = current!.id
  const sites = useSites()
  const [site, pick] = useSite(sites.data)
  const base = site ? `/tenants/${t}/sites/${site.id}` : ''
  const list = useLoad(() => (site ? api.get<VisitorPass[]>(`${base}/passes`) : Promise.resolve([])), [api, base])
  const [making, setMaking] = useState(false)
  const [made, setMade] = useState<VisitorPass | null>(null)
  const [error, setError] = useState<string | null>(null)
  if (sites.error || list.error) return <ErrorText>{sites.error || list.error}</ErrorText>
  if (!sites.data || !list.data) return <Loading what="visitors' passes" />
  return (
    <>
      <PageHeader title="Visitors">
        <SitePicker sites={sites.data} site={site} onPick={pick} />
        {site && <button className="ph-btn" onClick={() => setMaking(true)}>Make a pass</button>}
      </PageHeader>
      <p className="ph-hint">A pass lets a visitor in with a PIN through the doors of one group, for the hours you choose (at most 31 days). The visitor gets a link
        to their pass; revoke it and it stops working at once.</p>
      <ErrorText>{error}</ErrorText>
      {list.data.length === 0 ? <div className="ph-empty"><p>No passes at {site?.name} yet.</p></div> : (
        <div className="ph-table-wrap">
          <table className="ph-table pe-table">
            <thead><tr><th>Visitor</th><th>When</th><th>Doors</th><th>State</th><th></th></tr></thead>
            <tbody>
              {list.data.map((p) => (
                <tr key={p.id}>
                  <td className="pe-who" data-label="Visitor"><strong>{p.visitor_name}</strong><span className="ph-hint"> by {p.host}</span></td>
                  <td data-label="When">{when(p.valid_from)} to {when(p.valid_to)}</td>
                  <td data-label="Doors">{p.group}</td>
                  <td data-label="State"><StatusBadge tone={STATE[p.state].tone}>{STATE[p.state].text}</StatusBadge></td>
                  <td data-label="">{(p.state === 'active' || p.state === 'upcoming') && (
                    <ConfirmButton small label="Revoke" confirm="Revoke this pass now?" onConfirm={async () => {
                      setError(null)
                      try { await api.post(`${base}/passes/${p.id}/revoke`); await list.reload() } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
                    }} />
                  )}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {making && site && <PassDialog base={base} siteName={site.name} onClose={() => setMaking(false)} onMade={async (p) => { setMade(p); await list.reload() }} />}
      {made && (
        <Modal title={`Pass for ${made.visitor_name}`} onClose={() => setMade(null)}>
          <p>{made.emailed ? `It was emailed to ${made.visitor_email}.` : 'Give the visitor this link (or read them the PIN).'}</p>
          <dl className="pe-setup">
            {made.qr && <><dt>QR code</dt><dd><img className="pe-qr pe-qr-sm" src={made.qr} alt={`QR code for ${made.visitor_name}'s pass`} /></dd></>}
            <dt>PIN</dt><dd><code className="pe-code pe-secret pe-pin">{made.pin}</code></dd>
            <dt>Link</dt><dd><code className="pe-code pe-secret">{made.link}</code></dd>
            <dt>When</dt><dd>{when(made.valid_from)} to {when(made.valid_to)}, {made.group}</dd>
          </dl>
          <div className="ph-modal-footer"><button className="ph-btn" onClick={() => setMade(null)}>Done</button></div>
        </Modal>
      )}
    </>
  )
}

function PassDialog({ base, siteName, onClose, onMade }: { base: string; siteName: string; onClose: () => void; onMade: (p: VisitorPass) => Promise<void> }) {
  const { api } = useAuth()
  const groups = useLoad(() => api.get<{ id: string; name: string }[]>(`${base}/visitor-groups`), [api, base])
  const [f, setF] = useState({ visitor_name: '', visitor_email: '', group_id: '', valid_from: local(0), valid_to: local(8) })
  const [error, setError] = useState<string | null>(null)
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value })
  const group = f.group_id || groups.data?.[0]?.id || ''
  const save = async () => {
    setError(null)
    try {
      const p = await api.post<VisitorPass>(`${base}/passes`, { visitor_name: f.visitor_name.trim(), visitor_email: f.visitor_email.trim() || null, group_id: group,
        valid_from: new Date(f.valid_from).toISOString(), valid_to: new Date(f.valid_to).toISOString() })
      await onMade(p)
      onClose()
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
  }
  return (
    <Modal title={`A pass for ${siteName}`} onClose={onClose}>
      {groups.data && groups.data.length === 0 ? <p className="ph-hint">No access group here is open to visitors yet: an admin opens one on the Access page.</p> : (
        <>
          <div className="ph-field"><label htmlFor="pass-name">Visitor’s name</label><input id="pass-name" className="ph-input" value={f.visitor_name} onChange={set('visitor_name')} /></div>
          <div className="ph-field"><label htmlFor="pass-email">Their email (optional)</label><input id="pass-email" type="email" className="ph-input" value={f.visitor_email} onChange={set('visitor_email')} />
            <span className="ph-hint">They get the link to their pass.</span></div>
          <div className="ph-field"><label htmlFor="pass-group">Doors</label>
            <select id="pass-group" className="ph-input" value={group} onChange={set('group_id')}>{(groups.data ?? []).map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}</select></div>
          <div className="pe-row">
            <div className="ph-field"><label htmlFor="pass-from">From</label><input id="pass-from" type="datetime-local" className="ph-input" value={f.valid_from} onChange={set('valid_from')} /></div>
            <div className="ph-field"><label htmlFor="pass-to">Until</label><input id="pass-to" type="datetime-local" className="ph-input" value={f.valid_to} onChange={set('valid_to')} /></div>
          </div>
        </>
      )}
      <ErrorText>{error}</ErrorText>
      <div className="ph-modal-footer">
        <button className="ph-btn" disabled={!f.visitor_name.trim() || !group} onClick={() => void save()}>Make the pass</button>
        <button className="ph-btn ph-btn-ghost" onClick={onClose}>Cancel</button>
      </div>
    </Modal>
  )
}

/** The visitor's own page (no sign-in): where, when, and the PIN while the pass is good. */
export function PassPageRoute() {
  const { token = '' } = useParams()
  const { api } = useAuth()                 // with no session the client sends no token: the link's token is the secret
  const [page, setPage] = useState<PassPage | null>(null)
  const [missing, setMissing] = useState(false)
  useEffect(() => {
    let live = true
    api.get<PassPage>(`/passes/v1/${encodeURIComponent(token)}`)
      .then((p) => { if (live) setPage(p) })
      .catch(() => { if (live) setMissing(true) })
    return () => { live = false }
  }, [api, token])
  const tz = page?.timezone
  const at = (iso: string) => new Date(iso).toLocaleString(undefined, { weekday: 'long', month: 'long', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZone: tz })
  return (
    <div className="ph-auth">
      <div className="ph-card pe-pass">
        <img className="ph-auth-logo" src={logo} alt="Photon" />
        {missing ? <><h1>No such pass</h1><p>Check the link, or ask the person who invited you.</p></>
          : !page ? <p role="status">Loading your pass…</p> : (
            <>
              <h1>{page.visitor_name}</h1>
              <p><strong>{page.site}</strong>{page.address ? <><br />{page.address}</> : null}</p>
              <p>{at(page.valid_from)} to {at(page.valid_to)}<br /><span className="ph-hint">Invited by {page.host}</span></p>
              {page.pin ? (
                <>
                  {page.qr && (
                    <>
                      <p className="ph-hint">Show this to the intercom’s camera</p>
                      <img className="pe-qr" src={page.qr} alt="Your pass's QR code" />
                    </>
                  )}
                  <p className="ph-hint">{page.qr ? 'or, at the door’s keypad, enter' : 'At the door’s keypad, enter'}</p>
                  <p className="pe-pass-pin" aria-label="Your PIN">{page.pin}</p>
                  {page.state === 'upcoming' && <p className="ph-hint">It works from the time above.</p>}
                </>
              ) : <p className="ph-banner ph-banner-warning" role="status">{page.state === 'revoked' ? 'This pass was revoked.' : 'This pass is over.'}</p>}
            </>
          )}
      </div>
    </div>
  )
}

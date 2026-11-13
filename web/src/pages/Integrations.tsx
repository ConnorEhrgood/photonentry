import { useState } from 'react'
import { useAuth } from '../auth/AuthContext'
import { useTenant } from '../auth/TenantContext'
import { config } from '../config'
import { ConfirmButton, ErrorText, Loading, PageHeader, StatusBadge } from '../components/ui'
import { ago } from '../lib/format'
import { useLoad } from '../lib/useLoad'

interface GuardView {
  connected: boolean
  enabled: boolean
  token_hint: string | null
  last_ok_at: string | null
  last_error: string
  last_error_at: string | null
  sent: number
  guard_api_url: string
  bindings: { door_id: string; door: string; site: string; binding: string }[]
}

/** PhotonGuard: the doors' events on the cameras that see them, and forced or held-open doors as alarms (ARCHITECTURE §9.1). */
export function GuardSettingsPage() {
  const { api } = useAuth()
  const { current } = useTenant()
  const base = `/tenants/${current!.id}/integrations/guard`
  const view = useLoad(() => api.get<GuardView>(base), [api, base])
  const [token, setToken] = useState('')
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null)
  const [error, setError] = useState<string | null>(null)
  if (view.error) return <ErrorText>{view.error}</ErrorText>
  if (!view.data) return <Loading what="the PhotonGuard connection" />
  const v = view.data
  const run = async (what: () => Promise<unknown>) => {
    setError(null)
    try { await what(); await view.reload() } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
  }
  const state = !v.connected ? <StatusBadge tone="info">Not connected</StatusBadge>
    : !v.enabled ? <StatusBadge tone="warning">Paused</StatusBadge>
      : v.last_error ? <StatusBadge tone="error">Not sending</StatusBadge> : <StatusBadge tone="ok">Sending</StatusBadge>
  return (
    <>
      <PageHeader title="PhotonGuard" as="h2" />
      <section className="ph-card" aria-labelledby="guard-h">
        <h3 id="guard-h">Door events on your cameras {state}</h3>
        <p className="ph-hint">Grants and denials appear on the cameras that see each door, each with its clip; a door forced or held open becomes an alarm in PhotonGuard.
          Make an ingest token in PhotonGuard (it needs “events: write”) and paste it here.</p>
        {v.connected && (
          <p>Token {v.token_hint}; {v.sent} events sent{v.last_ok_at ? `, the last ${ago(v.last_ok_at)}` : ''}.</p>
        )}
        {v.last_error && <p className="ph-banner ph-banner-error" role="alert">{v.last_error}{v.last_error_at ? ` (${ago(v.last_error_at)})` : ''}. Sending resumes from where it stopped.</p>}
        <div className="ph-field">
          <label htmlFor="guard-token">{v.connected ? 'Replace the ingest token' : 'Ingest token'}</label>
          <input id="guard-token" className="ph-input" autoComplete="off" value={token} onChange={(e) => setToken(e.target.value)} />
        </div>
        {note && <p className={`ph-banner ph-banner-${note.ok ? 'ok' : 'error'}`} role="status">{note.text}</p>}
        <ErrorText>{error}</ErrorText>
        <div className="ph-actions">
          <button className="ph-btn" disabled={token.trim().length < 20} onClick={() => void run(async () => { await api.put(base, { token: token.trim() }); setToken('') })}>
            {v.connected ? 'Replace' : 'Connect'}
          </button>
          {v.connected && <button className="ph-btn ph-btn-secondary" onClick={() => void run(async () => {
            const r = await api.post<{ ok: boolean; detail: string }>(`${base}/test`)
            setNote({ ok: r.ok, text: r.detail })
          })}>Send a test event</button>}
          {v.connected && <button className="ph-btn ph-btn-secondary" onClick={() => void run(() => api.patch(base, { enabled: !v.enabled }))}>{v.enabled ? 'Pause' : 'Resume'}</button>}
          {v.connected && <ConfirmButton danger label="Disconnect" confirm="Stop sending and forget the token?" onConfirm={() => run(() => api.del(base))} />}
        </div>
      </section>
      {v.connected && (
        <section aria-labelledby="bind-h" className="pe-section">
          <h3 id="bind-h">Bind each door to its cameras</h3>
          <p className="ph-hint">In PhotonGuard, add a binding with each name below and choose the cameras that see that door.</p>
          <div className="ph-table-wrap">
            <table className="ph-table pe-table">
              <thead><tr><th>Door</th><th>Site</th><th>Binding name</th></tr></thead>
              <tbody>
                {v.bindings.map((b) => (
                  <tr key={b.door_id}>
                    <td className="pe-who" data-label="Door">{b.door}</td>
                    <td data-label="Site">{b.site}</td>
                    <td data-label="Binding"><code className="pe-code">{b.binding}</code></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </>
  )
}

interface FeedToken { id: string; name: string; console_tenant_id: string | null; created_at: string; last_used_at: string | null; revoked: boolean }

/** PhotonConsole: the doors and controllers beside the rest of the building, through a read-only feed (ARCHITECTURE §9.5). */
export function ConsoleSettingsPage() {
  const { api } = useAuth()
  const { current } = useTenant()
  const base = `/tenants/${current!.id}/integrations/console/tokens`
  const tokens = useLoad(() => api.get<FeedToken[]>(base), [api, base])
  const [name, setName] = useState('PhotonConsole')
  const [consoleTenant, setConsoleTenant] = useState('')
  const [made, setMade] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  if (tokens.error) return <ErrorText>{tokens.error}</ErrorText>
  if (!tokens.data) return <Loading what="feed tokens" />
  const make = async () => {
    setError(null)
    try {
      const r = await api.post<{ token: string }>(base, { name: name.trim(), console_tenant_id: consoleTenant.trim() || null })
      setMade(r.token)
      await tokens.reload()
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
  }
  const live = tokens.data.filter((t) => !t.revoked)
  return (
    <>
      <PageHeader title="PhotonConsole" as="h2" />
      <section className="ph-card" aria-labelledby="console-h">
        <h3 id="console-h">A feed for PhotonConsole</h3>
        <p className="ph-hint">In PhotonConsole, add a PhotonEntry data source with the address and token below. It reads door state, alarms and controller health, never people.</p>
        <p>Address: <code className="pe-code">{config.apiUrl}/integrations/console/v1/doors</code></p>
        <div className="pe-row">
          <div className="ph-field"><label htmlFor="feed-name">Name</label><input id="feed-name" className="ph-input" value={name} onChange={(e) => setName(e.target.value)} /></div>
          <div className="ph-field"><label htmlFor="feed-tenant">PhotonConsole tenant id (optional)</label>
            <input id="feed-tenant" className="ph-input" value={consoleTenant} onChange={(e) => setConsoleTenant(e.target.value)} /></div>
        </div>
        {made && <div className="ph-banner ph-banner-ok" role="status"><p>Copy the token now: it is not shown again.</p><code className="pe-code pe-secret">{made}</code></div>}
        <ErrorText>{error}</ErrorText>
        <div className="ph-actions"><button className="ph-btn" disabled={!name.trim()} onClick={() => void make()}>Make a token</button></div>
      </section>
      {live.length > 0 && (
        <ul className="pe-plain">
          {live.map((t) => (
            <li key={t.id} className="pe-item">
              <strong>{t.name}</strong> <span className="ph-hint">{t.last_used_at ? `used ${ago(t.last_used_at)}` : 'not used yet'}</span>
              <ConfirmButton small danger label="Revoke" confirm="Revoke this token?" onConfirm={async () => { await api.del(`${base}/${t.id}`); await tokens.reload() }} />
            </li>
          ))}
        </ul>
      )}
    </>
  )
}

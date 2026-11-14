import { useEffect, useState } from 'react'
import { useAuth } from '../auth/AuthContext'
import { useTenant } from '../auth/TenantContext'
import { DIRECTORY_URL } from '../components/Layout'
import { ErrorText, Loading, PageHeader, StatusBadge } from '../components/ui'
import { useLoad } from '../lib/useLoad'

interface MyDoor { door_id: string; door: string; site_id: string; site: string; can_open: boolean; why: string; why_text: string }
interface MyDoors { linked: boolean; doors: MyDoor[] }
interface CommandState { id: string; done: boolean; ok: boolean | null; error: string; expired: boolean }

/** How often an opening is checked on while the controller carries it out (it usually takes a second or two). */
export const OPEN_POLL_MS = 1000

/** The doors the signed-in person may open from their phone (decision 25): their own cardholder's doors, as their card would open them now. */
export function MyDoorsPage() {
  const { api } = useAuth()
  const { current } = useTenant()
  const base = `/tenants/${current!.id}/my`
  const mine = useLoad(() => api.get<MyDoors>(`${base}/doors`), [api, base])
  if (mine.error) return <ErrorText>{mine.error}</ErrorText>
  if (!mine.data) return <Loading what="your doors" />
  const bySite = new Map<string, MyDoor[]>()
  for (const d of mine.data.doors) bySite.set(d.site, [...(bySite.get(d.site) ?? []), d])
  return (
    <>
      <PageHeader title="My doors" />
      {!mine.data.linked ? (
        <div className="ph-empty"><p>Your PhotonID account isn’t linked to a cardholder at {current!.name} yet.</p>
          <p className="ph-hint">Ask whoever manages access there to link it (or to add you with this email address).</p></div>
      ) : mine.data.doors.length === 0 ? (
        <div className="ph-empty"><p>No doors yet: your access doesn’t include any door here.</p></div>
      ) : [...bySite.entries()].map(([site, doors]) => (
        <section key={site} className="pe-section" aria-label={site}>
          {bySite.size > 1 && <h2>{site}</h2>}
          <ul className="pe-plain pe-mydoors">
            {doors.map((d) => <DoorButton key={d.door_id} base={base} door={d} />)}
          </ul>
        </section>
      ))}
      <p className="ph-hint pe-mydoors-hint">Opens the door for its usual few seconds, through the internet: your phone and the site both need to be online.
        Your account is managed in <a href={DIRECTORY_URL}>PhotonID</a>.</p>
    </>
  )
}

function DoorButton({ base, door }: { base: string; door: MyDoor }) {
  const { api } = useAuth()
  const [command, setCommand] = useState<string | null>(null)
  const [state, setState] = useState<'idle' | 'sending' | 'opened' | 'failed'>('idle')
  const [message, setMessage] = useState('')
  useEffect(() => {
    if (!command) return
    let live = true
    const check = async () => {
      try {
        const c = await api.get<CommandState>(`${base}/commands/${command}`)
        if (!live) return
        if (c.done) { setState(c.ok ? 'opened' : 'failed'); setMessage(c.ok ? 'Opened' : `The door did not open${c.error ? `: ${c.error}` : ''}`); setCommand(null) }
        else if (c.expired) { setState('failed'); setMessage('The door’s controller did not answer in time'); setCommand(null) }
      } catch (e) { if (live) { setState('failed'); setMessage(e instanceof Error ? e.message : String(e)); setCommand(null) } }
    }
    const t = setInterval(() => void check(), OPEN_POLL_MS)
    return () => { live = false; clearInterval(t) }
  }, [api, base, command])
  const open = async () => {
    setState('sending')
    setMessage('Opening…')
    try { setCommand((await api.post<{ id: string }>(`${base}/doors/${door.door_id}/open`)).id) } catch (e) {
      setState('failed')
      setMessage(e instanceof Error ? e.message : String(e))
    }
  }
  return (
    <li className="pe-mydoor">
      <div>
        <strong>{door.door}</strong>
        {!door.can_open && <> <StatusBadge tone={door.why === 'locked_down' ? 'error' : 'info'}>{door.why_text}</StatusBadge></>}
        {message && <p className={state === 'failed' ? 'ph-error' : 'ph-hint'} role="status">{message}</p>}
      </div>
      <button className="ph-btn pe-open" disabled={!door.can_open || state === 'sending'} onClick={() => void open()}>
        {state === 'sending' ? 'Opening…' : 'Open'}
      </button>
    </li>
  )
}

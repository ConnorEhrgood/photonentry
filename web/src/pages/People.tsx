import { useState } from 'react'
import type { Cardholder, Credential, Group, Site } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { useTenant } from '../auth/TenantContext'
import { useSites } from '../components/sites'
import { ConfirmButton, ErrorText, Loading, Modal, PageHeader, StatusBadge } from '../components/ui'
import { useLoad } from '../lib/useLoad'

/** Every site's access groups, for naming a cardholder's groups and choosing them. */
function useAllGroups(sites: Site[] | null) {
  const { api } = useAuth()
  const { current } = useTenant()
  return useLoad(async () => {
    const out: (Group & { site: Site })[] = []
    for (const s of sites ?? []) for (const g of await api.get<Group[]>(`/tenants/${current!.id}/sites/${s.id}/groups`)) out.push({ ...g, site: s })
    return out
  }, [api, current?.id, sites])
}

/** The people who open doors (cardholders: PhotonEntry's own records), their groups and their cards and PINs. */
export function PeoplePage() {
  const { api } = useAuth()
  const { current, can } = useTenant()
  const t = current!.id
  const sites = useSites()
  const groups = useAllGroups(sites.data)
  const people = useLoad(() => api.get<Cardholder[]>(`/tenants/${t}/cardholders`), [api, t])
  const [open, setOpen] = useState<Cardholder | 'new' | null>(null)
  const [filter, setFilter] = useState('')
  if (people.error) return <ErrorText>{people.error}</ErrorText>
  if (!people.data) return <Loading what="people" />
  const groupName = (id: string) => groups.data?.find((g) => g.id === id)
  const multi = (sites.data?.length ?? 0) > 1
  const shown = people.data.filter((p) => !filter || `${p.name} ${p.ref ?? ''} ${p.email}`.toLowerCase().includes(filter.toLowerCase()))
  return (
    <>
      <PageHeader title="People">
        {can('entry.cardholders.manage') && <button className="ph-btn" onClick={() => setOpen('new')}>Add a person</button>}
      </PageHeader>
      {people.data.length > 5 && (
        <div className="ph-field pe-filter"><label htmlFor="people-filter">Find</label>
          <input id="people-filter" className="ph-input" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Name, reference or email" /></div>
      )}
      {people.data.length === 0 ? (
        <div className="ph-empty"><p>No one has access yet. Add people here, or import a spreadsheet in <strong>Set up a site</strong>.</p></div>
      ) : (
        <div className="ph-table-wrap">
          <table className="ph-table pe-table">
            <thead><tr><th>Name</th><th>Reference</th><th>Access groups</th><th>State</th></tr></thead>
            <tbody>
              {shown.map((p) => (
                <tr key={p.id}>
                  <td className="pe-who" data-label="Name">
                    {can('entry.cardholders.manage') ? <button className="ph-link-button" onClick={() => setOpen(p)}>{p.name}</button> : p.name}
                  </td>
                  <td data-label="Reference">{p.ref ?? ''}</td>
                  <td data-label="Groups">{p.groups.map((id) => { const g = groupName(id); return g ? (multi ? `${g.name} (${g.site.name})` : g.name) : null }).filter(Boolean).join(', ') || <span className="ph-hint">None</span>}</td>
                  <td data-label="State">{p.suspended ? <StatusBadge tone="warning">Suspended</StatusBadge> : <StatusBadge tone="ok">Active</StatusBadge>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {open && <PersonDialog person={open === 'new' ? null : open} groups={groups.data ?? []} multi={multi}
        onClose={() => setOpen(null)} onSaved={async () => { await people.reload() }} />}
    </>
  )
}

function PersonDialog({ person, groups, multi, onClose, onSaved }: {
  person: Cardholder | null; groups: (Group & { site: Site })[]; multi: boolean; onClose: () => void; onSaved: () => Promise<void>
}) {
  const { api } = useAuth()
  const { current, can } = useTenant()
  const t = current!.id
  const [name, setName] = useState(person?.name ?? '')
  const [ref, setRef] = useState(person?.ref ?? '')
  const [email, setEmail] = useState(person?.email ?? '')
  const [suspended, setSuspended] = useState(person?.suspended ?? false)
  const [chosen, setChosen] = useState<string[]>(person?.groups ?? [])
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState<Cardholder | null>(person)
  const save = async () => {
    setError(null)
    try {
      const body = { name: name.trim(), ref: ref.trim() || null, email: email.trim(), suspended }
      const p = saved ? await api.patch<Cardholder>(`/tenants/${t}/cardholders/${saved.id}`, body) : await api.post<Cardholder>(`/tenants/${t}/cardholders`, body)
      const withGroups = await api.put<Cardholder>(`/tenants/${t}/cardholders/${p.id}/groups`, { group_ids: chosen })
      setSaved(withGroups)
      await onSaved()
      if (!saved) return            // a new person: stay, so a card or PIN can be added next
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }
  return (
    <Modal title={person ? person.name : 'Add a person'} onClose={onClose} wide>
      <div className="pe-row">
        <div className="ph-field"><label htmlFor="p-name">Name</label><input id="p-name" className="ph-input" value={name} onChange={(e) => setName(e.target.value)} /></div>
        <div className="ph-field"><label htmlFor="p-ref">Reference</label><input id="p-ref" className="ph-input" value={ref} onChange={(e) => setRef(e.target.value)} placeholder="Employee or unit number" /></div>
        <div className="ph-field"><label htmlFor="p-email">Email</label><input id="p-email" className="ph-input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} /></div>
      </div>
      <fieldset className="pe-fieldset">
        <legend>Access groups</legend>
        {groups.length === 0 && <p className="ph-hint">No access groups yet: set up a site first.</p>}
        {groups.map((g) => (
          <label key={g.id} className="ph-check">
            <input type="checkbox" checked={chosen.includes(g.id)} onChange={(e) => setChosen(e.target.checked ? [...chosen, g.id] : chosen.filter((x) => x !== g.id))} />
            {' '}{g.name}{multi ? ` (${g.site.name})` : ''}
          </label>
        ))}
      </fieldset>
      {saved && <label className="ph-check"><input type="checkbox" checked={suspended} onChange={(e) => setSuspended(e.target.checked)} /> Suspended (every card and PIN stops working)</label>}
      <ErrorText>{error}</ErrorText>
      <div className="ph-modal-footer">
        <button className="ph-btn" disabled={!name.trim()} onClick={() => void save()}>{saved ? 'Save' : 'Add'}</button>
        <button className="ph-btn ph-btn-ghost" onClick={onClose}>Close</button>
      </div>
      {saved && can('entry.credential.issue') && <Credentials holder={saved} />}
    </Modal>
  )
}

const FORMATS = [{ key: 'h10301', label: '26-bit (facility + number)' }, { key: 'w34', label: '34-bit (intercom readers)' }, { key: 'raw', label: 'Raw number' }]

/** A person's cards and PINs. A card number and a PIN are never shown again after they are entered: a card shows its last digits. */
function Credentials({ holder }: { holder: Cardholder }) {
  const { api } = useAuth()
  const { current } = useTenant()
  const base = `/tenants/${current!.id}/cardholders/${holder.id}/credentials`
  const list = useLoad(() => api.get<Credential[]>(base), [api, base])
  const [kind, setKind] = useState<'card' | 'pin'>('card')
  const [format, setFormat] = useState('h10301')
  const [facility, setFacility] = useState('')
  const [number, setNumber] = useState('')
  const [pin, setPin] = useState('')
  const [error, setError] = useState<string | null>(null)
  const add = async () => {
    setError(null)
    try {
      await api.post(base, kind === 'pin' ? { kind, pin } : { kind, card: { format, number: Number(number), ...(format === 'h10301' ? { facility: Number(facility) } : {}) } })
      setNumber(''); setPin(''); setFacility('')
      await list.reload()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }
  const valid = kind === 'pin' ? /^\d{4,8}$/.test(pin) : /^\d+$/.test(number) && (format !== 'h10301' || /^\d+$/.test(facility))
  return (
    <section aria-labelledby="cred-h" className="pe-section">
      <h3 id="cred-h">Cards and PINs</h3>
      <ul className="pe-plain">
        {(list.data ?? []).map((c) => (
          <li key={c.id} className="pe-item">
            {c.kind === 'card' ? <>Card {c.card_facility != null ? `facility ${c.card_facility} ` : ''}{c.hint}</> : 'PIN'}{' '}
            {c.enabled ? <StatusBadge tone="ok">Works</StatusBadge> : <StatusBadge tone="warning">Turned off</StatusBadge>}{' '}
            <button className="ph-btn ph-btn-ghost ph-btn-sm" onClick={() => void api.patch(`${base}/${c.id}`, { enabled: !c.enabled }).then(list.reload)}>{c.enabled ? 'Turn off' : 'Turn on'}</button>
            <ConfirmButton small danger label="Remove" confirm="Remove it?" onConfirm={() => api.del(`${base}/${c.id}`).then(list.reload)} />
          </li>
        ))}
        {list.data?.length === 0 && <li className="ph-hint">None yet.</li>}
      </ul>
      <div className="pe-row">
        <div className="ph-field"><label htmlFor="c-kind">Add</label>
          <select id="c-kind" className="ph-input" value={kind} onChange={(e) => setKind(e.target.value as 'card' | 'pin')}><option value="card">A card</option><option value="pin">A PIN</option></select></div>
        {kind === 'card' ? (
          <>
            <div className="ph-field"><label htmlFor="c-format">Format</label>
              <select id="c-format" className="ph-input" value={format} onChange={(e) => setFormat(e.target.value)}>{FORMATS.map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}</select></div>
            {format === 'h10301' && <div className="ph-field"><label htmlFor="c-fac">Facility code</label><input id="c-fac" className="ph-input" inputMode="numeric" value={facility} onChange={(e) => setFacility(e.target.value)} /></div>}
            <div className="ph-field"><label htmlFor="c-num">Card number</label><input id="c-num" className="ph-input" inputMode="numeric" value={number} onChange={(e) => setNumber(e.target.value)} /></div>
          </>
        ) : (
          <div className="ph-field"><label htmlFor="c-pin">PIN (4 to 8 digits)</label><input id="c-pin" className="ph-input" inputMode="numeric" autoComplete="off" value={pin} onChange={(e) => setPin(e.target.value)} /></div>
        )}
      </div>
      <ErrorText>{error}</ErrorText>
      <button className="ph-btn ph-btn-secondary" disabled={!valid} onClick={() => void add()}>Add {kind === 'card' ? 'the card' : 'the PIN'}</button>
    </section>
  )
}

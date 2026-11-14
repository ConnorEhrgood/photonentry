import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import type { Applied, Controller, Door, Published, Site, SiteTemplate } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { useTenant } from '../auth/TenantContext'
import { SitePicker, useSite, useSites } from '../components/sites'
import { ErrorText, Loading, PageHeader, StatusBadge } from '../components/ui'
import { useLoad } from '../lib/useLoad'
import { windows } from '../lib/words'

const STEPS = ['Controllers', 'Template', 'Doors', 'People', 'Publish'] as const
/** How often the wizard looks again while a controller reports its doors or applies its settings. */
export const POLL_MS = 3000

/** Setting up a site, start to finish (BUILD-GUIDE §3): claim its controllers, pick a template, say which door is which, add people, publish. */
export function SetupPage() {
  const sites = useSites()
  const [site, pick] = useSite(sites.data)
  const [step, setStep] = useState(0)
  if (sites.error) return <ErrorText>{sites.error}</ErrorText>
  if (!sites.data) return <Loading what="sites" />
  if (!site) return <><PageHeader title="Set up a site" /><div className="ph-empty"><p>This organization has no sites yet. Add one in <a href="/">Manage organization</a>.</p></div></>
  return (
    <>
      <PageHeader title="Set up a site"><SitePicker sites={sites.data} site={site} onPick={(id) => { pick(id); setStep(0) }} /></PageHeader>
      <ol className="pe-steps" aria-label="Steps">
        {STEPS.map((s, i) => <li key={s} aria-current={i === step ? 'step' : undefined}>{i + 1}. {s}</li>)}
      </ol>
      <Wizard key={site.id} site={site} step={step} setStep={setStep} />
    </>
  )
}

function Wizard({ site, step, setStep }: { site: Site; step: number; setStep: (n: number) => void }) {
  const { api } = useAuth()
  const { current } = useTenant()
  const t = current!.id
  const controllers = useLoad(() => api.get<Controller[]>(`/tenants/${t}/controllers`).then((cs) => cs.filter((c) => c.site_id === site.id)), [api, t, site.id])
  const [template, setTemplate] = useState<SiteTemplate | null>(null)
  const [options, setOptions] = useState<Record<string, boolean>>({})
  const [applied, setApplied] = useState<Applied | null>(null)
  if (step === 0) return <ClaimStep site={site} controllers={controllers.data ?? []} reload={controllers.reload} next={() => setStep(1)} />
  if (step === 1) return <TemplateStep chosen={template} options={options} onChoose={(tpl) => { setTemplate(tpl); setOptions(Object.fromEntries(tpl.options.map((o) => [o.key, o.default]))) }}
    setOptions={setOptions} back={() => setStep(0)} next={() => setStep(2)} />
  if (step === 2) return <DoorsStep site={site} template={template!} options={options} controllers={controllers.data ?? []}
    back={() => setStep(1)} done={(a) => { setApplied(a); setStep(3) }} />
  if (step === 3) return <PeopleStep site={site} template={template} back={() => setStep(2)} next={() => setStep(4)} applied={applied} />
  return <PublishStep site={site} back={() => setStep(3)} />
}

/** 1. The controllers at the site: claim each by the code it shows, then wait for it to report its doors. */
function ClaimStep({ site, controllers, reload, next }: { site: Site; controllers: Controller[]; reload: () => Promise<void>; next: () => void }) {
  const { api } = useAuth()
  const { current } = useTenant()
  const [code, setCode] = useState('')
  const [name, setName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const waiting = controllers.some((c) => !c.inventory)
  useEffect(() => {
    if (!waiting) return
    const id = setInterval(() => void reload(), POLL_MS)
    return () => clearInterval(id)
  }, [waiting, reload])
  const claim = async () => {
    setBusy(true)
    setError(null)
    try {
      await api.post(`/tenants/${current!.id}/controllers/claim`, { code: code.trim(), site_id: site.id, name: name.trim() })
      setCode('')
      setName('')
      await reload()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }
  const ready = controllers.filter((c) => c.inventory && c.inventory.doors.length > 0)
  return (
    <section className="ph-card" aria-labelledby="claim-h">
      <h2 id="claim-h">Controllers at {site.name}</h2>
      <p className="ph-hint">Each door controller shows a claim code once it is online. Enter it here to add the controller to this site.</p>
      {controllers.length > 0 && (
        <ul className="pe-plain">
          {controllers.map((c) => (
            <li key={c.id} className={`ph-edge ph-edge-${c.inventory ? 'ok' : 'info'} pe-item`}>
              <strong>{c.name || c.device.model || 'Controller'}</strong>{' '}
              {c.inventory ? <StatusBadge tone="ok">{c.inventory.doors.length} doors reported</StatusBadge> : <StatusBadge tone="info">Waiting for its doors</StatusBadge>}
              <span className="ph-hint"> {c.device.model} {c.device.serial}</span>
            </li>
          ))}
        </ul>
      )}
      <div className="pe-row">
        <div className="ph-field">
          <label htmlFor="claim-code">Claim code</label>
          <input id="claim-code" className="ph-input" placeholder="ABCD-EFGH" value={code} onChange={(e) => setCode(e.target.value)} autoComplete="off" />
        </div>
        <div className="ph-field">
          <label htmlFor="claim-name">Name (optional)</label>
          <input id="claim-name" className="ph-input" placeholder="Front desk" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
      </div>
      <ErrorText>{error}</ErrorText>
      <div className="ph-actions">
        <button className="ph-btn ph-btn-secondary" disabled={busy || !/^[0-9A-Za-z]{4}-?[0-9A-Za-z]{4}$/.test(code.trim())} onClick={() => void claim()}>Claim controller</button>
        <button className="ph-btn" disabled={ready.length === 0} onClick={next}>Next: choose a template</button>
      </div>
    </section>
  )
}

/** 2. What kind of site this is. */
function TemplateStep({ chosen, options, onChoose, setOptions, back, next }: {
  chosen: SiteTemplate | null; options: Record<string, boolean>; onChoose: (t: SiteTemplate) => void; setOptions: (o: Record<string, boolean>) => void
  back: () => void; next: () => void
}) {
  const { api } = useAuth()
  const list = useLoad(() => api.get<SiteTemplate[]>('/templates'), [api])
  if (list.error) return <ErrorText>{list.error}</ErrorText>
  if (!list.data) return <Loading what="templates" />
  return (
    <section className="ph-card" aria-labelledby="tpl-h">
      <h2 id="tpl-h">What kind of site is this?</h2>
      <div className="pe-choices" role="radiogroup" aria-label="Template">
        {list.data.map((t) => (
          <label key={t.key} className={`pe-choice${chosen?.key === t.key ? ' pe-choice-on' : ''}`}>
            <input type="radio" name="template" checked={chosen?.key === t.key} onChange={() => onChoose(t)} />
            <span><strong>{t.name}</strong><br /><span className="ph-hint">{t.description}</span></span>
          </label>
        ))}
      </div>
      {chosen && (
        <>
          <h3>It creates</h3>
          <ul>
            {chosen.groups.map((g) => <li key={g.key}><strong>{g.name}</strong>: {g.description}</li>)}
          </ul>
          <p className="ph-hint">Schedules: {chosen.schedules.map((s) => `${s.name} (${windows(s.windows)})`).join('; ')}.
            {chosen.holidays ? ` Holidays: the ${chosen.holidays === 'us-federal' ? 'US federal' : 'usual US business'} holidays for this year and next, which you can change.` : ''}</p>
          {chosen.note && <p className="ph-banner ph-banner-info">{chosen.note}</p>}
          {chosen.options.map((o) => (
            <label key={o.key} className="ph-check">
              <input type="checkbox" checked={!!options[o.key]} onChange={(e) => setOptions({ ...options, [o.key]: e.target.checked })} /> {o.label}
            </label>
          ))}
        </>
      )}
      <div className="ph-actions">
        <button className="ph-btn ph-btn-ghost" onClick={back}>Back</button>
        <button className="ph-btn" disabled={!chosen} onClick={next}>Next: which door is which</button>
      </div>
    </section>
  )
}

/** 3. Each of the template's doors is one of the controllers' doors (or, if it is optional, not at this site). */
function DoorsStep({ site, template, options, controllers, back, done }: {
  site: Site; template: SiteTemplate; options: Record<string, boolean>; controllers: Controller[]; back: () => void; done: (a: Applied) => void
}) {
  const { api } = useAuth()
  const { current } = useTenant()
  const t = current!.id
  const existing = useLoad(() => api.get<Door[]>(`/tenants/${t}/sites/${site.id}/doors`), [api, t, site.id])
  const taken = useMemo(() => new Set((existing.data ?? []).map((d) => `${d.controller_id}|${d.controller_door}`)), [existing.data])
  const choices = controllers.flatMap((c) => (c.inventory?.doors ?? []).map((d) => ({
    value: `${c.id}|${d.token}`, label: `${c.name || c.device.model || 'Controller'} · ${d.name || d.token}`,
  }))).filter((o) => !taken.has(o.value))
  // Only the required doors start with a suggestion (in order); an optional door is "not at this site" until someone says which it is,
  // so a guess is never published by accident.
  const [map, setMap] = useState<Record<string, string>>(() => {
    const first: Record<string, string> = {}
    template.slots.filter((s) => s.required).forEach((s, i) => { if (choices[i]) first[s.key] = choices[i].value })
    return first
  })
  const [names, setNames] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const picked = Object.values(map).filter(Boolean)
  const twice = picked.length !== new Set(picked).size
  const missing = template.slots.filter((s) => s.required && !map[s.key])
  const create = async () => {
    setBusy(true)
    setError(null)
    const doors: Record<string, { controller_id: string; controller_door: string; name?: string }> = {}
    for (const s of template.slots) {
      if (!map[s.key]) continue
      const [controller_id, controller_door] = map[s.key].split('|')
      doors[s.key] = { controller_id, controller_door, ...(names[s.key]?.trim() ? { name: names[s.key].trim() } : {}) }
    }
    try {
      done(await api.post<Applied>(`/tenants/${t}/sites/${site.id}/templates/${template.key}/apply`, { doors, options }))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }
  if (!existing.data) return <Loading what="doors" />
  return (
    <section className="ph-card" aria-labelledby="doors-h">
      <h2 id="doors-h">Which door is which</h2>
      <p className="ph-hint">The controllers report their doors by number. Say which is which; leave out the ones this site doesn’t have.</p>
      <div className="pe-slots">
        {template.slots.map((s) => (
          <div key={s.key} className="pe-slot">
            <div className="ph-field">
              <label htmlFor={`slot-${s.key}`}>{s.name}{s.required ? '' : ' (if there is one)'}</label>
              <select id={`slot-${s.key}`} className="ph-input" value={map[s.key] ?? ''} onChange={(e) => setMap({ ...map, [s.key]: e.target.value })}>
                {!s.required && <option value="">Not at this site</option>}
                {s.required && !map[s.key] && <option value="">Choose a door</option>}
                {choices.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
              <span className="ph-hint">{s.hint}</span>
            </div>
            {map[s.key] && (
              <div className="ph-field">
                <label htmlFor={`name-${s.key}`}>Name</label>
                <input id={`name-${s.key}`} className="ph-input" placeholder={s.name} value={names[s.key] ?? ''} onChange={(e) => setNames({ ...names, [s.key]: e.target.value })} />
              </div>
            )}
          </div>
        ))}
      </div>
      {choices.length === 0 && <p className="ph-banner ph-banner-warning">Every door of these controllers is already a door at this site.</p>}
      {twice && <ErrorText>One controller door is chosen twice.</ErrorText>}
      <ErrorText>{error}</ErrorText>
      <div className="ph-actions">
        <button className="ph-btn ph-btn-ghost" onClick={back}>Back</button>
        <button className="ph-btn" disabled={busy || twice || missing.length > 0} onClick={() => void create()}>Create the doors, schedules and groups</button>
      </div>
    </section>
  )
}

const SAMPLE = 'name,ref,card_format,card_facility,card_number,pin,groups\nAlice Smith,E-100,h10301,12,3456,,Staff;Managers\nBob Jones,E-101,,,,4821,Staff\n'

/** 4. People: paste a spreadsheet (checked first, then imported), or add them later on the People page. */
function PeopleStep({ site, template, back, next, applied }: { site: Site; template: SiteTemplate | null; back: () => void; next: () => void; applied: Applied | null }) {
  const { api } = useAuth()
  const { current } = useTenant()
  const [csv, setCsv] = useState('')
  const [checked, setChecked] = useState<{ rows: number; new: number; updated: number; credentials: number } | null>(null)
  const [problems, setProblems] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const [imported, setImported] = useState(false)
  const run = async (dry: boolean) => {
    setError(null)
    setProblems([])
    try {
      const r = await api.post<{ rows: number; new: number; updated: number; credentials: number }>(`/tenants/${current!.id}/cardholders/import`, { site_id: site.id, csv, dry_run: dry })
      if (dry) setChecked(r)
      else { setImported(true); setChecked(r) }
    } catch (e) {
      const list = (e as { data?: { problems?: string[] } }).data?.problems
      if (list) setProblems(list)
      else setError(e instanceof Error ? e.message : String(e))
      setChecked(null)
    }
  }
  return (
    <section className="ph-card" aria-labelledby="people-h">
      <h2 id="people-h">People</h2>
      {applied && <p className="ph-banner ph-banner-ok" role="status">Created {Object.keys(applied.doors).length} doors, {Object.keys(applied.schedules).length} schedules and {Object.keys(applied.groups).length} access groups{applied.holidays_added ? `, and ${applied.holidays_added} holidays` : ''}.</p>}
      <p className="ph-hint">Paste rows from a spreadsheet: a name on each row, a card number or a PIN, and the groups they belong to
        {template ? <> ({template.groups.map((g) => g.name).join(', ')})</> : null}. Nothing is written until the check passes.</p>
      <textarea aria-label="Cardholders as CSV" className="ph-input pe-paste" placeholder={SAMPLE} value={csv} onChange={(e) => { setCsv(e.target.value); setChecked(null); setImported(false) }} />
      {problems.length > 0 && <ul className="ph-error" role="alert">{problems.map((p) => <li key={p}>{p}</li>)}</ul>}
      <ErrorText>{error}</ErrorText>
      {checked && <p className={`ph-banner ph-banner-${imported ? 'ok' : 'info'}`} role="status">
        {imported ? 'Imported' : 'Ready to import'}: {checked.new} new, {checked.updated} updated, {checked.credentials} cards and PINs.</p>}
      <div className="ph-actions">
        <button className="ph-btn ph-btn-ghost" onClick={back}>Back</button>
        <button className="ph-btn ph-btn-secondary" disabled={!csv.trim() || imported} onClick={() => void run(true)}>Check</button>
        <button className="ph-btn ph-btn-secondary" disabled={!checked || imported} onClick={() => void run(false)}>Import</button>
        <button className="ph-btn" onClick={next}>{imported || !csv.trim() ? 'Next: publish' : 'Skip for now'}</button>
      </div>
    </section>
  )
}

/** 5. Send it to the controllers, and watch them take it. */
function PublishStep({ site, back }: { site: Site; back: () => void }) {
  const { api } = useAuth()
  const { current, path } = useTenant()
  const t = current!.id
  const [result, setResult] = useState<Published | null>(null)
  const [problems, setProblems] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const controllers = useLoad(() => api.get<Controller[]>(`/tenants/${t}/controllers`).then((cs) => cs.filter((c) => c.site_id === site.id)), [api, t, site.id])
  const pending = !!result && (controllers.data ?? []).some((c) => !c.settings.current && c.settings.latest > 0)
  useEffect(() => {
    if (!pending) return
    const id = setInterval(() => void controllers.reload(), POLL_MS)
    return () => clearInterval(id)
  }, [pending, controllers])
  const publish = async () => {
    setError(null)
    setProblems([])
    try {
      setResult(await api.post<Published>(`/tenants/${t}/sites/${site.id}/publish`))
      await controllers.reload()
    } catch (e) {
      const list = (e as { data?: { problems?: string[] } }).data?.problems
      if (list) setProblems(list)
      else setError(e instanceof Error ? e.message : String(e))
    }
  }
  return (
    <section className="ph-card" aria-labelledby="pub-h">
      <h2 id="pub-h">Publish to the doors</h2>
      <p className="ph-hint">The controllers take the new settings within a few seconds and keep them: from then on every door decides on its own, with or without the internet.</p>
      {problems.length > 0 && <ul className="ph-error" role="alert">{problems.map((p) => <li key={p}>{p}</li>)}</ul>}
      <ErrorText>{error}</ErrorText>
      {result && (
        <ul className="pe-plain">
          {(controllers.data ?? []).map((c) => (
            <li key={c.id} className={`ph-edge ph-edge-${c.settings.error ? 'error' : c.settings.current ? 'ok' : 'info'} pe-item`}>
              <strong>{c.name || c.device.model}</strong>{' '}
              {c.settings.error ? <StatusBadge tone="error">Refused: {c.settings.error}</StatusBadge>
                : c.settings.current ? <StatusBadge tone="ok">Up to date</StatusBadge> : <StatusBadge tone="info">Applying…</StatusBadge>}
            </li>
          ))}
        </ul>
      )}
      <div className="ph-actions">
        <button className="ph-btn ph-btn-ghost" onClick={back}>Back</button>
        {!result && <button className="ph-btn" onClick={() => void publish()}>Publish</button>}
        {result && !pending && <Link className="ph-btn" to={path(`/doors?site=${site.id}`)}>Done: see the doors</Link>}
      </div>
    </section>
  )
}

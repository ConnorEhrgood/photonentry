import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import type { Controller, Door, DoorEvent, SiteTemplate } from '../api/types'
import { App } from '../App'
import { ME, meWith, OPERATOR, OWNER, renderApp, TECH_A, TECH_B, VIEWER } from '../test/helpers'
import { describe as describeEvent, days, windows } from '../lib/words'
import { controllerState } from './Doors'

const SITES = [{ id: 's1', slug: 'cw-main', name: 'Main office', address: '', timezone: 'America/New_York' }]
const now = new Date().toISOString()
const ctl = (o: Partial<Controller> = {}): Controller => ({
  id: 'c1', site_id: 's1', name: 'Front desk', state: 'claimed', device: { model: 'AXIS A1610', serial: 'B8A44F000001' },
  inventory: { doors: [{ token: 'door1', name: 'Door 1', access_points: ['ap1'] }, { token: 'door2', name: 'Door 2', access_points: ['ap2'] }] },
  settings: { latest: 1, applied: 1, error: '', current: true }, last_seen: now, health: {}, ...o,
})
const OFFICE: SiteTemplate = {
  key: 'office', name: 'Office', description: 'Staff in extended hours.', note: '', holidays: 'us-business',
  options: [{ key: 'unlock_main', label: 'Unlock the main entrance during business hours', default: false }],
  slots: [{ key: 'main_entrance', name: 'Main entrance', hint: 'The front door', required: true }, { key: 'server_room', name: 'Server room', hint: 'IT', required: false }],
  schedules: [{ key: 'extended', name: 'Extended hours', windows: [{ days: ['mo', 'tu', 'we', 'th', 'fr'], start: '06:00', end: '22:00' }], on_holidays: 'off' }],
  groups: [{ key: 'staff', name: 'Staff', description: 'Every employee' }, { key: 'it', name: 'IT', description: 'The server room' }],
}
const DOORS: Door[] = [{ id: 'd1', name: 'Main entrance', controller_id: 'c1', controller_door: 'door1', access_time_s: 7, open_too_long_s: 30, pre_alarm_s: 5, unlock_schedule_id: 'sc1' }]
const T = '/tenants/t1'

const app = (route: string, routes: Record<string, unknown>, me = ME) => renderApp(<Routes><Route path="*" element={<App />} /></Routes>, { route, me, routes: { [`GET ${T}/sites`]: SITES, ...routes } })

describe('setting up an office, start to finish', () => {
  it('claims a controller, applies the office template, imports people and publishes', async () => {
    const user = userEvent.setup()
    let controllers: Controller[] = []
    let applied: unknown = null
    let imported: unknown[] = []
    let published = false
    const { calls } = app('/setup', {
      [`GET ${T}/controllers`]: () => controllers,
      [`POST ${T}/controllers/claim`]: () => { controllers = [ctl({ settings: { latest: 0, applied: 0, error: '', current: true } })]; return controllers[0] },
      'GET /templates': [OFFICE],
      [`GET ${T}/sites/s1/doors`]: [],
      [`POST ${T}/sites/s1/templates/office/apply`]: (b: unknown) => { applied = b; return { template: 'office', doors: { main_entrance: 'd1' }, schedules: { extended: 'x' }, groups: { staff: 'g1' }, holidays_added: 7 } },
      [`POST ${T}/cardholders/import`]: (b: unknown) => { imported.push(b); return { dry_run: (b as { dry_run: boolean }).dry_run, rows: 2, new: 2, updated: 0, credentials: 2 } },
      [`POST ${T}/sites/s1/publish`]: () => { published = true; controllers = [ctl({ settings: { latest: 1, applied: 1, error: '', current: true } })]; return { controllers: [{ controller_id: 'c1', version: 1, changed: true }] } },
    })
    // 1. Claim.
    await user.type(await screen.findByLabelText('Claim code'), 'abcd-efgh')
    await user.type(screen.getByLabelText('Name (optional)'), 'Front desk')
    await user.click(screen.getByRole('button', { name: 'Claim controller' }))
    expect(await screen.findByText('2 doors reported')).toBeInTheDocument()
    expect(calls.find((c) => c.path.endsWith('/claim'))?.body).toEqual({ code: 'abcd-efgh', site_id: 's1', name: 'Front desk' })
    await user.click(screen.getByRole('button', { name: 'Next: choose a template' }))
    // 2. Template, with its option.
    await user.click(await screen.findByRole('radio', { name: /Office/ }))
    expect(screen.getByText(/Extended hours \(Mon–Fri 06:00–22:00\)/)).toBeInTheDocument()
    await user.click(screen.getByLabelText(/Unlock the main entrance/))
    await user.click(screen.getByRole('button', { name: 'Next: which door is which' }))
    // 3. Which door is which: the main entrance is door 1, the server room door 2, named.
    expect(screen.getByLabelText('Server room (if there is one)')).toHaveValue('')
    await user.selectOptions(await screen.findByLabelText('Server room (if there is one)'), 'c1|door2')
    await user.type(screen.getAllByLabelText('Name')[1], 'IT closet')
    await user.click(screen.getByRole('button', { name: 'Create the doors, schedules and groups' }))
    expect(await screen.findByText(/Created 1 doors, 1 schedules and 1 access groups, and 7 holidays/)).toBeInTheDocument()
    expect(applied).toEqual({ doors: { main_entrance: { controller_id: 'c1', controller_door: 'door1' }, server_room: { controller_id: 'c1', controller_door: 'door2', name: 'IT closet' } },
      options: { unlock_main: true } })
    // 4. People: check, then import.
    await user.click(screen.getByLabelText('Cardholders as CSV'))
    await user.paste('name,pin,groups\nAnn,4821,Staff\nBen,1357,Staff\n')
    await user.click(screen.getByRole('button', { name: 'Check' }))
    expect(await screen.findByText(/Ready to import: 2 new/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Import' }))
    expect(await screen.findByText(/Imported: 2 new/)).toBeInTheDocument()
    expect(imported.map((b) => (b as { dry_run: boolean }).dry_run)).toEqual([true, false])
    await user.click(screen.getByRole('button', { name: 'Next: publish' }))
    // 5. Publish and watch the controller take it.
    await user.click(await screen.findByRole('button', { name: 'Publish' }))
    expect(await screen.findByText('Up to date')).toBeInTheDocument()
    expect(published).toBe(true)
    expect(screen.getByRole('link', { name: 'Done: see the doors' })).toHaveAttribute('href', '/org/t1/doors?site=s1')
  })

  it('shows a refused claim, a door chosen twice, import problems and publish problems', async () => {
    const user = userEvent.setup()
    app('/setup', {
      [`GET ${T}/controllers`]: [ctl()],
      [`POST ${T}/controllers/claim`]: new Response(JSON.stringify({ detail: { code: 'no_such_controller', detail: 'No controller is waiting with that code.' } }), { status: 404 }),
      'GET /templates': [OFFICE], [`GET ${T}/sites/s1/doors`]: [],
      [`POST ${T}/sites/s1/templates/office/apply`]: { template: 'office', doors: {}, schedules: {}, groups: {}, holidays_added: 0 },
      [`POST ${T}/cardholders/import`]: new Response(JSON.stringify({ detail: { code: 'invalid_rows', problems: ['line 2: a name is required'] } }), { status: 422 }),
      [`POST ${T}/sites/s1/publish`]: new Response(JSON.stringify({ detail: { code: 'invalid', problems: ['door x: the controller has no door door9'] } }), { status: 422 }),
    })
    await user.type(await screen.findByLabelText('Claim code'), 'QQQQ-QQQQ')
    await user.click(screen.getByRole('button', { name: 'Claim controller' }))
    expect(await screen.findByText('No controller is waiting with that code.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Next: choose a template' }))
    await user.click(await screen.findByRole('radio', { name: /Office/ }))
    await user.click(screen.getByRole('button', { name: 'Next: which door is which' }))
    await user.selectOptions(await screen.findByLabelText('Server room (if there is one)'), 'c1|door1')
    expect(screen.getByText('One controller door is chosen twice.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Create the doors, schedules and groups' })).toBeDisabled()
    await user.selectOptions(screen.getByLabelText('Server room (if there is one)'), '')
    await user.click(screen.getByRole('button', { name: 'Create the doors, schedules and groups' }))
    await user.click(await screen.findByLabelText('Cardholders as CSV'))
    await user.paste(',\n')
    await user.click(screen.getByRole('button', { name: 'Check' }))
    expect(await screen.findByText('line 2: a name is required')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Skip for now' }))
    await user.click(await screen.findByRole('button', { name: 'Publish' }))
    expect(await screen.findByText('door x: the controller has no door door9')).toBeInTheDocument()
  })
})

describe('the daily pages', () => {
  it('overview: controllers and what needs attention', async () => {
    app('/overview', {
      [`GET ${T}/controllers`]: [ctl(), ctl({ id: 'c2', name: 'Back', last_seen: null }), ctl({ id: 'c3', name: 'Stale', settings: { latest: 2, applied: 1, error: 'capacity', current: false } })],
      [`GET ${T}/sites/s1/doors`]: DOORS,
    })
    expect(await screen.findByText('Never connected')).toBeInTheDocument()
    expect(screen.getByText('Settings refused')).toBeInTheDocument()
    expect(screen.getByText('capacity')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Set up this site' })).toHaveAttribute('href', '/org/t1/setup?site=s1')
  })

  it('doors: open one now and lock the site down, after confirming', async () => {
    const user = userEvent.setup()
    const { calls } = renderApp(<Routes><Route path="*" element={<App />} /></Routes>, {
      route: '/doors', me: meWith(OPERATOR), routes: {
        [`GET ${T}/sites`]: SITES, [`GET ${T}/sites/s1/doors`]: DOORS, [`GET ${T}/sites/s1/schedules`]: [{ id: 'sc1', name: 'Business hours', windows: [], on_holidays: 'off' }],
        [`POST ${T}/doors/d1/action`]: { id: 'cmd1' }, [`POST ${T}/sites/s1/lockdown`]: { commands: [] },
      },
    })
    expect(await screen.findByText('Business hours')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Open now' }))
    expect(await screen.findByText('Main entrance: opening for 7 seconds.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Lock down' }))
    await user.click(within(screen.getByRole('group', { name: /Lock every door/ })).getByRole('button', { name: 'Yes' }))
    expect(await screen.findByText(/Lockdown sent to every door/)).toBeInTheDocument()
    expect(calls.filter((c) => c.method === 'POST').map((c) => c.body)).toEqual([{ action: 'access' }, { on: true }])
  })

  it('doors: a viewer sees them without the buttons; an empty site offers setup', async () => {
    app('/doors', { [`GET ${T}/sites/s1/doors`]: DOORS, [`GET ${T}/sites/s1/schedules`]: [] }, meWith(VIEWER))
    expect(await screen.findByText('Main entrance')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Open now' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Lock down' })).not.toBeInTheDocument()
  })

  it('people: add a person to a group, then give them a PIN', async () => {
    const user = userEvent.setup()
    const people: unknown[] = []
    const { calls } = app('/people', {
      [`GET ${T}/cardholders`]: () => people, [`GET ${T}/sites/s1/groups`]: [{ id: 'g1', name: 'Staff', rules: [] }],
      [`POST ${T}/cardholders`]: (b: unknown) => ({ id: 'h1', ref: null, email: '', person_id: null, suspended: false, valid_from: null, valid_to: null, groups: [], ...(b as object) }),
      [`PUT ${T}/cardholders/h1/groups`]: () => { const p = { id: 'h1', name: 'Ann', ref: null, email: '', person_id: null, suspended: false, valid_from: null, valid_to: null, groups: ['g1'] }; people.push(p); return p },
      [`GET ${T}/cardholders/h1/credentials`]: [], [`POST ${T}/cardholders/h1/credentials`]: { id: 'k1' },
    })
    await user.click(await screen.findByRole('button', { name: 'Add a person' }))
    await user.type(screen.getByLabelText('Name'), 'Ann')
    await user.click(screen.getByLabelText(/Staff/))
    await user.click(screen.getByRole('button', { name: 'Add' }))
    expect(await screen.findByRole('heading', { name: 'Cards and PINs' })).toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText('Add'), 'pin')
    await user.type(screen.getByLabelText('PIN (4 to 8 digits)'), '4821')
    await user.click(screen.getByRole('button', { name: 'Add the PIN' }))
    await waitFor(() => expect(calls.some((c) => c.path === `${T}/cardholders/h1/credentials` && c.method === 'POST')).toBe(true))
    expect(calls.find((c) => c.method === 'PUT')?.body).toEqual({ group_ids: ['g1'] })
    expect(calls.find((c) => c.method === 'POST' && c.path.endsWith('/credentials'))?.body).toEqual({ kind: 'pin', pin: '4821' })
  })

  it('access: groups, schedules, holidays, and publishing', async () => {
    const user = userEvent.setup()
    app('/access', {
      [`GET ${T}/sites/s1/groups`]: [{ id: 'g1', name: 'Staff', rules: [{ doors: ['d1'], schedule_id: 'sc1' }, { doors: ['d1'], schedule_id: null }] }],
      [`GET ${T}/sites/s1/schedules`]: [{ id: 'sc1', name: 'Extended hours', windows: [{ days: ['mo', 'tu', 'we', 'th', 'fr'], start: '06:00', end: '22:00' }, { days: ['sa'], start: '08:00', end: '14:00' }], on_holidays: 'off' }],
      [`GET ${T}/sites/s1/doors`]: DOORS, [`GET ${T}/sites/s1/holidays`]: { days: [{ day: '2026-12-25', name: 'Christmas Day' }] },
      [`GET ${T}/controllers`]: [ctl({ settings: { latest: 2, applied: 1, error: '', current: false } })],
      [`POST ${T}/sites/s1/publish`]: { controllers: [{ controller_id: 'c1', version: 3, changed: true }] },
    })
    expect(await screen.findByText('A controller is not up to date with the last publish.')).toBeInTheDocument()
    expect(screen.getByText('Mon–Fri 06:00–22:00; Sat 08:00–14:00', { exact: false })).toBeInTheDocument()
    expect(screen.getByText('at all times')).toBeInTheDocument()
    expect(screen.getByText(/Christmas Day/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Publish to the doors' }))
    expect(await screen.findByText(/Published: 1 controller\(s\) get new settings/)).toBeInTheDocument()
  })

  it('events: in plain words, with door and person', async () => {
    const ev = (o: Partial<DoorEvent>): DoorEvent => ({ controller_id: 'c1', seq: 1, occurred_at: now, received_at: now, topic: '', door_id: 'd1', door: 'Main entrance',
      cardholder_id: null, cardholder: null, reason: null, state: null, ...o })
    app('/events', { [`GET ${T}/sites/s1/events?limit=200`]: [
      ev({ seq: 3, topic: 'AccessControl/AccessGranted/Credential', cardholder: 'Ann' }),
      ev({ seq: 2, topic: 'Door/State/DoorAlarm', state: 'DoorForcedOpen' }),
      ev({ seq: 1, topic: 'Door/State/DoorMode', state: 'Locked' }),
    ] })
    expect(await screen.findByText('Access granted')).toBeInTheDocument()
    expect(screen.getByText('Ann')).toBeInTheDocument()
    expect(screen.getByText('Door forced open')).toBeInTheDocument()
    expect(screen.queryByText('Door locked')).not.toBeInTheDocument()
  })

  it('an integrator starts at their customers', async () => {
    app('/', { [`GET ${T}/controllers`]: [ctl({ last_seen: null })], 'GET /tenants/t2/controllers': [] }, meWith(TECH_A, TECH_B))
    expect(await screen.findByRole('heading', { name: 'Customers' })).toBeInTheDocument()
    expect(within(screen.getByRole('table')).getByText('Birch Co')).toBeInTheDocument()
    expect(screen.getAllByText('None').length).toBe(1)
  })

  it('settings: the team, and the audit trail for an owner', async () => {
    app('/settings', { [`GET ${T}/members`]: [{ person_id: 'm1', name: 'Ada Owner', email: 'a@x', role: 'owner', scope: { all: true }, source: 'direct', pending: false }],
      [`GET ${T}/audit`]: [{ at: now, actor: 'Partner support', action: 'site.lockdown', target_type: 'site', target_id: 's1', detail: {} }] }, meWith(OWNER))
    await userEvent.setup().click(await screen.findByRole('link', { name: 'Audit trail' }))
    expect(await screen.findByText('Partner support')).toBeInTheDocument()
    expect(screen.getByText('site: lockdown')).toBeInTheDocument()
  })

  it('a viewer is told a page is not for them', async () => {
    app('/people', {}, meWith(VIEWER))
    expect(await screen.findByText('Your role doesn’t include this page.')).toBeInTheDocument()
  })
})

describe('words', () => {
  it('days and windows', () => {
    expect(days(['mo', 'tu', 'we', 'th', 'fr'])).toBe('Mon–Fri')
    expect(days(['sa', 'su', 'mo', 'tu', 'we', 'th', 'fr'])).toBe('Every day')
    expect(days(['mo', 'we', 'th'])).toBe('Mon, Wed, Thu')
    expect(windows([{ days: ['sa', 'su'], start: '08:00', end: '12:00' }])).toBe('Sat, Sun 08:00–12:00')
  })

  it('events', () => {
    const e = (topic: string, o: Partial<DoorEvent> = {}) => describeEvent({ controller_id: '', seq: 1, occurred_at: '', received_at: '', topic, door_id: null, door: null,
      cardholder_id: null, cardholder: null, reason: null, state: null, ...o })
    expect(e('AccessControl/Denied/Credential', { reason: 'NotPermittedAtThisTime' })).toEqual({ text: 'Denied: outside its schedule', tone: 'warning' })
    expect(e('AccessControl/Denied/Credential', { reason: 'Weird' }).text).toBe('Denied: Weird')
    expect(e('AccessControl/Denied/CredentialNotFound/Card').text).toBe('Denied: unknown card or PIN')
    expect(e('Door/State/DoorAlarm', { state: 'DoorOpenTooLong' }).text).toBe('Door held open')
    expect(e('Door/State/DoorAlarm', { state: 'Normal' }).tone).toBe('ok')
    expect(e('Door/State/DoorMode', { state: 'LockedDown' })).toEqual({ text: 'Door locked down', tone: 'warning' })
    expect(e('AccessControl/AccessGranted/Anonymous').text).toBe('Exit button')
    expect(e('Something/Else/Entirely').text).toBe('Else Entirely')
  })

  it('controller state', () => {
    expect(controllerState(ctl({ state: 'disabled' })).text).toBe('Out of service')
    expect(controllerState(ctl({ settings: { latest: 0, applied: 0, error: '', current: false } })).text).toBe('Not published yet')
    expect(controllerState(ctl({ last_seen: new Date(Date.now() - 3600e3).toISOString() })).text).toMatch(/^Offline since/)
    expect(controllerState(ctl()).text).toBe('Online')
  })
})

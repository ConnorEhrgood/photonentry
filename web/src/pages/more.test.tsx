import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { App } from '../App'
import { ago } from '../lib/format'
import { meWith, OWNER, renderApp, TECH_A, TECH_B } from '../test/helpers'

const T = '/tenants/t1'
const SITES = [{ id: 's1', slug: 'a', name: 'Main office', address: '', timezone: 'UTC' }, { id: 's2', slug: 'b', name: 'Annex', address: '', timezone: 'UTC' }]
const app = (route: string, routes: Record<string, unknown>, me = meWith(OWNER)) =>
  renderApp(<Routes><Route path="*" element={<App />} /></Routes>, { route, me, routes: { [`GET ${T}/sites`]: SITES, ...routes } })

describe('the frame', () => {
  it('switches customer, shows banners, signs out and opens the directory', async () => {
    const user = userEvent.setup()
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    const { source } = app('/doors', { [`GET ${T}/sites/s1/doors`]: [], [`GET ${T}/sites/s1/schedules`]: [], 'GET /tenants/t2/sites': SITES,
      'GET /tenants/t2/sites/s1/doors': [], 'GET /tenants/t2/sites/s1/schedules': [] },
    meWith({ ...TECH_A, status: 'suspended' }, { ...TECH_B, expires_at: '2030-01-01T00:00:00Z' }))
    expect(await screen.findByText(/plan needs attention/)).toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText('Customer'), 't2')
    expect(await screen.findByText(/Your access to Birch Co ends/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Ada Owner/ }))
    await user.click(screen.getByRole('menuitem', { name: 'Manage organization' }))
    expect(open).toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: /Ada Owner/ }))
    await user.click(screen.getByRole('menuitem', { name: 'Sign out' }))
    await waitFor(() => expect(source.signOut).toHaveBeenCalled())
  })

  it('someone with no organization is told so', async () => {
    app('/', {}, meWith())
    expect(await screen.findByText('No access to PhotonEntry yet')).toBeInTheDocument()
  })

  it('pages work on the site picked', async () => {
    const user = userEvent.setup()
    const { calls } = app('/events', { [`GET ${T}/sites/s1/events?limit=200`]: [], [`GET ${T}/sites/s2/events?limit=200`]: [] })
    await user.selectOptions(await screen.findByLabelText('Site'), 's2')
    expect(await screen.findByText(/Nothing has happened at Annex/)).toBeInTheDocument()
    expect(calls.some((c) => c.path.includes('/sites/s2/events'))).toBe(true)
  })
})

describe('people, changed', () => {
  it('edits a person, suspends them, turns a card off and removes it', async () => {
    const user = userEvent.setup()
    const ann = { id: 'h1', name: 'Ann', ref: 'E-1', email: '', person_id: null, suspended: false, valid_from: null, valid_to: null, groups: ['g1'] }
    let creds = [{ id: 'k1', kind: 'card', card_format: 'h10301', card_facility: 7, hint: '…213', enabled: true, valid_from: null, valid_to: null }]
    const { calls } = app('/people', {
      [`GET ${T}/cardholders`]: [ann, ...Array.from({ length: 5 }, (_, i) => ({ ...ann, id: `x${i}`, name: `Other ${i}`, ref: null }))],
      [`GET ${T}/sites/s1/groups`]: [{ id: 'g1', name: 'Staff', rules: [] }], [`GET ${T}/sites/s2/groups`]: [],
      [`PATCH ${T}/cardholders/h1`]: (b: unknown) => ({ ...ann, ...(b as object) }), [`PUT ${T}/cardholders/h1/groups`]: { ...ann, suspended: true },
      [`GET ${T}/cardholders/h1/credentials`]: () => creds,
      [`PATCH ${T}/cardholders/h1/credentials/k1`]: () => { creds = [{ ...creds[0], enabled: false }]; return creds[0] },
      [`DELETE ${T}/cardholders/h1/credentials/k1`]: () => { creds = []; return null },
    })
    expect((await screen.findAllByText('Staff (Main office)')).length).toBe(6)
    await user.type(screen.getByLabelText('Find'), 'other 1')
    expect(screen.queryByRole('button', { name: 'Ann' })).not.toBeInTheDocument()
    await user.clear(screen.getByLabelText('Find'))
    await user.click(screen.getByRole('button', { name: 'Ann' }))
    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByText(/facility 7 …213/)).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Turn off' }))
    expect(await within(dialog).findByText('Turned off')).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Remove' }))
    await user.click(within(dialog).getByRole('button', { name: 'Yes' }))
    expect(await within(dialog).findByText('None yet.')).toBeInTheDocument()
    await user.selectOptions(within(dialog).getByLabelText('Format'), 'w34')
    expect(within(dialog).queryByLabelText('Facility code')).not.toBeInTheDocument()
    await user.click(within(dialog).getByLabelText(/Suspended/))
    await user.click(within(dialog).getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(calls.find((c) => c.method === 'PATCH' && c.path === `${T}/cardholders/h1`)?.body).toEqual({ name: 'Ann', ref: 'E-1', email: '', suspended: true })
  })

  it('a card number already held is refused with the reason', async () => {
    const user = userEvent.setup()
    const ann = { id: 'h1', name: 'Ann', ref: null, email: '', person_id: null, suspended: false, valid_from: null, valid_to: null, groups: [] }
    app('/people', {
      [`GET ${T}/cardholders`]: [ann], [`GET ${T}/sites/s1/groups`]: [], [`GET ${T}/sites/s2/groups`]: [], [`GET ${T}/cardholders/h1/credentials`]: [],
      [`POST ${T}/cardholders/h1/credentials`]: new Response(JSON.stringify({ detail: { code: 'credential_exists', detail: 'That card or PIN already belongs to someone in this organization' } }), { status: 409 }),
    })
    await user.click(await screen.findByRole('button', { name: 'Ann' }))
    await user.type(screen.getByLabelText('Facility code'), '7')
    await user.type(screen.getByLabelText('Card number'), '10213')
    await user.click(screen.getByRole('button', { name: 'Add the card' }))
    expect(await screen.findByText(/already belongs to someone/)).toBeInTheDocument()
    expect(screen.getByText('No access groups yet: set up a site first.')).toBeInTheDocument()
  })
})

describe('publishing problems', () => {
  it('lists why a site cannot be published', async () => {
    const user = userEvent.setup()
    app('/access', {
      [`GET ${T}/sites/s1/groups`]: [], [`GET ${T}/sites/s1/schedules`]: [], [`GET ${T}/sites/s1/doors`]: [], [`GET ${T}/sites/s1/holidays`]: { days: [] },
      [`GET ${T}/controllers`]: [],
      [`POST ${T}/sites/s1/publish`]: new Response(JSON.stringify({ detail: { code: 'invalid', problems: ['door d: the controller has no door door9'] } }), { status: 422 }),
    })
    await user.click(await screen.findByRole('button', { name: 'Publish to the doors' }))
    expect(await screen.findByText('door d: the controller has no door door9')).toBeInTheDocument()
    expect(screen.getAllByText('None yet.').length).toBe(2)
  })
})

describe('time words', () => {
  it('ago', () => {
    const n = Date.parse('2026-11-13T12:00:00Z')
    expect(ago('2026-11-13T11:59:30Z', n)).toBe('just now')
    expect(ago('2026-11-13T11:30:00Z', n)).toBe('30 minutes ago')
    expect(ago('2026-11-13T06:00:00Z', n)).toBe('6 hours ago')
    expect(ago('2026-11-10T12:00:00Z', n)).toBe('3 days ago')
  })
})

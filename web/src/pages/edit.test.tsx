import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import type { Group, Holiday, Schedule } from '../api/types'
import { App } from '../App'
import { meWith, OWNER, renderApp, VIEWER } from '../test/helpers'

const T = '/tenants/t1'
const B = `${T}/sites/s1`
const SITES = [{ id: 's1', slug: 'a', name: 'Main office', address: '', timezone: 'UTC' }]
const DOORS = [{ id: 'd1', name: 'Front door', controller_id: 'c1', controller_door: 'door1', access_time_s: 7, open_too_long_s: 30, pre_alarm_s: 5, unlock_schedule_id: null },
  { id: 'd2', name: 'Side door', controller_id: 'c1', controller_door: 'door2', access_time_s: 7, open_too_long_s: 30, pre_alarm_s: 5, unlock_schedule_id: null }]

function world() {
  const state = {
    schedules: [{ id: 'sc1', name: 'Business hours', windows: [{ days: ['mo', 'tu', 'we', 'th', 'fr'], start: '08:00', end: '18:00' }], on_holidays: 'off' }] as Schedule[],
    groups: [{ id: 'g1', name: 'Staff', rules: [{ doors: ['d1'], schedule_id: 'sc1' }] }] as Group[],
    holidays: [{ day: '2026-12-25', name: 'Christmas Day' }] as Holiday[],
  }
  const routes = {
    [`GET ${T}/sites`]: SITES, [`GET ${B}/doors`]: DOORS, [`GET ${T}/controllers`]: [],
    [`GET ${B}/groups`]: () => state.groups, [`GET ${B}/schedules`]: () => state.schedules, [`GET ${B}/holidays`]: () => ({ days: state.holidays }),
    [`POST ${B}/schedules`]: (b: unknown) => { const s = { id: 'sc2', ...(b as object) } as Schedule; state.schedules = [...state.schedules, s]; return s },
    [`PUT ${B}/schedules/sc1`]: (b: unknown) => { state.schedules = [{ id: 'sc1', ...(b as object) } as Schedule]; return state.schedules[0] },
    [`DELETE ${B}/schedules/sc1`]: new Response(JSON.stringify({ detail: { code: 'schedule_in_use', detail: 'In use by: Staff' } }), { status: 409 }),
    [`POST ${B}/groups`]: (b: unknown) => { const g = { id: 'g2', ...(b as object) } as Group; state.groups = [...state.groups, g]; return g },
    [`PUT ${B}/groups/g1`]: (b: unknown) => { state.groups = [{ id: 'g1', ...(b as object) } as Group]; return state.groups[0] },
    [`DELETE ${B}/groups/g1`]: () => { state.groups = []; return null },
    [`PUT ${B}/holidays`]: (b: unknown) => { state.holidays = (b as { days: Holiday[] }).days; return b },
    'GET /holidays/us-federal/2027': [{ day: '2027-01-01', name: "New Year's Day" }, { day: '2026-12-25', name: 'Christmas Day' }],
    [`POST ${B}/publish`]: { controllers: [] },
  }
  return { state, routes }
}

const open = (routes: Record<string, unknown>, me = meWith(OWNER)) => renderApp(<Routes><Route path="*" element={<App />} /></Routes>, { route: '/access', me, routes })

describe('editing access in the app', () => {
  it('adds a schedule with two windows, one ending at midnight, on holidays too', async () => {
    const user = userEvent.setup()
    const { state, routes } = world()
    const { calls } = open(routes)
    await user.click(await screen.findByRole('button', { name: 'Add a schedule' }))
    const dialog = screen.getByRole('dialog')
    await user.type(within(dialog).getByLabelText('Name'), 'Cleaning')
    const days = within(dialog).getByRole('group', { name: 'Days of window 1' })
    for (const d of ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']) await user.click(within(days).getByLabelText(d))
    expect(within(dialog).getByText('Each window needs at least one day, and ends after it starts.')).toBeInTheDocument()
    await user.click(within(days).getByLabelText('Sat'))
    await user.clear(within(dialog).getByLabelText('Until'))
    await user.type(within(dialog).getByLabelText('Until'), '00:00')
    await user.click(within(dialog).getByRole('button', { name: 'Add a window' }))
    await user.click(within(dialog).getByRole('button', { name: 'Add a window' }))
    await user.click(within(dialog).getAllByRole('button', { name: 'Remove this window' })[2])
    await user.click(within(dialog).getByLabelText('Off on the site’s holidays'))
    await user.click(within(dialog).getByRole('button', { name: 'Save' }))
    expect(await screen.findByText(/Saved. The doors keep their current settings until you publish./)).toBeInTheDocument()
    expect(calls.find((c) => c.method === 'POST' && c.path.endsWith('/schedules'))?.body).toEqual({
      name: 'Cleaning', on_holidays: 'normal',
      windows: [{ days: ['sa'], start: '08:00', end: '24:00' }, { days: ['sa'], start: '09:00', end: '13:00' }],
    })
    expect(state.schedules).toHaveLength(2)
    await user.click(screen.getByRole('button', { name: 'Publish to the doors' }))
    await waitFor(() => expect(screen.queryByText(/Saved. The doors keep/)).not.toBeInTheDocument())
  })

  it('changes a schedule, and is told when one in use cannot be removed', async () => {
    const user = userEvent.setup()
    const { routes } = world()
    const { calls } = open(routes)
    await user.click((await screen.findAllByRole('button', { name: 'Change' }))[1])
    const dialog = screen.getByRole('dialog', { name: 'Change Business hours' })
    await user.clear(within(dialog).getByLabelText('From'))
    await user.type(within(dialog).getByLabelText('From'), '07:30')
    await user.click(within(dialog).getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'PUT' && c.path.endsWith('/schedules/sc1'))).toBe(true))
    expect((calls.find((c) => c.method === 'PUT')?.body as { windows: { start: string }[] }).windows[0].start).toBe('07:30')
    const item = (await screen.findByText(/Business hours:/)).closest('li')!
    await user.click(within(item).getByRole('button', { name: 'Remove' }))
    await user.click(within(item).getByRole('button', { name: 'Yes' }))
    expect(await screen.findByText('In use by: Staff')).toBeInTheDocument()
  })

  it('adds and changes an access group, and removes one', async () => {
    const user = userEvent.setup()
    const { state, routes } = world()
    const { calls } = open(routes)
    await user.click(await screen.findByRole('button', { name: 'Add an access group' }))
    let dialog = screen.getByRole('dialog')
    await user.type(within(dialog).getByLabelText('Name'), 'Night shift')
    expect(within(dialog).getByText('Each rule opens at least one door.')).toBeInTheDocument()
    await user.click(within(within(dialog).getByRole('group', { name: 'Doors of rule 1' })).getByLabelText('Side door'))
    await user.click(within(dialog).getByRole('button', { name: 'Add a rule' }))
    await user.click(within(within(dialog).getByRole('group', { name: 'Doors of rule 2' })).getByLabelText('Front door'))
    await user.selectOptions(within(dialog).getAllByLabelText('When')[1], 'sc1')
    await user.click(within(dialog).getAllByRole('button', { name: 'Remove this rule' })[0])
    await user.click(within(dialog).getByLabelText(/Visitors’ passes may use this group/))
    await user.click(within(dialog).getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(state.groups).toHaveLength(2))
    expect(calls.find((c) => c.method === 'POST' && c.path.endsWith('/groups'))?.body).toEqual({ name: 'Night shift', rules: [{ doors: ['d1'], schedule_id: 'sc1' }],
      for_visitors: true })
    const card = (await screen.findByRole('heading', { name: 'Staff' })).closest('.ph-card') as HTMLElement
    await user.click(within(card).getByRole('button', { name: 'Change' }))
    dialog = screen.getByRole('dialog', { name: 'Change Staff' })
    await user.selectOptions(within(dialog).getByLabelText('When'), '')
    await user.click(within(dialog).getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(state.groups[0].rules[0].schedule_id).toBeNull())
    const card2 = (await screen.findByRole('heading', { name: 'Staff' })).closest('.ph-card') as HTMLElement
    await user.click(within(card2).getByRole('button', { name: 'Remove' }))
    await user.click(within(card2).getByRole('button', { name: 'Yes' }))
    await waitFor(() => expect(state.groups.find((g) => g.id === 'g1')).toBeUndefined())
  })

  it('adds a day, a year of holidays without doubles, and removes one', async () => {
    const user = userEvent.setup()
    const { state, routes } = world()
    open(routes)
    await user.type(await screen.findByLabelText('Day'), '2027-03-15')
    await user.type(screen.getByLabelText('Name'), 'Spring break')
    await user.click(screen.getByRole('button', { name: 'Add the day' }))
    await waitFor(() => expect(state.holidays.map((h) => h.day)).toEqual(['2026-12-25', '2027-03-15']))
    await user.selectOptions(screen.getByLabelText('US holidays'), 'us-federal')
    await user.clear(screen.getByLabelText('Year'))
    await user.type(screen.getByLabelText('Year'), '2027')
    await user.click(screen.getByRole('button', { name: 'Add that year’s holidays' }))
    await waitFor(() => expect(state.holidays).toHaveLength(3))
    const item = (await screen.findByText(/Spring break/)).closest('li')!
    await user.click(within(item).getByRole('button', { name: 'Remove' }))
    await user.click(within(item).getByRole('button', { name: 'Yes' }))
    await waitFor(() => expect(state.holidays.map((h) => h.name)).toEqual(['Christmas Day', "New Year's Day"]))
  })

  it('a viewer sees access but cannot change it', async () => {
    const { routes } = world()
    open(routes, meWith(VIEWER))
    expect(await screen.findByText('Christmas Day', { exact: false })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Add a schedule' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Change' })).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Day')).not.toBeInTheDocument()
  })
})

describe('when the API refuses an edit', () => {
  it('shows why, for a schedule, a group and a year of holidays', async () => {
    const user = userEvent.setup()
    const { routes } = world()
    const refuse = (msg: string) => new Response(JSON.stringify({ detail: msg }), { status: 422 })
    open({ ...routes, [`POST ${B}/schedules`]: refuse('name: too long'), [`POST ${B}/groups`]: refuse('A rule names a door that is not this site’s'),
      'GET /holidays/us-business/2027': new Response(JSON.stringify({ detail: 'Not found' }), { status: 404 }),
      [`PUT ${B}/holidays`]: refuse('days: too many') })
    await user.click(await screen.findByRole('button', { name: 'Add a schedule' }))
    await user.type(within(screen.getByRole('dialog')).getByLabelText('Name'), 'X')
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Save' }))
    expect(await screen.findByText('name: too long')).toBeInTheDocument()
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Cancel' }))
    await user.click(screen.getByRole('button', { name: 'Add an access group' }))
    await user.type(within(screen.getByRole('dialog')).getByLabelText('Name'), 'G')
    await user.click(within(within(screen.getByRole('dialog')).getByRole('group', { name: 'Doors of rule 1' })).getByLabelText('Front door'))
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Save' }))
    expect(await screen.findByText('A rule names a door that is not this site’s')).toBeInTheDocument()
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Cancel' }))
    await user.clear(screen.getByLabelText('Year'))
    await user.type(screen.getByLabelText('Year'), '2027')
    await user.click(screen.getByRole('button', { name: 'Add that year’s holidays' }))
    expect(await screen.findByText('Not found')).toBeInTheDocument()
    await user.type(screen.getByLabelText('Day'), '2027-03-15')
    await user.click(screen.getByRole('button', { name: 'Add the day' }))
    expect(await screen.findByText('days: too many')).toBeInTheDocument()
  })
})

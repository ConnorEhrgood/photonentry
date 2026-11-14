import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import type { CommissioningRecord, Door, DoorCommissioning, SiteCommissioning } from '../api/types'
import { App } from '../App'
import { meWith, OPERATOR, OWNER, renderApp } from '../test/helpers'

const T = '/tenants/t1'
const S = `${T}/sites/s1`
const SITES = [{ id: 's1', slug: 'cw-main', name: 'Main office', address: '5 Capitol St, Charleston, WV', timezone: 'America/New_York' }]
const DOORS: Door[] = [{ id: 'd1', name: 'Main entrance', controller_id: 'c1', controller_door: 'door1', access_time_s: 7, open_too_long_s: 30, pre_alarm_s: 5, unlock_schedule_id: null }]
const RECORD: CommissioningRecord = { id: 'r1', door_id: 'd1', jurisdiction: 'WV', lock_type: 'strike_fail_secure', lock_type_label: 'Electric strike, fail-secure',
  failure_state: 'fail_secure', egress: 'Lever, free egress', special_locking: 'none', fire_release: 'tested', fire_tested_on: '2026-11-10', fire_tested_by: 'Bo Fire',
  rex_checked: true, contact_checked: true, reader_ul_verified: false, ahj_reference: 'Permit 2026-0412', installer: 'Ann Lee',
  license: 'WV Specialty Low-Voltage Electrician (SP-LV), State Fire Marshal SPLV-12345, Ann Lee, to 2027-06-30', notes: '', signed_by: 'Partner support',
  signed_at: '2026-11-14T15:00:00Z', voided_at: null, voided_by: null, void_reason: null }
const site = (d: DoorCommissioning): SiteCommissioning => ({ jurisdiction: 'WV', required_license: { WV: 'wv_sp_lv' },
  lock_types: { strike_fail_secure: 'Electric strike, fail-secure', maglock: 'Magnetic lock' },
  special_locking: { none: 'None', sensor_release: 'Sensor release (maglock)' }, doors: [d] })
const LICENSES = { kinds: { WV: { wv_sp_lv: 'Specialty Low-Voltage Electrician (SP-LV), State Fire Marshal', other: 'Other' }, PA: { pa_hicpa: 'HICPA' }, OH: {} },
  can_manage_partner: false, can_manage_organization: true,
  licenses: [{ id: 'l1', owner: 'partner', state: 'WV', kind: 'wv_sp_lv', kind_label: 'Specialty Low-Voltage Electrician (SP-LV), State Fire Marshal', holder: 'Ann Lee',
    number: 'SPLV-12345', expires_on: '2026-12-01', expired: false, expiring: true, removed: false, text: '' }] }
const app = (route: string, routes: Record<string, unknown>, me = meWith(OWNER)) => renderApp(<Routes><Route path="*" element={<App />} /></Routes>, {
  route, me, routes: { [`GET ${T}/sites`]: SITES, [`GET ${S}/doors`]: DOORS, [`GET ${S}/schedules`]: [], [`GET ${S}/lockdowns`]: [], [`GET ${S}/intercoms`]: [],
    [`GET ${T}/integrations/vox/stations`]: () => new Response('{}', { status: 404 }), ...routes } })

describe('commissioning', () => {
  it('an admin records a door, is told what is missing, then signs it', async () => {
    const user = userEvent.setup()
    let state = site({ door_id: 'd1', door: 'Main entrance', in_service: false, why: 'never', record: null })
    let tries = 0
    const { calls } = app('/doors', {
      [`GET ${S}/commissioning`]: () => state, [`GET ${T}/licenses`]: LICENSES,
      [`POST ${S}/doors/d1/commissioning`]: () => {
        if (tries++ === 0) return new Response(JSON.stringify({ detail: { code: 'incomplete', detail: 'Check the request-to-exit',
          problems: ['Check the request-to-exit', 'Check the door contact'] } }), { status: 422 })
        state = site({ door_id: 'd1', door: 'Main entrance', in_service: true, why: '', record: RECORD })
        return { ...state.doors[0], settings: 'updated' }
      },
    })
    expect(await screen.findByText(/No door here is commissioned yet/)).toBeInTheDocument()
    expect(screen.getByText(/gets only the installer test setup/)).toBeInTheDocument()
    await user.click(await screen.findByRole('button', { name: 'Main entrance: commission' }))
    const dialog = screen.getByRole('dialog', { name: 'Commission Main entrance' })
    expect(within(dialog).getByLabelText('State')).toHaveValue('WV')
    expect(within(dialog).getByLabelText('License (required here)')).toBeInTheDocument()
    await user.selectOptions(within(dialog).getByLabelText('Lock type'), 'strike_fail_secure')
    await user.selectOptions(within(dialog).getByLabelText('As wired, on power loss'), 'fail_secure')
    await user.type(within(dialog).getByLabelText('Egress hardware'), 'Lever, free egress')
    await user.selectOptions(within(dialog).getByLabelText('Fire release'), 'tested')
    await user.type(within(dialog).getByLabelText('Tested on'), '2026-11-10')
    await user.type(within(dialog).getByLabelText('Tested by'), 'Bo Fire')
    await user.type(within(dialog).getByLabelText('AHJ reference or permit number'), 'Permit 2026-0412')
    await user.type(within(dialog).getByLabelText('Name'), 'Ann Lee')
    await user.selectOptions(await within(dialog).findByLabelText('License (required here)'), 'l1')
    await user.selectOptions(within(dialog).getByLabelText('Special locking'), 'sensor_release')
    expect(within(dialog).getByLabelText(/UL-verified/)).toBeInTheDocument()
    await user.selectOptions(within(dialog).getByLabelText('Special locking'), 'none')
    await user.click(within(dialog).getByRole('button', { name: 'Sign and put in service' }))
    expect(await within(dialog).findByText('Check the door contact')).toBeInTheDocument()       // every problem, at once
    await user.click(within(dialog).getByLabelText('Request-to-exit checked'))
    await user.click(within(dialog).getByLabelText('Door contact checked'))
    await user.click(within(dialog).getByRole('button', { name: 'Sign and put in service' }))
    expect(await screen.findByText('In service')).toBeInTheDocument()
    expect(screen.getByText('Main entrance is in service: its real settings are on their way to the controller.')).toBeInTheDocument()
    expect(screen.queryByText(/not commissioned yet/)).not.toBeInTheDocument()
    const body = calls.filter((c) => c.method === 'POST').pop()?.body as Record<string, unknown>
    expect(body).toMatchObject({ jurisdiction: 'WV', lock_type: 'strike_fail_secure', license_id: 'l1', fire_tested_on: '2026-11-10', rex_checked: true, contact_checked: true })
  })

  it('anyone sees the record; an admin can say it needs commissioning again', async () => {
    const user = userEvent.setup()
    let state = site({ door_id: 'd1', door: 'Main entrance', in_service: true, why: '', record: RECORD })
    const { calls } = app('/doors', {
      [`GET ${S}/commissioning`]: () => state,
      [`GET ${S}/doors/d1/commissioning`]: [RECORD, { ...RECORD, id: 'r0', lock_type_label: 'Magnetic lock', void_reason: 'Replaced' }],
      [`POST ${S}/doors/d1/commissioning/void`]: () => {
        state = site({ door_id: 'd1', door: 'Main entrance', in_service: false, why: 'voided', record: { ...RECORD, voided_at: 'x', void_reason: 'New lock fitted' } })
        return state.doors[0]
      },
    })
    await user.click(await screen.findByRole('button', { name: 'Main entrance: commissioning record' }))
    const dialog = screen.getByRole('dialog', { name: 'Main entrance: commissioning' })
    expect(within(dialog).getByText(/SPLV-12345/)).toBeInTheDocument()
    expect(within(dialog).getByText(/Tested .* by Bo Fire/)).toBeInTheDocument()
    expect(await within(dialog).findByText('Earlier records (1)')).toBeInTheDocument()
    await user.type(within(dialog).getByLabelText('Needs commissioning again because'), 'New lock fitted')
    await user.click(within(dialog).getByRole('button', { name: 'Needs commissioning again' }))
    await user.click(within(screen.getByRole('group', { name: /out of service/ })).getByRole('button', { name: 'Yes' }))
    expect(await screen.findByText('Needs commissioning again: test setup only')).toBeInTheDocument()
    expect(calls.find((c) => c.path.endsWith('/void'))?.body).toEqual({ reason: 'New lock fitted' })
  })

  it('an operator sees the state but cannot sign', async () => {
    app('/doors', { [`GET ${S}/commissioning`]: site({ door_id: 'd1', door: 'Main entrance', in_service: false, why: 'moved', record: RECORD }),
      [`GET ${S}/doors/d1/commissioning`]: [RECORD] }, meWith(OPERATOR))
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Main entrance: commissioning record' }))
    expect(screen.getAllByText('Rewired: test setup only').length).toBeGreaterThan(0)
    expect(screen.queryByLabelText('Needs commissioning again because')).not.toBeInTheDocument()
  })
})

describe('licenses', () => {
  it('lists them with their expiry, adds one and removes one', async () => {
    const user = userEvent.setup()
    let list = LICENSES
    const { calls } = app('/settings/licenses', {
      [`GET ${T}/licenses`]: () => list,
      [`POST ${T}/licenses`]: () => { list = { ...LICENSES, licenses: [...LICENSES.licenses, { ...LICENSES.licenses[0], id: 'l2', owner: 'organization', holder: 'CW Facilities', expiring: false }] }; return list.licenses[1] },
      [`DELETE ${T}/licenses/l2`]: () => { list = LICENSES; return null },
    })
    expect(await screen.findByText('Expires soon')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Remove' })).not.toBeInTheDocument()                      // the partner's: not ours to remove
    await user.selectOptions(screen.getByLabelText('Kind'), 'wv_sp_lv')
    await user.type(screen.getByLabelText('Holder (as on the license)'), 'CW Facilities')
    await user.type(screen.getByLabelText('Number'), 'SPLV-9')
    await user.click(screen.getByRole('button', { name: 'Add' }))
    expect(await screen.findByText('CW Facilities')).toBeInTheDocument()
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ owner: 'organization', state: 'WV', kind: 'wv_sp_lv', holder: 'CW Facilities', number: 'SPLV-9', expires_on: null })
    await user.click(screen.getByRole('button', { name: 'Remove' }))
    await user.click(within(screen.getByRole('group', { name: /Remove\?/ })).getByRole('button', { name: 'Yes' }))
    expect(await screen.findByText('Ann Lee')).toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText('State'), 'PA')
    expect(screen.getByLabelText('Kind')).toHaveValue('')
  })
})


describe('holding doors back', () => {
  it('says which doors get only the test setup, and what signing does when the site has not been published', async () => {
    const user = userEvent.setup()
    const two = (d1: boolean): SiteCommissioning => ({ ...site({ door_id: 'd1', door: 'Main entrance', in_service: d1, why: d1 ? '' : 'never', record: d1 ? RECORD : null }),
      doors: [{ door_id: 'd1', door: 'Main entrance', in_service: d1, why: d1 ? '' : 'never', record: d1 ? RECORD : null },
        { door_id: 'd2', door: 'Side door', in_service: true, why: '', record: RECORD }] })
    let state = two(false)
    app('/doors', { [`GET ${S}/doors`]: [{ ...DOORS[0], unlock_schedule_id: 'sc1' }, { ...DOORS[0], id: 'd2', name: 'Side door' }],
      [`GET ${S}/schedules`]: [{ id: 'sc1', name: 'Business hours', windows: [], on_holidays: 'off' }], [`GET ${S}/commissioning`]: () => state, [`GET ${T}/licenses`]: LICENSES,
      [`POST ${S}/doors/d1/commissioning`]: () => { state = two(true); return { ...state.doors[0], settings: 'not_published' } } })
    expect(await screen.findByText('1 of 2 doors are not commissioned yet')).toBeInTheDocument()
    expect(screen.getByText('(once commissioned)')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Main entrance: commission' }))
    const dialog = screen.getByRole('dialog', { name: 'Commission Main entrance' })
    await user.click(within(dialog).getByRole('button', { name: 'Sign and put in service' }))
    expect(await screen.findByText(/its real settings go out with the site's first publish/)).toBeInTheDocument()
  })

  it('signed off, but the controller could not take it', async () => {
    const user = userEvent.setup()
    let state = site({ door_id: 'd1', door: 'Main entrance', in_service: false, why: 'never', record: null })
    app('/doors', { [`GET ${S}/commissioning`]: () => state, [`GET ${T}/licenses`]: LICENSES,
      [`POST ${S}/doors/d1/commissioning`]: () => { state = site({ door_id: 'd1', door: 'Main entrance', in_service: true, why: '', record: RECORD });
        return { ...state.doors[0], settings: 'not_updated', settings_problem: 'x' } } })
    await user.click(await screen.findByRole('button', { name: 'Main entrance: commission' }))
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Sign and put in service' }))
    expect(await screen.findByText(/could not be updated: publish the site to see why/)).toBeInTheDocument()
  })
})

import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import type { Door, Intercom } from '../api/types'
import { App } from '../App'
import { meWith, OPERATOR, OWNER, renderApp } from '../test/helpers'

const T = '/tenants/t1'
const S = `${T}/sites/s1`
const SITES = [{ id: 's1', slug: 'cw-main', name: 'Main office', address: '', timezone: 'America/New_York' }]
const DOORS: Door[] = [
  { id: 'd1', name: 'Main entrance', controller_id: 'c1', controller_door: 'door1', access_time_s: 7, open_too_long_s: 30, pre_alarm_s: 5, unlock_schedule_id: null },
  { id: 'd2', name: 'Side door', controller_id: 'c1', controller_door: 'door2', access_time_s: 7, open_too_long_s: 30, pre_alarm_s: 5, unlock_schedule_id: null },
]
const ic = (o: Partial<Intercom> = {}): Intercom => ({ id: 'i1', name: 'Front intercom', door_id: 'd1', door: 'Main entrance', model: 'S532', mac: '0C:11:05:AA:BB:CC',
  relay_address: '', relay_target: '10.152.0.20:8742', sip_server: 'vox.example', sip_port: 5061, sip_transport: 'tls', sip_user: 'door-101',
  sip_password_set: true, vox_station_id: '', sip_synced_at: null, last_fetch_at: null, last_fetch_ip: '', ...o })
const SETUP = { provision_url: 'https://link.entry.photonind.com/provision/v1/tok/', unlock_code: '#', admin_user: 'admin', admin_password: 'pw-admin' }
const app = (routes: Record<string, unknown>, me = meWith(OWNER)) => renderApp(<Routes><Route path="*" element={<App />} /></Routes>, {
  route: '/doors', me, routes: { [`GET ${T}/sites`]: SITES, [`GET ${S}/doors`]: DOORS, [`GET ${S}/schedules`]: [],
    [`GET ${T}/integrations/vox/stations`]: () => new Response(JSON.stringify({ detail: 'Not found' }), { status: 404 }), ...routes },
})

describe('Intercoms', () => {
  it('adds one, then shows what to type into it', async () => {
    const user = userEvent.setup()
    let list: Intercom[] = []
    const { calls } = app({
      [`GET ${S}/intercoms`]: () => list,
      [`POST ${S}/intercoms`]: () => { list = [ic({ door_id: 'd2', door: 'Side door' })]; return list[0] },
      [`GET ${S}/intercoms/i1/setup`]: SETUP,
    })
    expect(await screen.findByText('No intercoms at this site.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Add an intercom' }))
    const dialog = screen.getByRole('dialog', { name: 'Add an intercom' })
    expect(within(dialog).getByRole('button', { name: 'Save' })).toBeDisabled()
    await user.type(within(dialog).getByLabelText('Name'), 'Front intercom')
    await user.selectOptions(within(dialog).getByLabelText('Door'), 'd2')
    await user.selectOptions(within(dialog).getByLabelText('Akuvox model'), 'X915V2')
    await user.type(within(dialog).getByLabelText(/MAC address/), '0c:11:05:aa:bb:cc')
    await user.type(within(dialog).getByLabelText('Server'), 'vox.example')
    await user.type(within(dialog).getByLabelText('User'), 'door-101')
    await user.type(within(dialog).getByLabelText('Password'), 'sip-secret')
    await user.click(within(dialog).getByRole('button', { name: 'Save' }))
    // A new intercom opens its setup values straight away.
    const setup = await screen.findByRole('dialog', { name: 'Set up Front intercom' })
    expect(await within(setup).findByText(SETUP.provision_url)).toBeInTheDocument()
    expect(within(setup).getByText('#')).toBeInTheDocument()
    expect(within(setup).getByText('pw-admin')).toBeInTheDocument()
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ name: 'Front intercom', door_id: 'd2', model: 'X915V2', mac: '0c:11:05:aa:bb:cc',
      sip_server: 'vox.example', sip_port: 5061, sip_transport: 'tls', sip_user: 'door-101', sip_password: 'sip-secret', relay_address: '' })
    await user.click(within(setup).getByRole('button', { name: 'Done' }))
    expect(screen.getByText('Waiting for the intercom')).toBeInTheDocument()
  })

  it('changes one without resending its SIP password, and removes one', async () => {
    const user = userEvent.setup()
    let list = [ic({ last_fetch_at: new Date().toISOString() })]
    const { calls } = app({
      [`GET ${S}/intercoms`]: () => list,
      [`PATCH ${S}/intercoms/i1`]: () => { list = [ic({ name: 'Lobby intercom' })]; return list[0] },
      [`DELETE ${S}/intercoms/i1`]: () => { list = []; return null },
    })
    expect(await screen.findByText('Front intercom')).toBeInTheDocument()
    expect(screen.getByText(/^Set up /)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Change' }))
    const dialog = screen.getByRole('dialog', { name: 'Change Front intercom' })
    expect(within(dialog).getByLabelText('Password')).toHaveAttribute('placeholder', 'Unchanged')
    await user.clear(within(dialog).getByLabelText('Name'))
    await user.type(within(dialog).getByLabelText('Name'), 'Lobby intercom')
    await user.click(within(dialog).getByRole('button', { name: 'Save' }))
    expect(await screen.findByText('Lobby intercom')).toBeInTheDocument()
    const patch = calls.find((c) => c.method === 'PATCH')?.body as Record<string, unknown>
    expect(patch.name).toBe('Lobby intercom')
    expect(patch).not.toHaveProperty('sip_password')
    await user.click(screen.getByRole('button', { name: 'Remove' }))
    await user.click(within(screen.getByRole('group', { name: /Remove\?/ })).getByRole('button', { name: 'Yes' }))
    expect(await screen.findByText('No intercoms at this site.')).toBeInTheDocument()
  })

  it('says when the controller has not reported its address, and when a request fails', async () => {
    const user = userEvent.setup()
    app({
      [`GET ${S}/intercoms`]: [ic({ relay_target: '' })],
      [`GET ${S}/intercoms/i1/setup`]: () => new Response(JSON.stringify({ detail: 'Not allowed' }), { status: 403 }),
    })
    expect(await screen.findByText(/has not said where the intercom reaches it/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Setup values' }))
    expect(await within(screen.getByRole('dialog')).findByText(/Not allowed/)).toBeInTheDocument()
  })

  it('with PhotonVox connected, a door station gives the intercom its phone account', async () => {
    const user = userEvent.setup()
    let list: Intercom[] = [ic()]
    const { calls } = app({
      [`GET ${S}/intercoms`]: () => list,
      [`GET ${T}/integrations/vox/stations`]: [{ id: 'ds-1', name: 'Front door', site_id: null, extension: '901' }],
      [`PATCH ${S}/intercoms/i1`]: () => { list = [ic({ vox_station_id: 'ds-1' })]; return list[0] },
    })
    await user.click(await screen.findByRole('button', { name: 'Change' }))
    const dialog = screen.getByRole('dialog', { name: 'Change Front intercom' })
    expect(within(dialog).getByLabelText('Server')).toBeInTheDocument()
    await user.selectOptions(await within(dialog).findByLabelText('Door station in PhotonVox'), 'ds-1')
    expect(within(dialog).queryByLabelText('Server')).not.toBeInTheDocument()
    expect(within(dialog).getByText(/comes from PhotonVox/)).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Save' }))
    await screen.findByText('Front intercom')
    const patch = calls.find((c) => c.method === 'PATCH')?.body as Record<string, unknown>
    expect(patch.vox_station_id).toBe('ds-1')
    for (const k of ['sip_server', 'sip_user', 'sip_password', 'sip_port']) expect(patch).not.toHaveProperty(k)
  })

  it('says when PhotonVox cannot list its door stations, and still lets the account be typed', async () => {
    const user = userEvent.setup()
    app({ [`GET ${S}/intercoms`]: [ic()],
      [`GET ${T}/integrations/vox/stations`]: () => new Response(JSON.stringify({ detail: { code: 'vox_refused', detail: 'PhotonVox could not be reached' } }), { status: 502 }) })
    await user.click(await screen.findByRole('button', { name: 'Change' }))
    expect(await screen.findByText(/can’t be listed right now/)).toBeInTheDocument()
    expect(screen.getByLabelText('Server')).toBeInTheDocument()
  })

  it('operators do not see intercoms', async () => {
    app({}, meWith(OPERATOR))
    expect(await screen.findByText('Main entrance')).toBeInTheDocument()
    expect(screen.queryByText('Intercoms')).not.toBeInTheDocument()
  })
})

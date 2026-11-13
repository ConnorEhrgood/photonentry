import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { App } from '../App'
import { meWith, OPERATOR, OWNER, renderApp } from '../test/helpers'

const T = '/tenants/t1'
const app = (route: string, routes: Record<string, unknown>, me = meWith(OWNER)) => renderApp(<Routes><Route path="*" element={<App />} /></Routes>, { route, me, routes })
const view = (o = {}) => ({ connected: true, enabled: true, token_hint: '…ghij', last_ok_at: new Date().toISOString(), last_error: '', last_error_at: null, sent: 12,
  guard_api_url: 'https://api.guard.photonind.com', bindings: [{ door_id: 'd1', door: 'Front door', site: 'Main office', binding: 'entry-door-d1' }], ...o })

describe('PhotonGuard settings', () => {
  it('connects with a token, tests it, pauses and disconnects', async () => {
    const user = userEvent.setup()
    let current = view({ connected: false, enabled: false, token_hint: null, last_ok_at: null, sent: 0, bindings: [] })
    const { calls } = app('/settings/guard', {
      [`GET ${T}/integrations/guard`]: () => current,
      [`PUT ${T}/integrations/guard`]: () => { current = view(); return current },
      [`POST ${T}/integrations/guard/test`]: { ok: false, detail: 'PhotonGuard refused the token: make a new ingest token in PhotonGuard and paste it here.' },
      [`PATCH ${T}/integrations/guard`]: () => { current = view({ enabled: false }); return current },
      [`DELETE ${T}/integrations/guard`]: () => { current = view({ connected: false, enabled: false, bindings: [] }); return null },
    })
    expect(await screen.findByText('Not connected')).toBeInTheDocument()
    await user.type(screen.getByLabelText('Ingest token'), 'guard_ingest_token_0123456789')
    await user.click(screen.getByRole('button', { name: 'Connect' }))
    expect(await screen.findByText('Sending')).toBeInTheDocument()
    expect(screen.getByText('entry-door-d1')).toBeInTheDocument()
    expect(calls.find((c) => c.method === 'PUT')?.body).toEqual({ token: 'guard_ingest_token_0123456789' })
    await user.click(screen.getByRole('button', { name: 'Send a test event' }))
    expect(await screen.findByText(/refused the token/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Pause' }))
    expect(await screen.findByText('Paused')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Disconnect' }))
    await user.click(within(screen.getByRole('group', { name: /Stop sending/ })).getByRole('button', { name: 'Yes' }))
    expect(await screen.findByText('Not connected')).toBeInTheDocument()
  })

  it('says when sending stopped', async () => {
    app('/settings/guard', { [`GET ${T}/integrations/guard`]: view({ last_error: 'Guard refused an event (HTTP 401)', last_error_at: new Date().toISOString() }) })
    expect(await screen.findByText('Not sending')).toBeInTheDocument()
    expect(screen.getByText(/Guard refused an event \(HTTP 401\)/)).toBeInTheDocument()
  })

  it('operators have no integration tabs', async () => {
    app('/settings/guard', {}, meWith(OPERATOR))
    expect(await screen.findByText('Your role doesn’t include this page.')).toBeInTheDocument()
  })
})

describe('PhotonConsole settings', () => {
  it('makes a token shown once and revokes one', async () => {
    const user = userEvent.setup()
    let tokens = [{ id: 'k0', name: 'Old', console_tenant_id: null, created_at: '', last_used_at: new Date().toISOString(), revoked: false }]
    const { calls } = app('/settings/console', {
      [`GET ${T}/integrations/console/tokens`]: () => tokens,
      [`POST ${T}/integrations/console/tokens`]: () => { tokens = [...tokens, { id: 'k1', name: 'PhotonConsole', console_tenant_id: null, created_at: '', last_used_at: null, revoked: false }]; return { token: 'pent_secret' } },
      [`DELETE ${T}/integrations/console/tokens/k0`]: () => { tokens = tokens.filter((t) => t.id !== 'k0'); return null },
    })
    expect(await screen.findByText('Old')).toBeInTheDocument()
    await user.type(screen.getByLabelText('PhotonConsole tenant id (optional)'), 'ct-1')
    await user.click(screen.getByRole('button', { name: 'Make a token' }))
    expect(await screen.findByText('pent_secret')).toBeInTheDocument()
    expect(screen.getByText('not used yet')).toBeInTheDocument()
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ name: 'PhotonConsole', console_tenant_id: 'ct-1' })
    await user.click(screen.getAllByRole('button', { name: 'Revoke' })[0])
    await user.click(within(screen.getByRole('group', { name: /Revoke this token/ })).getByRole('button', { name: 'Yes' }))
    await screen.findByText('Copy the token now: it is not shown again.')
    expect(within(screen.getByRole('list')).getByText('PhotonConsole')).toBeInTheDocument()
    await screen.findByRole('list')
    expect(screen.queryByText('Old')).not.toBeInTheDocument()
  })
})

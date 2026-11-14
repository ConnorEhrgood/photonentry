import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes, useLocation } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { App } from '../App'
import { DOOR_USER, meWith, OWNER, renderApp } from '../test/helpers'

const T = '/tenants/t1'
const door = (o = {}) => ({ door_id: 'd1', door: 'Front door', site_id: 's1', site: 'Main office', can_open: true, why: '', why_text: '', ...o })
function Where() { return <output data-testid="where">{useLocation().pathname}</output> }
const app = (route: string, routes: Record<string, unknown>, me = meWith(DOOR_USER)) =>
  renderApp(<><Routes><Route path="*" element={<App />} /></Routes><Where /></>, { route, me, routes })

describe('my doors', () => {
  it('a door user lands on their doors, sees nothing else, and opens one', async () => {
    const user = userEvent.setup()
    let polls = 0
    const { calls } = app('/', {
      [`GET ${T}/my/doors`]: { linked: true, doors: [door(), door({ door_id: 'd2', door: 'Side door', can_open: false, why: 'outside_schedule', why_text: 'Not at this time' })] },
      [`POST ${T}/my/doors/d1/open`]: { id: 'cmd1' },
      [`GET ${T}/my/commands/cmd1`]: () => ({ id: 'cmd1', done: ++polls > 1, ok: true, error: '', expired: false }),
    })
    expect(await screen.findByRole('heading', { name: 'My doors' })).toBeInTheDocument()
    expect(screen.getByTestId('where').textContent).toBe('/org/t1/my-doors')
    expect(screen.getAllByRole('link').map((l) => l.textContent)).not.toContain('Doors')                 // nothing else in the sidebar
    expect(screen.getByText('Not at this time')).toBeInTheDocument()
    const side = screen.getByText('Side door').closest('li') as HTMLElement
    expect(within(side).getByRole('button', { name: 'Open' })).toBeDisabled()
    const front = screen.getByText('Front door').closest('li') as HTMLElement
    await user.click(within(front).getByRole('button', { name: 'Open' }))
    await waitFor(() => expect(within(front).getByRole('status')).toHaveTextContent('Opened'), { timeout: 4000 })
    expect(calls.filter((c) => c.method === 'POST').map((c) => c.path)).toEqual([`${T}/my/doors/d1/open`])
  })

  it('a door that refuses, a controller that does not answer, and an open that is refused', async () => {
    const user = userEvent.setup()
    app('/my-doors', {
      [`GET ${T}/my/doors`]: { linked: true, doors: [door(), door({ door_id: 'd2', door: 'Side door' }), door({ door_id: 'd3', door: 'Gate' })] },
      [`POST ${T}/my/doors/d1/open`]: { id: 'c1' }, [`GET ${T}/my/commands/c1`]: { id: 'c1', done: true, ok: false, error: 'Failure', expired: false },
      [`POST ${T}/my/doors/d2/open`]: { id: 'c2' }, [`GET ${T}/my/commands/c2`]: { id: 'c2', done: false, ok: null, error: '', expired: true },
      [`POST ${T}/my/doors/d3/open`]: () => new Response(JSON.stringify({ detail: { code: 'locked_down', detail: 'Gate: locked down' } }), { status: 409 }),
    })
    const row = async (name: string) => (await screen.findByText(name)).closest('li') as HTMLElement
    await user.click(within(await row('Front door')).getByRole('button', { name: 'Open' }))
    await waitFor(() => expect(within(screen.getByText('Front door').closest('li') as HTMLElement).getByRole('status')).toHaveTextContent('did not open: Failure'), { timeout: 4000 })
    await user.click(within(await row('Side door')).getByRole('button', { name: 'Open' }))
    await waitFor(() => expect(within(screen.getByText('Side door').closest('li') as HTMLElement).getByRole('status')).toHaveTextContent('did not answer in time'), { timeout: 4000 })
    await user.click(within(await row('Gate')).getByRole('button', { name: 'Open' }))
    expect(await within(screen.getByText('Gate').closest('li') as HTMLElement).findByText(/locked down/)).toBeInTheDocument()
  })

  it('not linked yet, and linked with no doors', async () => {
    const r = app('/my-doors', { [`GET ${T}/my/doors`]: { linked: false, doors: [] } })
    expect(await screen.findByText(/isn’t linked to a cardholder/)).toBeInTheDocument()
    r.unmount()
    app('/my-doors', { [`GET ${T}/my/doors`]: { linked: true, doors: [] } })
    expect(await screen.findByText(/No doors yet/)).toBeInTheDocument()
  })

  it('an owner keeps the overview as home and has My doors too', async () => {
    app('/', { [`GET ${T}/controllers`]: [], [`GET ${T}/sites`]: [] }, meWith({ ...OWNER, capabilities: [...OWNER.capabilities, 'entry.unlock.own'] }))
    expect(await screen.findByRole('link', { name: 'My doors' })).toHaveAttribute('href', '/org/t1/my-doors')
    await waitFor(() => expect(screen.getByTestId('where').textContent).toBe('/org/t1/'))
  })
})

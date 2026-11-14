import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import type { VisitorPass } from '../api/types'
import { App } from '../App'
import { meWith, OPERATOR, renderApp, VIEWER } from '../test/helpers'

const T = '/tenants/t1'
const S = `${T}/sites/s1`
const SITES = [{ id: 's1', slug: 'cw-main', name: 'Main office', address: '', timezone: 'America/New_York' }]
const soon = (h: number) => new Date(Date.now() + h * 3_600_000).toISOString()
const pass = (o: Partial<VisitorPass> = {}): VisitorPass => ({ id: 'p1', visitor_name: 'Vera Visitor', visitor_email: null, group_id: 'g9', group: 'Visitors',
  valid_from: soon(0), valid_to: soon(8), state: 'active', host: 'A Op', created_at: soon(0), emailed: false, link: 'https://entry.photonind.com/pass/tok',
  revoked_by: null, ...o })
const app = (route: string, routes: Record<string, unknown>, me = meWith(OPERATOR)) =>
  renderApp(<Routes><Route path="*" element={<App />} /></Routes>, { route, me, routes: { [`GET ${T}/sites`]: SITES, ...routes } })

describe('visitors', () => {
  it('the front desk makes a pass, sees its PIN and link once, and revokes one', async () => {
    const user = userEvent.setup()
    let list: VisitorPass[] = [pass({ id: 'p0', visitor_name: 'Old Guest', state: 'over' })]
    const { calls } = app('/visitors', {
      [`GET ${S}/passes`]: () => list, [`GET ${S}/visitor-groups`]: [{ id: 'g9', name: 'Visitors' }],
      [`POST ${S}/passes`]: () => { const p = pass({ pin: '482913', emailed: true, visitor_email: 'vera@example.com' }); list = [p, ...list]; return p },
      [`POST ${S}/passes/p1/revoke`]: () => { list = [pass({ state: 'revoked' }), list[1]]; return list[0] },
    })
    expect(await screen.findByText('Old Guest')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Revoke' })).not.toBeInTheDocument()            // an over pass has nothing to revoke
    await user.click(screen.getByRole('button', { name: 'Make a pass' }))
    const dialog = screen.getByRole('dialog', { name: 'A pass for Main office' })
    expect(within(dialog).getByRole('button', { name: 'Make the pass' })).toBeDisabled()
    await user.type(within(dialog).getByLabelText('Visitor’s name'), 'Vera Visitor')
    await user.type(within(dialog).getByLabelText('Their email (optional)'), 'vera@example.com')
    expect(await within(dialog).findByRole('option', { name: 'Visitors' })).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Make the pass' }))
    const made = await screen.findByRole('dialog', { name: 'Pass for Vera Visitor' })
    expect(within(made).getByText('482913')).toBeInTheDocument()
    expect(within(made).getByText(/emailed to vera@example.com/)).toBeInTheDocument()
    const body = calls.find((c) => c.method === 'POST')?.body as Record<string, string>
    expect(body.group_id).toBe('g9') && expect(body.visitor_email).toBe('vera@example.com')
    expect(new Date(body.valid_to).getTime() - new Date(body.valid_from).getTime()).toBe(8 * 3_600_000)
    await user.click(within(made).getByRole('button', { name: 'Done' }))
    await user.click(screen.getByRole('button', { name: 'Revoke' }))
    await user.click(within(screen.getByRole('group', { name: /Revoke this pass/ })).getByRole('button', { name: 'Yes' }))
    expect(await screen.findByText('Revoked')).toBeInTheDocument()
  })

  it('says when no group is open to visitors yet', async () => {
    const user = userEvent.setup()
    app('/visitors', { [`GET ${S}/passes`]: [], [`GET ${S}/visitor-groups`]: [] })
    await user.click(await screen.findByRole('button', { name: 'Make a pass' }))
    expect(await screen.findByText(/No access group here is open to visitors yet/)).toBeInTheDocument()
  })

  it('a viewer has no Visitors page', async () => {
    app('/visitors', {}, meWith(VIEWER))
    expect(await screen.findByText('Your role doesn’t include this page.')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Visitors' })).not.toBeInTheDocument()
  })
})

describe("the visitor's own page", () => {
  const page = (o = {}) => ({ visitor_name: 'Vera Visitor', site: 'Main office', address: '1 Mill Road, Pittsburgh PA', timezone: 'America/New_York', host: 'A Op',
    valid_from: soon(0), valid_to: soon(8), state: 'active', pin: '482913', card_number: '2914587', ...o })

  it('shows where, when and the PIN, with no sign-in', async () => {
    renderApp(<Routes><Route path="*" element={<App />} /></Routes>, { route: '/pass/tok', bare: true, routes: { 'GET /passes/v1/tok': page() } })
    expect(await screen.findByLabelText('Your PIN')).toHaveTextContent('482913')
    expect(screen.getByText('Main office')).toBeInTheDocument()
    expect(screen.getByText(/Invited by A Op/)).toBeInTheDocument()
  })

  it('a revoked pass, an upcoming one, and a link that is not one', async () => {
    const r1 = renderApp(<Routes><Route path="*" element={<App />} /></Routes>, { route: '/pass/tok', bare: true,
      routes: { 'GET /passes/v1/tok': page({ state: 'revoked', pin: null }) } })
    expect(await screen.findByText('This pass was revoked.')).toBeInTheDocument()
    r1.unmount()
    const r2 = renderApp(<Routes><Route path="*" element={<App />} /></Routes>, { route: '/pass/tok', bare: true,
      routes: { 'GET /passes/v1/tok': page({ state: 'upcoming' }) } })
    expect(await screen.findByText('It works from the time above.')).toBeInTheDocument()
    r2.unmount()
    renderApp(<Routes><Route path="*" element={<App />} /></Routes>, { route: '/pass/bad', bare: true,
      routes: { 'GET /passes/v1/bad': () => new Response('{}', { status: 404 }) } })
    expect(await screen.findByRole('heading', { name: 'No such pass' })).toBeInTheDocument()
  })
})

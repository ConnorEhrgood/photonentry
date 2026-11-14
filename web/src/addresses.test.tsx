import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes, useLocation } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import type { TenantAccess } from './api/types'
import { App } from './App'
import { meWith, OWNER, renderApp, TECH_A } from './test/helpers'

/** The suite's addresses (photon-suite ARCHITECTURE §6): /org/<slug>/…, /org/<slug>/site/<site-slug>/…; old ones redirect. */
const CEDAR: TenantAccess = { ...OWNER, slug: 'cedar-works', former_slugs: ['cedar'] }
const BIRCH: TenantAccess = { ...TECH_A, id: 't2', name: 'Birch Co', slug: 'birch' }
const SITES = [{ id: 's1', slug: 'cw-main', name: 'Main office', address: '', timezone: 'America/New_York' },
  { id: 's2', slug: 'cw-annex', name: 'Annex', address: '', timezone: 'America/New_York' }]
const DOOR = (site: string) => [{ id: `d-${site}`, name: `${site} door`, controller_id: 'c1', controller_door: 'door1', access_time_s: 7, open_too_long_s: 30, pre_alarm_s: 5, unlock_schedule_id: null }]
const ROUTES = {
  'GET /tenants/t1/sites': SITES, 'GET /tenants/t1/sites/s1/doors': DOOR('s1'), 'GET /tenants/t1/sites/s2/doors': DOOR('s2'),
  'GET /tenants/t1/sites/s1/schedules': [], 'GET /tenants/t1/sites/s2/schedules': [], 'GET /tenants/t1/sites/s1/intercoms': [], 'GET /tenants/t1/sites/s2/intercoms': [],
  'GET /tenants/t1/controllers': [], 'GET /tenants/t2/controllers': [], 'GET /tenants/t2/sites': [],
}

function Where() {
  const { pathname, search } = useLocation()
  return <output data-testid="where">{pathname + search}</output>
}
const app = (route: string, me = meWith(CEDAR), routes: Record<string, unknown> = {}) =>
  renderApp(<><Routes><Route path="*" element={<App />} /></Routes><Where /></>, { route, me, routes: { ...ROUTES, ...routes } })
const where = () => screen.getByTestId('where').textContent

describe('addresses', () => {
  it('an organization by its slug; its home is the overview', async () => {
    app('/org/cedar-works/')
    expect(await screen.findByRole('heading', { name: 'Overview' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Doors' })).toHaveAttribute('href', '/org/cedar-works/doors')
  })

  it('old addresses keep working: the same page in the current organization', async () => {
    app('/doors?site=s2#x')
    expect(await screen.findByText('s2 door')).toBeInTheDocument()
    expect(where()).toBe('/org/cedar-works/doors?site=s2')
  })

  it('a former slug goes to the organization’s address now', async () => {
    app('/org/cedar/doors?site=s2')
    expect(await screen.findByText('s2 door')).toBeInTheDocument()
    expect(where()).toBe('/org/cedar-works/doors?site=s2')
  })

  it('an organization this person cannot reach is “can’t open”, never another customer', async () => {
    app('/org/someone-else/doors')
    expect(await screen.findByRole('heading', { name: 'We can’t open that organization' })).toBeInTheDocument()
    expect(screen.queryByText('Cedar Works')).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Go to your organizations' })).toHaveAttribute('href', '/')
  })

  it('a site by its slug: the pages work on that site, and the links stay on it', async () => {
    app('/org/cedar-works/site/cw-annex/doors')
    expect(await screen.findByText('s2 door')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Access' })).toHaveAttribute('href', '/org/cedar-works/site/cw-annex/access')
    await userEvent.setup().selectOptions(screen.getByLabelText('Site'), 's1')
    expect(await screen.findByText('s1 door')).toBeInTheDocument()
    expect(where()).toBe('/org/cedar-works/site/cw-main/doors')
  })

  it('a site’s home, and an unknown page inside an organization goes to its home', async () => {
    app('/org/cedar-works/site/cw-annex/')
    expect(await screen.findByRole('heading', { name: 'Overview' })).toBeInTheDocument()
    app('/org/cedar-works/nothing-here')
    expect(await screen.findAllByRole('heading', { name: 'Overview' })).not.toHaveLength(0)
  })

  it('other apps may link in with ?organization=&site=', async () => {
    app('/?organization=t1&site=cw-annex')
    expect(await screen.findAllByRole('heading', { name: 'Overview' })).not.toHaveLength(0)
    expect(where()).toBe('/org/cedar-works/site/cw-annex/')
  })

  it('an integrator switches customers on the same page, and gets the Customers list first', async () => {
    const user = userEvent.setup()
    app('/', meWith(CEDAR, BIRCH))
    expect(await screen.findByRole('heading', { name: 'Customers' })).toBeInTheDocument()
    await user.click(screen.getAllByRole('link', { name: 'Open' })[1])
    expect(await screen.findAllByRole('heading', { name: 'Overview' })).not.toHaveLength(0)
    expect(where()).toBe('/org/birch/overview')
    await user.selectOptions(screen.getByLabelText('Customer'), 't1')
    expect(where()).toBe('/org/cedar-works/overview')
  })
})

describe('the app switcher', () => {
  it('lists the products for this organization and site, from the directory, with this token', async () => {
    const user = userEvent.setup()
    const apps = {
      home: 'https://account.photonind.com/', organization: { id: 't1', slug: 'cedar-works', name: 'Cedar Works' }, site: { id: 's2', slug: 'cw-annex', name: 'Annex' },
      apps: [{ key: 'entry', name: 'PhotonEntry', state: 'open', url: 'https://entry.photonind.com/org/cedar-works/site/cw-annex/' },
        { key: 'guard', name: 'PhotonGuard', state: 'open', url: 'https://guard.photonind.com/org/cedar-works/site/cw-annex/' },
        { key: 'vox', name: 'PhotonVox', state: 'not_enabled' }],
    }
    const { calls } = app('/org/cedar-works/site/cw-annex/doors', meWith(CEDAR), { 'GET /v1/me/apps': apps })
    await screen.findByText('s2 door')
    await user.click(screen.getByRole('button', { name: 'Switch app' }))
    const panel = await screen.findByRole('dialog', { name: 'Photon apps' })
    expect(await within(panel).findByRole('link', { name: 'PhotonGuard' })).toHaveAttribute('href', 'https://guard.photonind.com/org/cedar-works/site/cw-annex/')
    expect(within(panel).getByText('You are here')).toBeInTheDocument()
    expect(within(panel).getByRole('link', { name: /Home/ })).toHaveAttribute('href', 'https://account.photonind.com/')
    expect(calls.find((c) => c.path.startsWith('/v1/me/apps'))?.path).toBe('/v1/me/apps?organization=cedar-works&site=cw-annex')
  })
})

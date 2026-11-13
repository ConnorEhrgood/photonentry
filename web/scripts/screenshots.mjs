#!/usr/bin/env node
// The screenshot recipe (photon-suite/ARCHITECTURE.md §6): run the dev server, answer the API from fixtures, screenshot every page at the three
// sizes every page is reviewed at (1440x900, 820x1180, 390x844), then LOOK at them. Output goes to web/screenshots/ (git-ignored).
//   node scripts/screenshots.mjs                 all pages, all sizes
//   node scripts/screenshots.mjs setup           only pages whose name contains "setup"
// Chromium comes from Playwright's cache (~/.cache/ms-playwright); no Playwright test runner is needed.
import { spawn } from 'node:child_process'
import { existsSync, mkdirSync, readdirSync, readFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { chromium } from 'playwright-core'

const PORT = 5193
const API = 'http://api.test'
const SIZES = { desktop: { width: 1440, height: 900 }, tablet: { width: 820, height: 1180 }, phone: { width: 390, height: 844 } }
const only = process.argv[2]

const cache = join(homedir(), '.cache/ms-playwright')
const shellDir = readdirSync(cache).find((d) => d.startsWith('chromium_headless_shell'))
const executablePath = join(cache, shellDir, 'chrome-headless-shell-linux64/chrome-headless-shell')
if (!existsSync(executablePath)) throw new Error(`no Chromium at ${executablePath}`)

const VIEWER = ['entry.view', 'entry.events.view']
const OPERATOR = [...VIEWER, 'entry.cardholders.view', 'entry.door.unlock', 'entry.lockdown']
const ADMIN = [...OPERATOR, 'entry.cardholders.manage', 'entry.credential.issue', 'entry.config.manage', 'entry.controller.manage', 'entry.members.view']
const OWNER = [...ADMIN, 'entry.emergency.open', 'entry.audit.view']
const tenant = (o = {}) => ({ id: 't1', name: 'Cedar Works', status: 'active', partner_id: null, role: 'owner', scope: { all: true }, source: 'direct', expires_at: null, capabilities: OWNER, ...o })
const tech = (o = {}) => tenant({ role: 'admin', source: 'partner', partner_id: 'pa', capabilities: ADMIN, ...o })
const me = (tenants, extra = {}) => ({ id: 'p1', name: 'Ada Owner', email: 'ada@example.com', is_platform_admin: false, tenants, ...extra })
const now = new Date().toISOString()
const SITES = [{ id: 's1', slug: 'cw-main', name: 'Main office', address: '1 Mill Road, Pittsburgh PA', timezone: 'America/New_York' },
  { id: 's2', slug: 'cw-annex', name: 'Annex', address: '', timezone: 'America/New_York' }]
const inv = { doors: [{ token: 'Axis-b8a44f:door1', name: 'Door 1', access_points: ['a'] }, { token: 'Axis-b8a44f:door2', name: 'Door 2', access_points: ['b'] }] }
const CONTROLLERS = [
  { id: 'c1', site_id: 's1', name: 'Front desk', state: 'claimed', device: { model: 'AXIS A1610', serial: 'B8A44F0A1B2C' }, inventory: inv,
    settings: { latest: 3, applied: 3, error: '', current: true }, last_seen: now, health: {} },
  { id: 'c2', site_id: 's1', name: 'Server room', state: 'claimed', device: { model: 'AXIS A1210', serial: 'B8A44F0D3E4F' }, inventory: { doors: [inv.doors[0]] },
    settings: { latest: 3, applied: 2, error: '', current: false }, last_seen: now, health: {} },
]
const DOORS = [
  { id: 'd1', name: 'Main entrance', controller_id: 'c1', controller_door: 'Axis-b8a44f:door1', access_time_s: 7, open_too_long_s: 30, pre_alarm_s: 5, unlock_schedule_id: 'sc1' },
  { id: 'd2', name: 'Staff entrance', controller_id: 'c1', controller_door: 'Axis-b8a44f:door2', access_time_s: 7, open_too_long_s: 30, pre_alarm_s: 5, unlock_schedule_id: null },
  { id: 'd3', name: 'IT closet', controller_id: 'c2', controller_door: 'Axis-b8a44f:door1', access_time_s: 5, open_too_long_s: 60, pre_alarm_s: 5, unlock_schedule_id: null },
]
const WEEK = ['mo', 'tu', 'we', 'th', 'fr']
const SCHEDULES = [
  { id: 'sc1', name: 'Business hours', windows: [{ days: WEEK, start: '08:00', end: '18:00' }], on_holidays: 'off' },
  { id: 'sc2', name: 'Extended hours', windows: [{ days: WEEK, start: '06:00', end: '22:00' }, { days: ['sa'], start: '08:00', end: '14:00' }], on_holidays: 'off' },
  { id: 'sc3', name: 'Cleaning crew hours', windows: [{ days: WEEK, start: '18:00', end: '23:00' }], on_holidays: 'normal' },
]
const GROUPS = [
  { id: 'g1', name: 'Staff', rules: [{ doors: ['d1', 'd2'], schedule_id: 'sc2' }] },
  { id: 'g2', name: 'Managers', rules: [{ doors: ['d1', 'd2'], schedule_id: null }] },
  { id: 'g3', name: 'IT', rules: [{ doors: ['d3'], schedule_id: null }] },
  { id: 'g4', name: 'Cleaning crew', rules: [{ doors: ['d1', 'd2'], schedule_id: 'sc3' }] },
]
const HOLIDAYS = { days: [['2026-01-01', "New Year's Day"], ['2026-05-25', 'Memorial Day'], ['2026-07-03', 'Independence Day'], ['2026-09-07', 'Labor Day'],
  ['2026-11-26', 'Thanksgiving'], ['2026-11-27', 'Day after Thanksgiving'], ['2026-12-25', 'Christmas Day']].map(([day, name]) => ({ day, name })) }
const holder = (id, name, groups, o = {}) => ({ id, name, ref: `E-${id.slice(1)}`, email: '', person_id: null, suspended: false, valid_from: null, valid_to: null, groups, ...o })
const PEOPLE = [holder('h100', 'Alice Smith', ['g1', 'g2']), holder('h101', 'Bob Jones', ['g1']), holder('h102', 'Carol Diaz', ['g1', 'g3']),
  holder('h103', 'Dan Kim', ['g4'], { suspended: true }), holder('h104', 'Eve Park', ['g1'])]
const ev = (seq, mins, topic, o = {}) => ({ controller_id: 'c1', seq, occurred_at: new Date(Date.now() - mins * 60e3).toISOString(), received_at: now, topic,
  door_id: 'd1', door: 'Main entrance', cardholder_id: null, cardholder: null, reason: null, state: null, ...o })
const EVENTS = [ev(9, 2, 'AccessControl/AccessGranted/Credential', { cardholder: 'Alice Smith' }), ev(8, 14, 'AccessControl/Denied/Credential', { cardholder: 'Dan Kim', reason: 'CredentialNotEnabled' }),
  ev(7, 40, 'Door/State/DoorAlarm', { state: 'DoorOpenTooLong', door: 'Staff entrance' }), ev(6, 95, 'AccessControl/Denied/CredentialNotFound/Card'),
  ev(5, 300, 'AccessControl/AccessGranted/Credential', { cardholder: 'Carol Diaz', door: 'IT closet' })]
const CATALOG = JSON.parse(readFileSync(new URL('../../contract/templates/catalog.json', import.meta.url)))   // the API's own catalog
const MEMBERS = [{ person_id: 'm1', name: 'Ada Owner', email: 'ada@example.com', role: 'owner', scope: { all: true }, source: 'direct', pending: false },
  { person_id: 'm2', name: 'Partner support', email: '', role: 'admin', scope: { all: true }, source: 'partner', pending: false },
  { person_id: 'm3', name: 'Fay Front', email: 'fay@example.com', role: 'operator', scope: { sites: ['s1'] }, source: 'direct', pending: false }]
const AUDIT = [{ at: now, actor: 'Partner support', action: 'site.publish', target_type: 'site', target_id: 's1', detail: {} },
  { at: now, actor: 'Ada Owner', action: 'cardholder.add', target_type: 'cardholder', target_id: 'h1', detail: { name: 'Eve Park' } }]

const answers = (who) => ({
  '/me': [200, who === 'tech' ? me([tech(), tech({ id: 't2', name: 'Birch Co', status: 'suspended' }), tech({ id: 't3', name: 'Elm Street School' })], { name: 'Tom Tech' }) : me([tenant()])],
  '/templates': [200, CATALOG],
  '/tenants/t1/sites': [200, SITES], '/tenants/t2/sites': [200, SITES], '/tenants/t3/sites': [200, SITES],
  '/tenants/t1/controllers': [200, CONTROLLERS], '/tenants/t2/controllers': [200, []], '/tenants/t3/controllers': [200, [{ ...CONTROLLERS[0], last_seen: null }]],
  '/tenants/t1/sites/s1/doors': [200, who === 'setup' ? [] : DOORS], '/tenants/t1/sites/s1/schedules': [200, SCHEDULES], '/tenants/t1/sites/s1/groups': [200, GROUPS],
  '/tenants/t1/sites/s2/groups': [200, []], '/tenants/t1/sites/s1/holidays': [200, HOLIDAYS], '/tenants/t1/cardholders': [200, PEOPLE],
  '/tenants/t1/cardholders/h100/credentials': [200, [{ id: 'k1', kind: 'card', card_format: 'h10301', card_facility: 12, hint: '…456', enabled: true, valid_from: null, valid_to: null },
    { id: 'k2', kind: 'pin', card_format: null, card_facility: null, hint: '', enabled: true, valid_from: null, valid_to: null }]],
  '/tenants/t1/sites/s1/events': [200, EVENTS], '/tenants/t1/members': [200, MEMBERS], '/tenants/t1/audit': [200, AUDIT],
})

// [file name, route, who, steps]: steps are buttons to click, radios to pick, in order.
const PAGES = [
  ['overview', '/overview', 'owner'], ['doors', '/doors', 'owner'], ['people', '/people', 'owner'], ['person', '/people', 'owner', [{ button: 'Alice Smith' }]],
  ['access', '/access', 'owner'], ['events', '/events', 'owner'], ['customers-tech', '/', 'tech'], ['team', '/settings/team', 'owner'], ['audit', '/settings/audit', 'owner'],
  ['setup-1-controllers', '/setup', 'setup'],
  ['setup-2-template', '/setup', 'setup', [{ button: 'Next: choose a template' }, { radio: 'Office' }]],
  ['setup-3-doors', '/setup', 'setup', [{ button: 'Next: choose a template' }, { radio: 'Office' }, { button: 'Next: which door is which' }]],
  ['setup-2-school', '/setup', 'setup', [{ button: 'Next: choose a template' }, { radio: 'School' }]],
  ['setup-3-multifamily', '/setup', 'setup', [{ button: 'Next: choose a template' }, { radio: 'Multifamily' }, { button: 'Next: which door is which' }]],
  ['setup-2-gate', '/setup', 'setup', [{ button: 'Next: choose a template' }, { radio: 'Gate' }]],
].filter(([name]) => !only || name.includes(only))

mkdirSync('screenshots', { recursive: true })
const env = { ...process.env, VITE_API_URL: API, VITE_OIDC_ISSUER: 'http://idp.test', VITE_OIDC_CLIENT_ID: 'x', VITE_OIDC_AUDIENCE_PROJECT: '1', VITE_DEV_TOKEN_LOGIN: '1' }
const vite = spawn('npx', ['vite', '--port', String(PORT), '--strictPort'], { env, stdio: 'ignore', detached: true })
const stop = () => { try { process.kill(-vite.pid) } catch { /* already gone */ } }
process.on('exit', stop)

for (let i = 0; i < 100; i++) { try { if ((await fetch(`http://localhost:${PORT}/`)).ok) break } catch { /* not up yet */ } await new Promise((r) => setTimeout(r, 200)) }
const browser = await chromium.launch({ executablePath })
try {
  for (const [name, route, who, steps = []] of PAGES) {
    for (const [size, viewport] of Object.entries(SIZES)) {
      const ctx = await browser.newContext({ viewport, deviceScaleFactor: 1 })
      await ctx.addInitScript(() => sessionStorage.setItem('pe-dev-token', 'screenshot'))
      const table = answers(who)
      await ctx.route(`${API}/**`, async (r) => {
        const path = new URL(r.request().url()).pathname
        if (r.request().method() === 'OPTIONS') return r.fulfill({ status: 204, headers: { 'access-control-allow-origin': '*', 'access-control-allow-headers': '*', 'access-control-allow-methods': '*' } })
        const [status, body] = table[path] ?? [404, { detail: 'no fixture' }]
        return r.fulfill({ status, contentType: 'application/json', headers: { 'access-control-allow-origin': '*' }, body: JSON.stringify(body) })
      })
      const page = await ctx.newPage()
      await page.goto(`http://localhost:${PORT}${route}`)
      await page.waitForTimeout(700)
      for (const s of steps) {
        if (s.button) await page.getByRole('button', { name: s.button }).first().click()
        if (s.radio) await page.getByRole('radio', { name: new RegExp(s.radio) }).check()
        await page.waitForTimeout(400)
      }
      await page.screenshot({ path: `screenshots/${name}-${size}.png`, fullPage: true })
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
      if (overflow > 0) console.log(`HORIZONTAL SCROLL ${name} ${size}: ${overflow}px`)
      await ctx.close()
    }
    console.log('shot', name)
  }
} finally {
  await browser.close()
  stop()
}

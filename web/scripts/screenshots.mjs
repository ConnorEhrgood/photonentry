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
const tenant = (o = {}) => ({ id: 't1', name: 'Cedar Works', slug: 'cedar-works', former_slugs: [], status: 'active', partner_id: null, role: 'owner', scope: { all: true }, source: 'direct', expires_at: null, capabilities: OWNER, ...o })
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
const intercom = (o) => ({ id: 'i1', name: 'Front door intercom', door_id: 'd1', door: 'Main entrance', model: 'S532', mac: '0C:11:05:AA:BB:CC', relay_address: '',
  relay_target: '10.152.0.20:8742', sip_server: 'vox.photonind.com', sip_port: 5061, sip_transport: 'tls', sip_user: 'cw-door-101', sip_password_set: true,
  vox_station_id: '', sip_synced_at: null,
  last_fetch_at: now, last_fetch_ip: '10.152.0.31', ...o })
const INTERCOMS = [intercom({ vox_station_id: 'ds-1', sip_synced_at: now }), intercom({ id: 'i2', name: 'Staff entrance intercom', door_id: 'd2', door: 'Staff entrance', model: 'X915V2', mac: '0C:11:05:01:02:03',
  last_fetch_at: null, relay_target: '' })]
const CATALOG = JSON.parse(readFileSync(new URL('../../contract/templates/catalog.json', import.meta.url)))   // the API's own catalog
const MEMBERS = [{ person_id: 'm1', name: 'Ada Owner', email: 'ada@example.com', role: 'owner', scope: { all: true }, source: 'direct', pending: false },
  { person_id: 'm2', name: 'Partner support', email: '', role: 'admin', scope: { all: true }, source: 'partner', pending: false },
  { person_id: 'm3', name: 'Fay Front', email: 'fay@example.com', role: 'operator', scope: { sites: ['s1'] }, source: 'direct', pending: false }]
const AUDIT = [{ at: now, actor: 'Partner support', action: 'site.publish', target_type: 'site', target_id: 's1', detail: {} },
  { at: now, actor: 'Ada Owner', action: 'cardholder.add', target_type: 'cardholder', target_id: 'h1', detail: { name: 'Eve Park' } }]

const APPS = { home: 'https://account.photonind.com/', organization: { id: 't1', slug: 'cedar-works', name: 'Cedar Works' }, site: { id: 's1', slug: 'cw-main', name: 'Main office' },
  apps: [['account', 'PhotonID', 'open'], ['console', 'PhotonConsole', 'open'], ['guard', 'PhotonGuard', 'open'], ['entry', 'PhotonEntry', 'open'], ['vox', 'PhotonVox', 'not_enabled'],
    ['board', 'PhotonBoard', 'no_access'], ['edge', 'PhotonEdge', 'coming']].map(([key, name, state]) => ({ key, name, state, ...(state === 'open' ? { url: `https://${key}.photonind.com/org/cedar-works/site/cw-main/` } : {}) })) }
const LOCKDOWN = { id: 'l1', site_id: 's1', site: 'Main office', whole_site: true, reason: 'Threat reported in the parking lot', source: 'app',
  started_by: 'Fay Front', started_at: new Date(Date.now() - 4 * 60e3).toISOString(), active: true, ended_at: null, ended_by: null, end_reason: null,
  doors: [{ door_id: 'd1', door: 'Main entrance', state: 'done', error: '' }, { door_id: 'd2', door: 'Staff entrance', state: 'done', error: '' },
    { door_id: 'd3', door: 'IT closet', state: 'expired', error: '' }] }
const REC = { id: 'r1', door_id: 'd1', jurisdiction: 'PA', lock_type: 'strike_fail_secure', lock_type_label: 'Electric strike, fail-secure', failure_state: 'fail_secure',
  egress: 'Lever, free egress', special_locking: 'none', fire_release: 'tested', fire_tested_on: '2026-11-10', fire_tested_by: 'Bo Fire (Keystone Fire)',
  rex_checked: true, contact_checked: true, reader_ul_verified: false, ahj_reference: 'Pittsburgh permit EL-2026-0412', installer: 'Ann Lee',
  license: 'PA Pittsburgh electrical trade license ETL-5521, Ann Lee, to 2027-03-31', notes: '', signed_by: 'Partner support', signed_at: '2026-11-14T15:00:00Z',
  voided_at: null, voided_by: null, void_reason: null }
const COMMISSIONING = { jurisdiction: 'PA', required_license: { WV: 'wv_sp_lv' },
  lock_types: { strike_fail_secure: 'Electric strike, fail-secure', strike_fail_safe: 'Electric strike, fail-safe', maglock: 'Magnetic lock', other: 'Other' },
  special_locking: { none: 'None', delayed_egress: 'Delayed egress', controlled_egress: 'Controlled egress', sensor_release: 'Sensor release (maglock)' },
  doors: [{ door_id: 'd1', door: 'Main entrance', in_service: true, why: '', record: REC }, { door_id: 'd2', door: 'Staff entrance', in_service: false, why: 'never', record: null },
    { door_id: 'd3', door: 'IT closet', in_service: false, why: 'voided', record: { ...REC, id: 'r3', door_id: 'd3', voided_at: now, void_reason: 'New lock fitted' } }] }
const LIC = { kinds: { PA: { pa_pittsburgh_electrical: 'Pittsburgh electrical trade license', pa_hicpa: 'Home Improvement Contractor (HICPA)', other: 'Other' },
  OH: { oh_ocilb_electrical: 'OCILB electrical contractor', other: 'Other' }, WV: { wv_sp_lv: 'Specialty Low-Voltage Electrician (SP-LV), State Fire Marshal', other: 'Other' } },
  can_manage_partner: true, can_manage_organization: true, licenses: [
    { id: 'l1', owner: 'partner', state: 'PA', kind: 'pa_pittsburgh_electrical', kind_label: 'Pittsburgh electrical trade license', holder: 'Ann Lee', number: 'ETL-5521',
      expires_on: '2027-03-31', expired: false, expiring: false, removed: false, text: '' },
    { id: 'l2', owner: 'partner', state: 'WV', kind: 'wv_sp_lv', kind_label: 'Specialty Low-Voltage Electrician (SP-LV), State Fire Marshal', holder: 'Ben Ortiz',
      number: 'SPLV-20877', expires_on: '2026-12-01', expired: false, expiring: true, removed: false, text: '' }] }
const answers = (who) => ({
  '/tenants/t1/sites/s1/commissioning': [200, COMMISSIONING], '/tenants/t1/licenses': [200, LIC],
  '/tenants/t1/sites/s1/doors/d1/commissioning': [200, [REC]],
  '/tenants/t1/lockdowns/active': [200, who === 'lockdown' ? [LOCKDOWN] : []],
  '/tenants/t1/sites/s1/lockdowns': [200, who === 'lockdown' ? [LOCKDOWN] : []],
  '/v1/me/apps': [200, APPS],
  '/me': [200, who === 'tech' ? me([tech(), tech({ id: 't2', name: 'Birch Co', status: 'suspended' }), tech({ id: 't3', name: 'Elm Street School' })], { name: 'Tom Tech' }) : me([tenant()])],
  '/templates': [200, CATALOG],
  '/tenants/t1/sites': [200, SITES], '/tenants/t2/sites': [200, SITES], '/tenants/t3/sites': [200, SITES],
  '/tenants/t1/controllers': [200, CONTROLLERS], '/tenants/t2/controllers': [200, []], '/tenants/t3/controllers': [200, [{ ...CONTROLLERS[0], last_seen: null }]],
  '/tenants/t1/sites/s1/doors': [200, who === 'setup' ? [] : DOORS], '/tenants/t1/sites/s1/schedules': [200, SCHEDULES], '/tenants/t1/sites/s1/groups': [200, GROUPS],
  '/tenants/t1/sites/s2/groups': [200, []], '/tenants/t1/sites/s1/holidays': [200, HOLIDAYS], '/tenants/t1/cardholders': [200, PEOPLE],
  '/tenants/t1/cardholders/h100/credentials': [200, [{ id: 'k1', kind: 'card', card_format: 'h10301', card_facility: 12, hint: '…456', enabled: true, valid_from: null, valid_to: null },
    { id: 'k2', kind: 'pin', card_format: null, card_facility: null, hint: '', enabled: true, valid_from: null, valid_to: null }]],
  '/tenants/t1/sites/s1/events': [200, EVENTS], '/tenants/t1/members': [200, MEMBERS], '/tenants/t1/audit': [200, AUDIT],
  '/tenants/t1/integrations/guard': [200, { connected: true, enabled: true, token_hint: '…9f2c', last_ok_at: now, last_error: '', last_error_at: null, sent: 1284,
    guard_api_url: 'https://api.guard.photonind.com', bindings: DOORS.map((d) => ({ door_id: d.id, door: d.name, site: 'Main office', binding: `entry-door-0d1b2c3d-${d.id}00-4e5f-8a9b-0c1d2e3f4a5b` })) }],
  '/tenants/t1/sites/s1/intercoms': [200, INTERCOMS],
  '/tenants/t1/integrations/vox': [200, { connected: true, token_hint: '…7c1e', last_ok_at: now, last_error: '', last_error_at: null,
    vox_api_url: 'https://api.vox.photonind.com', intercoms: 1 }],
  '/tenants/t1/integrations/vox/stations': [200, [{ id: 'ds-1', name: 'Front door', site_id: 's1', extension: '901' },
    { id: 'ds-2', name: 'Staff entrance', site_id: 's1', extension: '902' }]],
  '/tenants/t1/sites/s1/intercoms/i1/setup': [200, { provision_url: 'https://link.entry.photonind.com/provision/v1/Xq7mR2vK9pLw4nB8cT3yZf6hJ1sD5gA0/', unlock_code: '#',
    admin_user: 'admin', admin_password: 'r8TqW2mZx5KpL9vBn3CjH7Ds' }],
  '/tenants/t1/integrations/console/tokens': [200, [{ id: 'k1', name: 'PhotonConsole', console_tenant_id: null, created_at: now, last_used_at: now, revoked: false }]],
})

// [file name, route, who, steps]: steps are buttons to click, radios to pick, in order.
const PAGES = [
  ['org-home', '/org/cedar-works/', 'owner'], ['site-home', '/org/cedar-works/site/cw-main/', 'owner'],
  ['switcher', '/org/cedar-works/site/cw-main/doors', 'owner', [{ button: 'Switch app' }]],
  ['lockdown-start', '/doors', 'owner', [{ button: 'Lock down' }]], ['lockdown-active', '/doors', 'lockdown'],
  ['commission-form', '/doors', 'owner', [{ button: 'Staff entrance: commission' }]],
  ['commission-record', '/doors', 'owner', [{ button: 'Main entrance: commissioning record' }]], ['licenses', '/settings/licenses', 'owner'],
  ['overview', '/overview', 'owner'], ['doors', '/doors', 'owner'], ['people', '/people', 'owner'], ['person', '/people', 'owner', [{ button: 'Alice Smith' }]],
  ['access', '/access', 'owner'], ['events', '/events', 'owner'], ['customers-tech', '/', 'tech'], ['team', '/settings/team', 'owner'], ['guard', '/settings/guard', 'owner'], ['console', '/settings/console', 'owner'], ['vox', '/settings/vox', 'owner'],
  ['intercom-change', '/doors', 'owner', [{ button: 'Change' }]], ['audit', '/settings/audit', 'owner'],
  ['intercom-add', '/doors', 'owner', [{ button: 'Add an intercom' }]], ['intercom-setup', '/doors', 'owner', [{ button: 'Setup values' }]],
  ['setup-1-controllers', '/setup', 'setup'],
  ['setup-2-template', '/setup', 'setup', [{ button: 'Next: choose a template' }, { radio: 'Office' }]],
  ['setup-3-doors', '/setup', 'setup', [{ button: 'Next: choose a template' }, { radio: 'Office' }, { button: 'Next: which door is which' }]],
  ['setup-2-school', '/setup', 'setup', [{ button: 'Next: choose a template' }, { radio: 'School' }]],
  ['setup-3-multifamily', '/setup', 'setup', [{ button: 'Next: choose a template' }, { radio: 'Multifamily' }, { button: 'Next: which door is which' }]],
  ['setup-2-gate', '/setup', 'setup', [{ button: 'Next: choose a template' }, { radio: 'Gate' }]],
].filter(([name]) => !only || name.includes(only))

mkdirSync('screenshots', { recursive: true })
const env = { ...process.env, VITE_API_URL: API, VITE_OIDC_ISSUER: 'http://idp.test', VITE_OIDC_CLIENT_ID: 'x', VITE_OIDC_AUDIENCE_PROJECT: '1', VITE_DEV_TOKEN_LOGIN: '1', VITE_DIRECTORY_API_URL: API }
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

// The suite's sign-in contract (photonid docs/SIGNIN-PLAN.md) for PhotonEntry, end to end against the DEV PhotonID on LXC 800, with screenshots of
// PhotonEntry's own sign-in pages at 1440, 820 and 390. Modeled on photonid/directory/web/scripts/signin-contract.mjs, which also covers PhotonID's
// own pages (password reset, authenticator app, invitations); this one checks what is PhotonEntry's: the client registration and the app's pages.
//   VITE_API_URL=https://api.test npm run build && node scripts/signin-contract.mjs <output dir>
// The app is served by `vite preview` on http://localhost:5193 (the registered redirect; a secure context, so PKCE works) and signs in for real; its
// API is faked inside the browser (https://api.test), so a 401, 403 or 503 can be forced. The test person is made through the API and deleted at the end.
// Needs ~/keys/zitadel-dev-provisioner.pat (the dev instance's). Exits 1 on the first thing that is not as expected.
import { spawn } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { mkdirSync, readFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { chromium } from 'playwright-core'

const out = process.argv[2]
if (!out) { console.error('usage: signin-contract.mjs <output dir>'); process.exit(2) }
mkdirSync(out, { recursive: true })
const ISSUER = process.env.E2E_ISSUER || 'http://10.10.0.80:8085'
const APP = 'http://localhost:5193'
const PAT = readFileSync(join(homedir(), 'keys/zitadel-dev-provisioner.pat'), 'utf8').trim()
const SIZES = [[1440, 900], [820, 1180], [390, 844]]
const run = Date.now().toString(36)
const ok = (what) => console.log(`ok   ${what}`)
const fail = (what) => { console.error(`FAIL ${what}`); process.exitCode = 1; throw new Error(what) }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

// -- PhotonID (Zitadel) API, as the dev provisioner ------------------------------------------------------------------------------------------------
async function zitadel(method, path, body) {
  const r = await fetch(ISSUER + path, { method, headers: { Authorization: `Bearer ${PAT}`, 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined })
  const text = await r.text()
  if (!r.ok) throw new Error(`${method} ${path} -> ${r.status} ${text.slice(0, 300)}`)
  return text ? JSON.parse(text) : {}
}
const made = []
async function person(tag, password) {
  const email = `entry-${tag}-${run}@example.test`
  const { userId } = await zitadel('POST', '/v2/users/human', {
    username: email, profile: { givenName: 'Sam', familyName: 'Signin' }, email: { email, isVerified: true }, password: { password, changeRequired: false } })
  made.push(userId)
  return { id: userId, email }
}

// -- the app ---------------------------------------------------------------------------------------------------------------------------------------
// Its own process group, so stopping it stops vite too (killing npx alone leaves vite holding the port).
const preview = spawn('npx', ['vite', 'preview', '--port', '5193', '--strictPort'], { cwd: new URL('..', import.meta.url).pathname, stdio: 'ignore', detached: true })
const stopPreview = () => { try { process.kill(-preview.pid) } catch { /* already gone */ } }
process.on('exit', stopPreview)
for (let i = 0; i < 60; i++) { try { if ((await fetch(APP)).ok) break } catch { /* not up yet */ } await sleep(250) }

let api = 'ok' // what the faked PhotonEntry API answers on /me: ok | unauth | forbidden | pending | none (signed in, no organization)
const OWNER = ['entry.view', 'entry.events.view', 'entry.cardholders.view', 'entry.door.unlock', 'entry.lockdown', 'entry.cardholders.manage',
  'entry.credential.issue', 'entry.config.manage', 'entry.controller.manage', 'entry.members.view', 'entry.emergency.open', 'entry.audit.view']
const tenant = { id: 't1', name: 'Cedar Works', slug: '', former_slugs: [], status: 'active', partner_id: null, role: 'owner', scope: { all: true }, source: 'direct', expires_at: null, capabilities: OWNER }
let currentEmail = ''
const me = () => ({ id: 'p1', name: 'Sam Signin', email: currentEmail, is_platform_admin: false, tenants: api === 'none' ? [] : [tenant] })
const SITES = [{ id: 's1', slug: 'cw-main', name: 'Main office', address: '1 Mill Road, Pittsburgh PA', timezone: 'America/New_York' }]
const json = (route, status, body) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
const meCalls = []

const browser = await chromium.launch({
  executablePath: join(homedir(), '.cache/ms-playwright/chromium-1248/chrome-linux64/chrome'),
  args: ['--no-sandbox', `--unsafely-treat-insecure-origin-as-secure=${new URL(ISSUER).origin}`],
})
async function context() {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  await ctx.route('https://api.test/**', (route) => {
    const path = new URL(route.request().url()).pathname
    if (path === '/me') meCalls.push({ at: Date.now(), bearer: /^Bearer \S+/.test(route.request().headers().authorization || '') })
    if (api === 'unauth') return json(route, 401, { detail: 'Not authenticated' })
    if (path === '/me' && api === 'forbidden') return json(route, 403, { detail: { code: 'no_access', detail: 'This account is disabled.' } })
    if (path === '/me' && api === 'pending') return json(route, 503, { detail: { code: 'access_pending', detail: 'Your access is being set up.' } })
    if (path === '/me') return json(route, 200, me())
    if (path === '/tenants/t1/sites') return json(route, 200, SITES)
    return json(route, 200, path.endsWith('/holidays') ? { days: [] } : [])
  })
  return ctx
}
/** Every address the tab's main frame asked for, redirects included (an authorize answered with a redirect is never a page of its own). */
function watch(page) {
  const seen = []
  page.on('request', (r) => { if (r.isNavigationRequest() && r.frame() === page.mainFrame()) seen.push(r.url()) })
  return seen
}
const authorizeCount = (seen) => seen.filter((u) => u.startsWith(`${ISSUER}/oauth/v2/authorize`)).length
let n = 0
async function shot(page, name) {
  n++
  for (const [w, h] of SIZES) {
    await page.setViewportSize({ width: w, height: h })
    await sleep(250)
    await page.screenshot({ path: join(out, `${String(n).padStart(2, '0')}-${name}-${w}.png`), fullPage: true })
  }
  await page.setViewportSize({ width: 1440, height: 900 })
}
const onLogin = (page, part) => page.waitForURL((u) => u.href.startsWith(`${ISSUER}/ui/v2/login/${part}`), { timeout: 20000 })
async function typeLoginName(page, email) {
  await page.locator('input[name="loginName"], input[autocomplete="username"], input').first().fill(email)
  await page.getByRole('button', { name: 'Continue' }).click()
}
async function typePassword(page, password) {
  await onLogin(page, 'password')
  await page.locator('input[type="password"]').first().fill(password)
  await page.getByRole('button', { name: 'Continue' }).click()
}
async function skipMfaPrompt(page) {
  await page.waitForLoadState('networkidle')
  if (page.url().includes('/ui/v2/login/mfa/set')) await page.getByRole('button', { name: 'Not now' }).click()
}
const DEEP = `${APP}/people?q=sam#h`
const LANDED = `${APP}/org/t1/people?q=sam#h`        // an old address: the same page under the organization (the suite's addresses)

try {
  const password = `Pw-${randomBytes(6).toString('hex')}-A1!`
  const sam = await person('sam', password)
  currentEmail = sam.email
  ok(`test person made in PhotonID (${sam.email})`)

  // 1. No sign-in card: a deep link with no session lands straight on PhotonID's sign-in form; no sign-up offered there.
  const ctx = await context()
  const page = await ctx.newPage()
  const seen = watch(page)
  await page.goto(DEEP)
  await onLogin(page, 'loginname')
  if (seen.some((u) => u.startsWith(APP) && /\/login(\?|$)/.test(new URL(u).pathname))) fail('the app showed a sign-in page of its own')
  const authz = new URL(seen.find((u) => u.startsWith(`${ISSUER}/oauth/v2/authorize`)))
  if (authz.searchParams.get('redirect_uri') !== `${APP}/auth/callback`) fail(`redirect_uri is ${authz.searchParams.get('redirect_uri')}`)
  if (authz.searchParams.get('code_challenge_method') !== 'S256') fail('the sign-in does not use PKCE (S256)')
  if (!authz.searchParams.get('scope').includes('urn:zitadel:iam:org:project:id:399489273323061251:aud')) fail(`the token is not for PhotonEntry's API: scope ${authz.searchParams.get('scope')}`)
  if (!authz.searchParams.get('scope').includes('urn:zitadel:iam:org:project:id:398336253029777411:aud')) fail('the token does not reach the directory (the app switcher)')
  ok('signed out: straight from the deep link to PhotonID (no sign-in card), code + PKCE, the API project in the audience')
  await page.waitForLoadState('networkidle')
  if (await page.getByText(/Register|Create your PhotonID|sign up/i).count()) fail('PhotonID offers sign-up on a PhotonEntry sign-in')
  ok('no sign-up offered')
  await shot(page, 'photonid-sign-in')

  // 2. Password, then back to exactly the deep link, with a bearer token on the API.
  await typeLoginName(page, sam.email)
  await typePassword(page, password)
  await page.waitForURL((u) => u.href.startsWith(APP) && !u.pathname.startsWith('/auth/'), { timeout: 20000 }).catch(async () => { await skipMfaPrompt(page) })
  if (page.url().includes('/ui/v2/login/mfa/set')) await skipMfaPrompt(page)
  await page.waitForURL(LANDED, { timeout: 20000 })
  await page.getByRole('heading', { name: 'People', exact: true }).waitFor()
  if (!meCalls.length || !meCalls.every((c) => c.bearer)) fail('the API was called without a bearer token')
  ok('deep link survived sign-in (/people?q=sam#h, now /org/t1/people?q=sam#h); the API gets a bearer token')
  await shot(page, 'signed-in')

  // 3. Silent SSO: a new tab (no tokens of its own) is signed in without seeing a PhotonID page.
  const p2 = await ctx.newPage()
  const seen2 = watch(p2)
  await p2.goto(`${APP}/doors`)
  await p2.getByRole('heading', { name: 'Doors', exact: true }).waitFor({ timeout: 20000 })
  const pages2 = seen2.filter((u) => u.includes('/ui/v2/login/') && !u.includes('/ui/v2/login/login?'))
  if (pages2.length) fail(`silent SSO showed a PhotonID page: ${pages2.join(' ')}`)
  if (authorizeCount(seen2) !== 1) fail(`silent SSO took ${authorizeCount(seen2)} trips to PhotonID`)
  ok('silent SSO: a new tab signed in with one trip to PhotonID and no page shown')
  await p2.close()

  // 4. No loop: the API refusing the new token right after sign-in is a page, after exactly one trip to PhotonID.
  api = 'unauth'
  const p3 = await ctx.newPage()
  const seen3 = watch(p3)
  await p3.goto(`${APP}/`)
  await p3.getByRole('heading', { name: "We couldn't sign you in" }).waitFor({ timeout: 20000 })
  await sleep(3000)
  if (authorizeCount(seen3) !== 1) fail(`a 401 after sign-in went to PhotonID ${authorizeCount(seen3)} times (a loop)`)
  ok('401 right after sign-in: the problem page, one trip to PhotonID, no loop')
  await shot(p3, 'sign-in-problem')
  await p3.close()

  // 5. A 403 is a page, never a redirect.
  api = 'forbidden'
  const p4 = await ctx.newPage()
  const seen4 = watch(p4)
  await p4.goto(`${APP}/`)
  await p4.getByRole('heading', { name: 'No access to PhotonEntry' }).waitFor({ timeout: 20000 })
  await sleep(2000)
  if (authorizeCount(seen4) !== 1) fail(`a 403 went to PhotonID ${authorizeCount(seen4)} times`)
  ok('403: a "No access to PhotonEntry" page with Sign out, no redirect')
  await shot(p4, 'no-access')
  await p4.close()

  // 6. Access pending (a fresh invitation the directory has not told PhotonEntry about yet): a page that asks again by itself, then the app.
  api = 'pending'
  const p5 = await ctx.newPage()
  const seen5 = watch(p5)
  await p5.goto(`${APP}/doors`)
  await p5.getByRole('heading', { name: 'Setting up your access to PhotonEntry' }).waitFor({ timeout: 20000 })
  await shot(p5, 'access-pending')
  const asked = meCalls.length
  api = 'ok'
  await p5.getByRole('heading', { name: 'Doors', exact: true }).waitFor({ timeout: 40000 })
  if (meCalls.length <= asked) fail('the pending page did not ask again')
  if (authorizeCount(seen5) !== 1) fail(`the pending page went to PhotonID ${authorizeCount(seen5)} times`)
  ok('access pending: a page that asks again by itself, then the app (no redirect)')
  await p5.close()

  // 7. Signed in, but no organization has PhotonEntry for this person.
  api = 'none'
  const p6 = await ctx.newPage()
  await p6.goto(`${APP}/`)
  await p6.getByRole('heading', { name: 'No access to PhotonEntry yet' }).waitFor({ timeout: 20000 })
  ok('no organization: a page pointing to Manage organization, with Sign out')
  await shot(p6, 'no-organization')
  await p6.close()
  api = 'ok'

  // 8. The moment of leaving for PhotonID (held back so it can be seen).
  const ctxWait = await context()
  await ctxWait.route(`${ISSUER}/.well-known/openid-configuration`, async (route) => { await sleep(4000); await route.continue() })
  const p7 = await ctxWait.newPage()
  await p7.goto(`${APP}/`)
  await p7.getByRole('status').filter({ hasText: 'Signing you in' }).waitFor()
  await shot(p7, 'signing-in')
  await ctxWait.close()

  // 9. Sign out: the PhotonID session ends and the sign-in form shows (not a silent sign-in).
  const seenOut = watch(page)
  await page.getByRole('button', { name: /Sam Signin/ }).click()
  await page.getByRole('menuitem', { name: 'Sign out' }).click()
  await onLogin(page, 'loginname')
  if (!seenOut.some((u) => u.startsWith(`${APP}/auth/signed-out`))) fail('sign-out did not come back through /auth/signed-out')
  if (!seenOut.some((u) => u.startsWith(`${ISSUER}/oauth/v2/authorize`) && u.includes('prompt=login'))) fail('after sign-out the sign-in did not ask for prompt=login')
  ok('sign-out: PhotonID session ended, back through /auth/signed-out to the sign-in form (prompt=login)')
  const p8 = await ctx.newPage()
  await p8.goto(`${APP}/doors`)
  await p8.waitForURL((u) => u.href.startsWith(`${ISSUER}/ui/v2/login/`) && !u.href.includes('/ui/v2/login/login?'), { timeout: 20000 })
  await p8.waitForLoadState('networkidle')
  if (p8.url().startsWith(APP)) fail('after sign-out a new tab was signed in silently')
  ok(`after sign-out a new tab is not signed in silently (PhotonID shows ${new URL(p8.url()).pathname.split('/').pop()})`)
  await shot(p8, 'after-sign-out-new-tab')
  await p8.close()
  await ctx.close()
} catch (e) {
  if (!process.exitCode) { console.error(`FAIL ${e.message}`); process.exitCode = 1 }
  let i = 0
  for (const c of browser.contexts()) for (const p of c.pages()) {
    await p.screenshot({ path: join(out, `FAILED-${++i}.png`), fullPage: true }).catch(() => {})
    console.error(`  tab ${i}: ${p.url()}`)
  }
} finally {
  for (const id of made) await zitadel('DELETE', `/v2/users/${id}`).catch((e) => console.error(`could not delete ${id}: ${e.message}`))
  console.log(`cleanup: ${made.length} test person(s) deleted`)
  await browser.close()
  stopPreview()
}

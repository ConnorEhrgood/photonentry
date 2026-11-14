import { render } from '@testing-library/react'
import type { ReactElement } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'
import type { Me, TenantAccess } from '../api/types'
import { AuthProvider, useAuth } from '../auth/AuthContext'
import { TenantProvider } from '../auth/TenantContext'
import type { TokenSource } from '../auth/tokenSource'
import type { PhotonSignIn } from '../ph-auth/signin'

/** A stand-in for the shared sign-in (ph-auth's PhotonSignIn): each step is a spy. */
export function fakeAuth() {
  return {
    signIn: vi.fn(async (_returnTo?: string, _opts?: unknown) => {}),
    signOut: vi.fn(async () => {}),
    handleCallback: vi.fn(async () => '/overview'),
    afterSignOut: vi.fn(async () => {}),
    unauthorized: vi.fn(async (): Promise<'redirect' | 'problem'> => 'redirect'),
    getAccessToken: vi.fn(async () => null),
  }
}

export class FakeSource implements TokenSource {
  supportsPaste = true
  token: string | null
  readonly fake = fakeAuth()
  /** The shared sign-in the auth routes drive (a fake here). */
  auth = this.fake as unknown as PhotonSignIn
  constructor(token: string | null = 'tok') { this.token = token }
  getAccessToken = async () => this.token
  signIn = vi.fn(async (_returnTo: string) => {})
  signOut = vi.fn(async () => { this.token = null })
  /** What the shared sign-in says about a 401: 'redirect' (the session ended) unless a test says 'problem' (just signed in). */
  unauthorized = vi.fn(async (): Promise<'redirect' | 'problem'> => { this.token = null; return 'redirect' })
  paste = (t: string) => { this.token = t }
}

const VIEWER_CAPS = ['entry.view', 'entry.events.view']
const OPERATOR_CAPS = [...VIEWER_CAPS, 'entry.cardholders.view', 'entry.door.unlock', 'entry.lockdown', 'entry.visitors.manage']
const ADMIN_CAPS = [...OPERATOR_CAPS, 'entry.cardholders.manage', 'entry.credential.issue', 'entry.config.manage', 'entry.controller.manage', 'entry.members.view']
const ALL = [...ADMIN_CAPS, 'entry.emergency.open', 'entry.audit.view']

export const OWNER: TenantAccess = {
  id: 't1', name: 'Cedar Works', slug: '', former_slugs: [], status: 'active', partner_id: null, role: 'owner', scope: { all: true }, source: 'direct', expires_at: null, capabilities: ALL,
}
export const VIEWER: TenantAccess = { ...OWNER, role: 'viewer', capabilities: VIEWER_CAPS }
export const OPERATOR: TenantAccess = { ...OWNER, role: 'operator', capabilities: OPERATOR_CAPS }
/** A partner technician: admin of two customers through the partner grant. */
export const TECH_A: TenantAccess = { ...OWNER, role: 'admin', source: 'partner', partner_id: 'pa', capabilities: ADMIN_CAPS }
export const TECH_B: TenantAccess = { ...TECH_A, id: 't2', name: 'Birch Co' }

export const meWith = (...tenants: TenantAccess[]): Me => ({ id: 'p1', name: 'Ada Owner', email: 'ada@example.com', is_staff: false, is_platform_admin: false, tenants })
export const ME = meWith(OWNER)

/** Requests are JSON, except a WebRTC offer, which is SDP text. */
const parseBody = (text: string): unknown => { try { return JSON.parse(text) } catch { return text } }

type Handler = (body?: unknown) => unknown
/** A fake fetch keyed by "METHOD /path". Unmatched requests fail the test loudly. */
export function fakeFetch(routes: Record<string, Handler | unknown>) {
  const calls: { method: string; path: string; body?: unknown }[] = []
  const fn = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    const u = new URL(String(url))
    const method = init?.method ?? 'GET'
    const key = `${method} ${u.pathname}${u.search}`
    const keyNoQuery = `${method} ${u.pathname}`
    calls.push({ method, path: u.pathname + u.search, body: init?.body ? parseBody(String(init.body)) : undefined })
    const h = key in routes ? routes[key] : routes[keyNoQuery]
    if (h === undefined) throw new Error(`unmocked request: ${key}`)
    const out = typeof h === 'function' ? await (h as Handler)(calls[calls.length - 1].body) : h
    if (out instanceof Response) return out
    return new Response(out === null ? null : JSON.stringify(out), { status: out === null ? 204 : 200 })
  })
  return { fn: fn as unknown as typeof fetch, calls }
}

/** Mirrors the app's Protected wrapper: nothing under it renders until the session is ready. */
function Ready({ children, bare }: { children: ReactElement; bare?: boolean }) {
  const { status } = useAuth()
  if (bare) return children
  return status === 'ready' ? children : null
}

export function renderApp(ui: ReactElement, opts: { routes: Record<string, Handler | unknown>; route?: string; me?: Me; source?: FakeSource; bare?: boolean } = { routes: {} }) {
  // Every page's banner asks for active lockdowns; none unless a test says otherwise.
  const { fn, calls } = fakeFetch({ 'GET /me': opts.me ?? ME, 'GET /tenants/t1/lockdowns/active': [], 'GET /tenants/t2/lockdowns/active': [], ...opts.routes })
  const source = opts.source ?? new FakeSource()
  vi.stubGlobal('fetch', fn)
  const utils = render(
    <MemoryRouter initialEntries={[opts.route ?? '/']}>
      <AuthProvider source={source} baseUrl="https://api.test">
        <Ready bare={opts.bare}><TenantProvider>{ui}</TenantProvider></Ready>
      </AuthProvider>
    </MemoryRouter>,
  )
  return { ...utils, calls, source }
}

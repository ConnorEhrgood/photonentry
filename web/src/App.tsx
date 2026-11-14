import { Navigate, Outlet, Route, Routes, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import logo from './assets/photon-logo.png'
import { useAuth } from './auth/AuthContext'
import { DevTokenPage } from './auth/DevTokenPage'
import { orgKey, TenantProvider, useTenant } from './auth/TenantContext'
import { isIntegrator, Layout } from './components/Layout'
import { AccessPage } from './pages/Access'
import { AuditPage } from './pages/Audit'
import { LicensesPage } from './pages/Commissioning'
import { PassPageRoute, VisitorsPage } from './pages/Visitors'
import { CustomersPage } from './pages/Customers'
import { DoorsPage, OverviewPage } from './pages/Doors'
import { EventsPage } from './pages/Events'
import { ConsoleSettingsPage, GuardSettingsPage, VoxSettingsPage } from './pages/Integrations'
import { NotForYou, SettingsHub, SettingsIndex } from './pages/Hubs'
import { PeoplePage } from './pages/People'
import { SetupPage } from './pages/Setup'
import { TeamPage } from './pages/Team'
import { AccessPending, CallbackRoute, NoAccess, RequireSignIn, SignedOutRoute, SignInProblem, SigningIn } from './ph-auth/pages'

/** Everything but the auth routes needs a session. Signed out: straight to PhotonID with the deep link kept (the suite's sign-in contract, ph-auth).
 *  A 401 just after signing in, and any 403, are pages here: never another redirect. */
function Protected() {
  const { status, error, source, signIn, signOut } = useAuth()
  const out = () => void signOut()
  if (status === 'loading') return <SigningIn logo={logo} title="Loading" hint="Opening PhotonEntry." />
  if (status === 'signedOut') {
    if (source.supportsPaste) return <Navigate to="/login" replace /> // development builds: the paste-a-token page
    return <RequireSignIn auth={source.auth!} signedIn={false} logo={logo}>{null}</RequireSignIn>
  }
  if (status === 'problem') return <SignInProblem logo={logo} onRetry={() => void signIn()} onSignOut={out} detail="PhotonID signed you in, but PhotonEntry did not accept the sign-in." />
  if (status === 'pending') return <AccessPending logo={logo} product="PhotonEntry" onSignOut={out} />
  if (status === 'noAccess') return <NoAccess logo={logo} product="PhotonEntry" detail={error} onSignOut={out} />
  if (status === 'error') return <div className="ph-auth"><div className="ph-card"><h1>Something went wrong</h1><p className="ph-error">{error}</p><button className="ph-btn" onClick={() => location.reload()}>Try again</button></div></div>
  return <TenantProvider><Outlet /></TenantProvider>
}

/** PhotonID sends the browser here with ?code=…: load the person, then go where they were headed. */
function Callback() {
  const { source, refreshMe } = useAuth()
  const nav = useNavigate()
  if (!source.auth) return <Navigate to="/login" replace />
  return <CallbackRoute auth={source.auth} logo={logo} onSignedIn={async (to) => { await refreshMe(); nav(to, { replace: true }) }} />
}

/** PhotonID's post-logout address: straight on to its sign-in form. */
function SignedOut() {
  const { source } = useAuth()
  if (!source.auth) return <Navigate to="/login" replace />
  return <SignedOutRoute auth={source.auth} logo={logo} />
}

/** Where "/" goes: the customer list for an integrator, their organization's home for anyone else. `?organization=<id or slug>&site=<slug>`
 *  (how other apps may link in) opens that organization and site. */
export function Home() {
  const { tenants, current } = useTenant()
  const [params] = useSearchParams()
  const asked = params.get('organization')
  if (asked) {
    const t = tenants.find((x) => x.id === asked || x.slug === asked || x.former_slugs?.includes(asked))
    const site = params.get('site')
    return <Navigate to={`/org/${t ? orgKey(t) : asked}/${site ? `site/${encodeURIComponent(site)}/` : ''}`} replace />
  }
  if (isIntegrator(tenants)) return <Navigate to="/customers" replace />
  return current ? <Navigate to={`/org/${orgKey(current)}/`} replace /> : <Outlet />
}

/** Addresses from before the suite's convention (/doors, /settings/team …) still work: the same page in the organization used last. */
function Legacy() {
  const { current } = useTenant()
  const { pathname, search, hash } = useLocation()
  if (!current) return <Navigate to="/" replace />
  // An unknown page inside an organization's address goes to that organization's home (never nested under another /org/).
  const inOrg = pathname.match(/^\/org\/[^/]+/)
  if (inOrg) return <Navigate to={`${inOrg[0]}/`} replace />
  return <Navigate to={`/org/${orgKey(current)}${pathname}${search}${hash}`} replace />
}

/** A page for people whose role includes `cap`; anyone else following a link there is told so (the API refuses them anyway). */
function Needs({ cap }: { cap: string }) {
  const { can } = useTenant()
  return can(cap) ? <Outlet /> : <NotForYou />
}

/** An organization's pages (and a site's: the same, on that site). Its home is the overview. */
function orgPages() {
  return (
    <>
      <Route element={<Needs cap="entry.view" />}>
        <Route index element={<OverviewPage />} />
        <Route path="overview" element={<OverviewPage />} />
        <Route path="doors" element={<DoorsPage />} />
        <Route path="access" element={<AccessPage />} />
      </Route>
      <Route element={<Needs cap="entry.config.manage" />}><Route path="setup" element={<SetupPage />} /></Route>
      <Route element={<Needs cap="entry.cardholders.view" />}><Route path="people" element={<PeoplePage />} /></Route>
      <Route element={<Needs cap="entry.events.view" />}><Route path="events" element={<EventsPage />} /></Route>
      <Route element={<Needs cap="entry.visitors.manage" />}><Route path="visitors" element={<VisitorsPage />} /></Route>
      <Route path="settings" element={<SettingsHub />}>
        <Route index element={<SettingsIndex />} />
        <Route element={<Needs cap="entry.members.view" />}><Route path="team" element={<TeamPage />} /></Route>
        <Route element={<Needs cap="entry.config.manage" />}>
          <Route path="guard" element={<GuardSettingsPage />} />
          <Route path="console" element={<ConsoleSettingsPage />} />
          <Route path="vox" element={<VoxSettingsPage />} />
          <Route path="licenses" element={<LicensesPage />} />
        </Route>
        <Route element={<Needs cap="entry.audit.view" />}><Route path="audit" element={<AuditPage />} /></Route>
      </Route>
    </>
  )
}

export function App() {
  return (
    <Routes>
      {/* `/login` is the development paste-a-token page; in production an old address for home. There is no sign-in page. */}
      <Route path="/login" element={<DevTokenPage />} />
      <Route path="/auth/callback" element={<Callback />} />
      <Route path="/auth/signed-out" element={<SignedOut />} />
      {/* A visitor's own pass: no sign-in; the link's token is the secret. */}
      <Route path="/pass/:token" element={<PassPageRoute />} />
      <Route element={<Protected />}>
        <Route element={<Layout />}>
          <Route index element={<Home />} />
          <Route path="customers" element={<CustomersPage />} />
          {/* The suite's addresses: an organization, and one of its sites (the same pages, on that site). */}
          <Route path="org/:orgSlug">
            {orgPages()}
            <Route path="site/:siteSlug">{orgPages()}</Route>
          </Route>
          <Route path="*" element={<Legacy />} />
        </Route>
      </Route>
    </Routes>
  )
}

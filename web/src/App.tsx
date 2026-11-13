import { Navigate, Outlet, Route, Routes, useNavigate } from 'react-router-dom'
import logo from './assets/photon-logo.png'
import { useAuth } from './auth/AuthContext'
import { DevTokenPage } from './auth/DevTokenPage'
import { TenantProvider, useTenant } from './auth/TenantContext'
import { isIntegrator, Layout } from './components/Layout'
import { AccessPage } from './pages/Access'
import { AuditPage } from './pages/Audit'
import { CustomersPage } from './pages/Customers'
import { DoorsPage, OverviewPage } from './pages/Doors'
import { EventsPage } from './pages/Events'
import { ConsoleSettingsPage, GuardSettingsPage } from './pages/Integrations'
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

/** Where "/" goes: the customer list for an integrator, the customer's overview for anyone else. */
export function Home() {
  const { tenants } = useTenant()
  return <Navigate to={isIntegrator(tenants) ? '/customers' : '/overview'} replace />
}

/** A page for people whose role includes `cap`; anyone else following a link there is told so (the API refuses them anyway). */
function Needs({ cap }: { cap: string }) {
  const { can } = useTenant()
  return can(cap) ? <Outlet /> : <NotForYou />
}

export function App() {
  return (
    <Routes>
      {/* `/login` is the development paste-a-token page; in production an old address for home. There is no sign-in page. */}
      <Route path="/login" element={<DevTokenPage />} />
      <Route path="/auth/callback" element={<Callback />} />
      <Route path="/auth/signed-out" element={<SignedOut />} />
      <Route element={<Protected />}>
        <Route element={<Layout />}>
          <Route index element={<Home />} />
          <Route path="customers" element={<CustomersPage />} />
          <Route element={<Needs cap="entry.view" />}>
            <Route path="overview" element={<OverviewPage />} />
            <Route path="doors" element={<DoorsPage />} />
            <Route path="access" element={<AccessPage />} />
          </Route>
          <Route element={<Needs cap="entry.config.manage" />}><Route path="setup" element={<SetupPage />} /></Route>
          <Route element={<Needs cap="entry.cardholders.view" />}><Route path="people" element={<PeoplePage />} /></Route>
          <Route element={<Needs cap="entry.events.view" />}><Route path="events" element={<EventsPage />} /></Route>
          <Route path="settings" element={<SettingsHub />}>
            <Route index element={<SettingsIndex />} />
            <Route element={<Needs cap="entry.members.view" />}><Route path="team" element={<TeamPage />} /></Route>
            <Route element={<Needs cap="entry.config.manage" />}>
              <Route path="guard" element={<GuardSettingsPage />} />
              <Route path="console" element={<ConsoleSettingsPage />} />
            </Route>
            <Route element={<Needs cap="entry.audit.view" />}><Route path="audit" element={<AuditPage />} /></Route>
          </Route>
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

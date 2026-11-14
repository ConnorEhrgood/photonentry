# PhotonEntry: build log

Dated notes, kept for their reasoning. They describe what was true on the day, not necessarily now.

## 2026-11-13: Step 1, the scaffold on a simulator

**Built.** Everything runs on the runner, with no hardware, no database and no Docker:
- **The site document** (`api/app/document.py`): its validation.
- **The compiler** to Axis's access-control objects (`api/app/compiler/`).
- **The link service:** hello and claim; settings versions; events exactly once and in order; commands with expiry; long-poll; Ed25519
  request signatures with a nonce window. It runs on an in-memory store.
- **The contract** (`contract/`): JSON Schemas generated from the protocol models; the compiled-settings schema; a sample; a signing vector
  shared by the Python and C signers.
- **The Axis simulator** (`sim/`) with its reference (`sim/reference/AXIS-PACS.md`).
- **`entry-link` in C:**
  - its identity key and signing;
  - hello and claim code;
  - two threads: a long-polled control sync, and event reading and pushing;
  - applying settings by difference;
  - a persistent event queue with a row-id cursor;
  - commands with expiry and de-duplication;
  - an hourly drift re-apply, and a retry of failed versions.
- **The ACAP manifest** (untested: Step 7).

**Verified, by tests:**
- 109 tests pass (`scripts/test-all.sh`).
- The CRITICAL cloud modules (signing, service, store, compiler, document) are at 100% branch coverage.
- **The simulator:** the compiled settings, applied to it, decide as intended. Office hours, Sundays, Christmas (a holiday exception),
  evenings that ignore holidays, PINs, suspended cardholders, validity windows, the front door's unlock schedule, forced and held-open
  alarms, lockdown and release, remote actions, REX.
- **End to end:** the real C binary between the simulator and the link service, all over HTTP, five times without a failure. It covers:
  - claim, and the inventory (read across pages of two);
  - settings applied;
  - a grant and a denial reaching the cloud with their tokens;
  - unlock, lockdown, a refused unlock while locked down, release;
  - every controller event in the cloud exactly once, in order;
  - a settings change, with stale objects removed and objects made by hand left alone;
  - a version the controller refuses: reported, not resent, then superseded;
  - 25 accesses during a cloud outage, all delivered afterwards;
  - a restart with events queued on disk;
  - the controller's API going away and coming back;
  - a disabled controller stopping.
- The C signer produces byte-for-byte the header the Python signer does.

**Not verified:**
- Anything on a real Axis controller: the ACAP build, the D-Bus service account, firmware behavior (BUILD-GUIDE GATE H).
- Postgres, sign-in, the web app (Steps 2–3).

**What Axis's documentation changed in the design:**
- **Services.** Schedules are their own service (`/vapix/schedule`, `axsch`), not ONVIF's. Holidays become an `ExceptionScheduleDefinition`
  on each schedule (not ONVIF special days). Credentials, access profiles, access points and users all live on `/vapix/pacs`.
- **Door unlock schedules** are `DoorScheduleConfiguration` objects linked from the door's configuration. With no priority level there must
  be exactly one DoorSchedule, so the compiler writes "Unlock during the schedule, then Lock at `standard_always`".
- **The event logger is a cursor.** `axlog:FetchEvents` takes a `RowID` cursor (up to 1000 rows a call) over a log of the last 30,000 events.
  That made exactly-once, in-order delivery simple: sequence numbers are assigned on reading, and the row cursor is persisted. The plan's
  "250k events" was the datasheet's figure for credentials; the event log is 30,000 (ARCHITECTURE corrected).
- **Forced and held-open doors** come from the controller itself (DoorAlarm `DoorForcedOpen` / `DoorOpenTooLong`, plus the DoorWarning
  pre-alarm). The cloud does not need to work them out, as it would for UniFi.
- **Card matching.** Axis's factory `CardOnly` profile matches `Card`, the reader's raw hex. The compiler writes `Card` and computes the
  Wiegand parity itself; it does not use `CardNr`. This works for any bit length without card-format configuration (34-bit cards from an
  Akuvox intercom included). Bench H5 confirms the padding.
- **ACAP access** goes through `http://127.0.0.12` with a D-Bus service account (Basic auth; up to 200 accounts, cleared on reboot).
  `entry-link` takes a configured login for now.

**Build decisions recorded in ARCHITECTURE (for Connor to confirm):** HTTPS long-polling instead of a WebSocket; the link service in the
Python API instead of Go; PINs encrypted, not hashed.

**Kept honest:**
- **The simulator's guesses** are listed in `docs/SIMULATOR.md` §"Choices Axis does not document".
- **Duplicate events after a crash.** A crash between appending to the queue and saving the row cursor re-queues those events. Duplicates
  are possible and losses are not; `ref` identifies a duplicate, and Step 4 de-duplicates by it.
- **Offline capacity.** The on-disk queue holds 10,000 events, and the controller's log holds 30,000 more. A site that makes over about
  40,000 events during one outage loses the oldest.

## 2026-11-13: Step 2, the database and the directory

**Built:**
- **Migration 0001** writes its tables out in SQL, so it means the same thing forever:
  - the three database roles;
  - the directory copy, with person documents' `platform_admin` and `partners`;
  - the audit log (append-only for every role);
  - controllers, settings versions, link commands and door events;
  - doors, schedules, the site holiday calendar, access groups, group memberships;
  - cardholders and credentials (sealed, fingerprinted).
- **Row-level security on every table**, with helpers that answer site questions by the strongest entry covering the site:
  - configuration is written by admins at their sites;
  - credentials are readable by admins only;
  - cardholders are readable by operators and up;
  - commands are written by operators at their sites, in their own name;
  - pending controllers are seen by the system role only.
- **Sign-in and the directory**, copied from PhotonVox's working code: token verification, first sign-in resolution, notify-then-pull,
  publishing the role catalog, the worker's periodic pull. Staff are now recognized from the directory itself: `platform_admin`, or
  membership of partner "photon".
- **The link on Postgres** (`PgStore`) passes the same store tests as the in-memory store. A held sync wakes through `LISTEN/NOTIFY`,
  counted in memory, so it costs no queries. Store calls run in the thread pool.
- **The integrator's API:**
  - claim a controller by code;
  - rename or disable it;
  - doors from the controller's inventory, schedules, holidays, access groups;
  - cardholders with their groups, credentials, and a bulk CSV import that checks every row before writing any;
  - publish: compile per controller, store a version only where it changed, everything or nothing;
  - remote door actions, lockdown and its end, command status, events with door and cardholder names, the audit trail ("Partner support"
    for partner staff).

**Verified:**
- 379 tests pass on the runner (a local Postgres 16) and on LXC 800 (Postgres 16 in Docker).
- The 17 CRITICAL modules are at 100% branch coverage (`api/tests/check_critical.py`); the whole is at 98%.
- **Isolation:** all 38 routes are closed to another organization's owner and to a stranger. Nothing of the first organization is found,
  shown or changed, even when named under the second organization's id.
- **Database level:** site-limited people see and write only their sites. Commands go in their own names only. The audit log refuses UPDATE
  and DELETE from every role.
- **End to end on Postgres, through the API, with the real C `entry-link` and the simulator,** each step by a signed-in person:
  - claim, set up and publish;
  - a grant that comes back with the cardholder's name;
  - a remote unlock carried out;
  - lockdown and its end;
  - every step in the owner's audit trail.

**Found and fixed: the start-up guard missed table owners.** It refused logins that were superusers or had BYPASSRLS. A role that **owns the
tables** also skips their policies, with neither flag, and the local test owner showed it. The guard now refuses any login that owns a public
table too. PhotonVox has the same check; its test database's owner is a superuser, so the gap never showed there. Worth the same change in
PhotonVox, in its own session.

**Decided while building (small; Connor may reverse):**
- **Door events are a plain table for now**, indexed by site and time. They become a TimescaleDB hypertable when volume calls for it, as
  PhotonGuard did.
- **One holiday calendar per site** (ARCHITECTURE §6.1's site calendar), listed for every schedule that is off on holidays.
- **Operators can read every cardholder's name in their organization** (events show who opened a door). Credentials stay admins-only.
- **A site-limited admin may add cardholders to the organization,** but give them only their own sites' groups. Removing a cardholder
  needs the right at every site they belong to.
- **Card numbers and PINs** are unique per organization, enforced by a keyed fingerprint (`FINGERPRINT_KEY`, separate from `SECRETS_KEY`
  so that rotating the sealing key changes no fingerprint).
- **There are no platform pages yet:** PhotonVox's platform routes were not copied.

**Not done here (later steps):** the web app (Step 3); door events normalized and sent to Guard and Console (Step 4); `PhotonEntry` in
PhotonID's catalog (GATE P).

## 2026-11-13: Step 3, the integrator's web app and the site templates

**Connor's direction:** templates for all four customer types (offices, schools, multifamily, gates), all likely clients; the office template
first and end to end; photon-ui and the shared `@photon/ui/auth` sign-in from the start.

**Built:**
- **Site templates** (`api/app/templates.py`). Each template has:
  - door slots, which the integrator maps to the controllers' own doors;
  - schedules, and access groups that combine (an office's IT person is in Staff and IT);
  - options (unlock the main entrance during business hours, open the vehicle gate in the day);
  - US business or federal holidays with weekend observance (July 4, 2026 is observed Friday the 3rd).

  Applying one creates everything at a site in one transaction and leaves it to be reviewed and published. Required slots only are suggested;
  an optional door is "not at this site" until someone says which it is, so a guess is never published. Four templates:
  - **office:** staff, managers, IT, cleaning crew;
  - **school:** staff, administrators, office staff, custodians, after-school programs; the note to add the school's own breaks;
  - **multifamily:** residents (lobby and garage at all times, package room and amenities in their hours), property staff, maintenance,
    vendors; the note to use the unit number as the reference;
  - **gate:** tenants and employees, deliveries; the note that the gate operator's own safety devices stay its own.

  `GET /templates` serves the catalog. `contract/templates/catalog.json` is generated from it and used by the web app's tests and screenshots.
- **The web app** (`web/`), in PhotonVox's shape:
  - **Sign-in and design:** photon-ui's shell, tokens and components, vendored and checked by `scripts/test-all.sh`. The suite's sign-in:
    straight to PhotonID, no sign-in page, 401 after sign-in and 403 as pages.
  - **Pages:**
    - Customers (integrators);
    - Overview (controllers and what needs attention);
    - Doors (open now; lockdown and its end, each confirmed);
    - People (cardholders, their groups, cards and PINs, which are never shown back);
    - Access (groups, schedules, holidays, publish);
    - Events (in plain words, with door and person);
    - Settings (Team, Audit trail).
  - **The setup wizard:** claim controllers, then wait for their doors; pick a template and its options; say which door is which; import
    people (checked, then imported); publish and watch the controllers take it.

**Verified:**
- **Web:** 134 tests, including the suite's sign-in contract, every page, the office wizard end to end, and every template's notes and options
  read from the API's catalog. Coverage ratchet at 97% lines, 94% statements, 82% branches, 92% functions; PhotonEntry's starting point,
  raised from here.
- **API:** 398 tests on Postgres (every template applied and published to a controller; the template route closed to other organizations).
- **Screenshots:** every page at 1440×900, 820×1180 and 390×844, looked at. No page scrolls sideways. Two things were fixed from them:
  - the stat tiles ran their label into the number;
  - the door step pre-filled optional doors with guesses.

**Not done, or left for later:**
- **Editing in place:** schedules, groups and holidays are shown and published from the web app, but changed through the API. The
  wizard and the API make them today; forms to edit each come with Step 6's people-facing work if the integrators ask for them first.
- **The commissioning record** moved to Step 6, with the installers' licenses.
- **A door or lock icon:** the sidebar uses photon-ui's existing icons. A door icon would need a line in photon-ui's `shell/icons.tsx`,
  another repo, in its own session.
- **Sign-in against a real PhotonID:** not run yet. Registering `entry` at the dev PhotonID (callback and signed-out addresses) is id1's
  job, and the production addresses are Connor's step (GATE P).

## 2026-11-13: Step 4, door events and alarms to PhotonGuard and PhotonConsole

**Built:**
- **Door events in PhotonEntry's words** (`api/app/events.py`): granted (credential or exit button), denied with a reason ("outside its
  schedule", "credential expired"...), forced, held open and cleared, tamper, door opened or closed, door modes. One function serves the API's
  event list, the Guard sender and the Console feed. A topic it does not know becomes `other`, never an error.
- **Door index** (`api/app/doorindex.py`): which door an event belongs to, by the door's token or by an access point of the controller's
  inventory; and the cardholder, from the credential's `pe-u-<id>` user token.
- **PhotonGuard** (`api/app/guard.py`, migration 0002's `guard_link`, `guard_cursor`, `door_alarm`):
  - **Connection:** an organization's admin pastes the ingest token its Guard admin made (sealed; only the last four characters shown).
    Guard's address is PhotonEntry's configuration, never a user's.
  - **What goes:** the worker sends grants and denials as instant events on the door's binding (`entry-door-<door id>`), each asking for a
    clip from 10 s before to 20 s after. A forced or held-open door, and tamper, start an alarm that ends under the same `dedup_key` when the
    door clears. Door modes, opening and closing, and the exit button stay in PhotonEntry.
  - **Exactly once, in order,** per controller. A refusal or an outage stops that organization's sending, shows in Settings, and resumes
    where it stopped. A duplicate from a controller's crash has the same `dedup_key` (the controller's own event token).
  - **Settings, PhotonGuard tab:** connect, replace, test, pause, disconnect, and the binding name of every door for the Guard admin.
- **PhotonConsole** (`api/app/consolefeed.py`, `console_feed_token`):
  - **Feed tokens:** `pent_…`, shown once, stored hashed, revocable, naming the Console tenant.
  - **The feed:** `GET /integrations/console/v1/doors` gives each door's mode, position, alarm, lockdown and its last 24 hours' counts;
    each controller's online state, settings and queue; alerts with severities; totals.
  - **Isolation:** the feed reads through a new `feed` mode of row-level security that sees one organization's tenant, sites, doors,
    controllers and events, never people or credentials.
  - **Refusals:** a bad token gets 401 JSON with `WWW-Authenticate: Bearer`, no redirect.
- **The contract with Guard** (`contract/guard/`): the schema of what PhotonEntry sends (from Guard's ARCHITECTURE §7.6) and samples made
  by the real sender: a grant, a denial, a forced door and its end. Guard pins the same files when it builds its ingest.
- **photon-ui icons** from id1: Doors uses `door`, Access uses `access` (a key).

**Verified:**
- The whole Python suite (API, simulator, end to end) on Postgres and 138 web tests, all passing. (An earlier version of this line and the Step 4 commit message said "449 API tests", a number that was never counted; the suite was 445 tests after the editing work below.)
- 21 CRITICAL modules at 100% branch coverage. The four new ones: events, door index, Guard sender, Console feed.
- **Guard sending:** in order, once; stops and resumes on a refusal or an outage; an alarm is one alarm until it clears; nothing is sent
  when paused or disconnected.
- **The feed:** it shows the right state and alerts, and seen through feed mode one organization cannot see another's doors,
  controllers, credentials or people.
- **Screenshots** of both new Settings tabs at the three sizes, looked at.
- **One gap found by the tests and fixed:** the web app did not guard the Settings tabs by role (the API already refused).

**Not verified:**
- **Against a real PhotonGuard:** its ingest is its M3, not built yet. Until then PhotonEntry is tested against a fake that follows Guard's
  documented contract. Guard's side needs (ARCHITECTURE §14): the ingest itself, an incident source `access` for started and ended door
  alarms, and bindings that may be named `entry-door-<id>`.
- **Against a real PhotonConsole:** a PhotonEntry data source in Console is Console's work (its own session). The feed's shape follows
  PhotonEdge's and PhotonBoard's feeds, which Console already reads.

## 2026-11-13: editing access in the web app (right after Step 4, as Connor asked)

**Built** (`web/src/pages/AccessEdit.tsx`, Access page):
- **Schedules:** add, change and remove. Days of the week, any number of time windows (an end of 00:00 means midnight, sent as `24:00`),
  and off on holidays or not. A schedule still in use is refused with the names of what uses it.
- **Access groups:** add, change and remove, rule by rule: which doors, at all times or under a schedule.
- **Holidays:** add a day, add a year's US business or federal holidays without doubling any (a new endpoint,
  `GET /holidays/{us-business|us-federal}/{year}`), remove one.
- **After any change:** "Saved. The doors keep their current settings until you publish." Only admins (and owners) see the controls.
- **Remove buttons:** a quiet first step in lists; the red is kept for the confirming "Yes" (a page of red buttons was loud in the
  screenshots).

**Verified:** 144 web tests (each editor, its refusals, a viewer's read-only view) and the API suite; screenshots at the three sizes, looked at.

## 2026-11-13: sign-in against the development PhotonID

**Built:** `web/scripts/signin-contract.mjs`, the suite's sign-in contract for PhotonEntry (modeled on PhotonID's own). It signs in for real against
the development PhotonID (id1's registration: a public client, code + PKCE) with a test person made through the API and deleted at the end; the
PhotonEntry API is faked in the browser so each answer can be forced.

**Verified** (all against http://10.10.0.80:8085, 10 checks):
- **Signed out:** a deep link goes straight to PhotonID's form (no sign-in page of ours, no sign-up offered); the request uses PKCE (S256), the
  registered redirect, and asks for PhotonEntry's API project as the audience.
- **Sign-in:** back to exactly the deep link (`/people?q=sam#h`), and every API call carries a bearer token.
- **Silent SSO:** a new tab signs in with one trip to PhotonID and no page shown.
- **Refusals are pages, never loops:** a 401 right after sign-in ("We couldn't sign you in", one trip), a 403 ("No access to PhotonEntry"),
  access pending (a page that asks again by itself and then opens the app), and no organization ("No access to PhotonEntry yet").
- **Sign-out:** ends the PhotonID session, comes back through `/auth/signed-out` to the form (`prompt=login`); a new tab is not signed in silently.
- **Screenshots** of each page at the three sizes, looked at. One fix: the no-organization page lacked the Photon logo the other sign-in
  pages show.

**Not covered here:** PhotonID's own pages (password reset, authenticator app, invitations, sign-up), which PhotonID's contract tests.
Against the real PhotonEntry API: needs the API running with the dev issuer and the "entry" product in the directory catalogue (id1).

## 2026-11-14: Step 5, part 1: intercoms and the Akuvox provisioning server

**Research first** (`sim/reference/AKUVOX-AUTOP.md`, public Akuvox documents only, no contact): the Autop file names and keys for SIP,
Wiegand, the web relay, action URLs and the local relay, with a bench checklist. Two findings changed the plan:
- **No file encryption for now.** The AES scheme of Akuvox's provisioning files (mode, padding, IV) is published nowhere; a wrong guess leaves
  the intercom unable to read its settings. Files are served over HTTPS at an address holding a per-intercom random token. Bench item.
- **The web relay offers only no authentication or Digest**, so its action is a full URL with the intercom's id and key as parameters.

**Built:**
- **Intercoms** (`intercom` table, migration 0003; `app/routes/intercoms.py`): admins at the site add one at a door (model, MAC, SIP account
  typed in until PhotonVox has door stations). PhotonEntry makes its relay key, admin password and provisioning token, sealed. The setup view
  (audited) shows the provisioning address, the admin password and the unlock code. Row-level security: admins at the site only. A door with an
  intercom cannot be removed.
- **The provisioning server** (`GET /provision/v1/<token>/<file>`, `app/akuvox.py`, both CRITICAL): the model's general file (empty) and
  `<MAC>.cfg` for the intercom's own MAC only; the same 404 for every miss; 30 requests a minute per address. The file: SIP account, 34-bit
  Wiegand out with the card check off, every path to the intercom's own relay off, the web relay to entry-link, call and tamper action URLs,
  a random admin password, hourly provisioning.
- **entry-link's intercom endpoint** (`app/local.c`, a third thread): a small HTTP server on the building's network (GET only, a 4 KB head
  read within 3 s, one connection at a time). `/v1/relay` opens the intercom's door through the controller (`tdc:AccessDoor`), `/v1/event`
  records a call or tamper. The intercom proves itself with its key (as parameters or a Basic login) against the SHA-256 in the settings
  (`intercoms`, new in the settings contract). Ten refusals in a minute refuse everything for the rest of it; refusals are recorded once a
  minute. Its events (`PhotonEntry/Intercom/...`) join the controller's in the same numbered queue. No internet needed. The controller
  reports where the endpoint is (`local_endpoint` in health), which the provisioning file uses.
- **Events:** "Opened from the intercom" is a grant (to Guard with a clip, like any grant); intercom tamper is an instant critical event in
  Guard (Akuvox never reports its end); calls and refusals stay in PhotonEntry.
- **Web:** an Intercoms section on Doors for admins: add, change, remove, and the setup values.

**Verified:** 469 Python tests (24 new: the file, the provisioning server, routes, row-level security, events, and end to end with the real C
entry-link against the simulator: unlock by the web relay, refusals, the limit, malformed requests, a controller refusing, and the cloud away)
and 148 web tests; 23 CRITICAL modules at 100% branch coverage. Screenshots at the three sizes, looked at; the action buttons' cell was fixed.

**Not verified:** anything on a real Akuvox (bench checklist, AKUVOX-AUTOP.md §6) or Axis controller (an ACAP app listening on its own port
must also be allowed by the controller's firewall; the alternative is Axis's reverse proxy, Step 7).

**Also:** the sign-in contract's `vite preview` was left running after a run (killing `npx` does not stop vite); it now runs in its own process
group and is stopped with it.

## 2026-11-14: the suite's addresses, app switcher and home-dashboard summary (photonid docs/HOME-BRIEFS.md; not deployed)

**Built:**
- **Slugs from the directory:** the vendored directory client re-copied (photonid d707a4c: organizations carry `slug` and `former_slugs`);
  migration 0004 keeps them on `tenant`; `/me` returns them.
- **Addresses:** every organization page is `/org/<slug>/…`, and again under `/org/<slug>/site/<site-slug>/…` (the pages work on that site,
  and the sidebar's links stay on it). The organization's home and a site's home are the overview. Old addresses (`/doors?site=…`) redirect to
  the same page in the organization used last; a former slug redirects to the current one; a slug this person cannot reach is "We can't open
  that organization", never another customer; `/?organization=<id|slug>&site=<slug>` opens that organization and site. Switching customer
  keeps the page.
- **The app switcher:** photon-ui re-vendored (e6a91c2); `AppShell` gets `apps` while an organization is on screen, loaded from the
  directory's `GET /v1/me/apps` with the organization's and site's slugs. Sign-in also asks for the directory's audience.
- **`GET /v1/summary?organization=<id>`** (`app/summary.py`, CRITICAL): "8 of 8 doors online", per organization and per site; `attention`
  when a door is offline or forced or held open, `down` when none is online, `unknown` with no doors. From what PhotonEntry keeps (controllers'
  last contact, the doors' newest alarm), never asking a controller; in the person's own session (row-level security limits it to their
  sites); cached 30 s per organization and scope; `Cache-Control: private, max-age=30`; CORS for the account app on this route only. Without
  `organization`: one line across every organization the person reaches. **A token another app asked for is accepted on this route only**:
  everywhere else a token whose `client_id`/`azp` is not our web client (`OIDC_WEB_CLIENT_ID`) is a 401.

**Verified:** 476 Python tests (the summary against the directory's own schema, the counts, the cache and its scope, 403 without access,
the one-route rule, CORS; slugs through the sync) and 171 web tests (addresses, redirects, not found, sites, `?organization=`, switching
customers, the switcher's request); 23 CRITICAL modules at 100%. The sign-in contract against the development PhotonID passes again, with the
directory's audience in the request and the old deep link landing at `/org/t1/people?q=sam#h`. Screenshots of an organization home, a site
home and the switcher open at the three sizes, looked at.

**Found on the way:** a second `@app.middleware("http")` made coverage lose the link service's route code after its first `await` (the gate
caught it). The summary's CORS is now plain ASGI, added outside CORSMiddleware so the account app's preflight reaches it first.

## 2026-11-14: Step 5, part 2: PhotonVox door stations and call records (PhotonEntry's side)

**The contract** (`contract/vox/`, `docs/VOX.md`), proposed to v1 for PhotonVox (nothing changed in its repo): PhotonVox owns door stations
(an extension kind, `door_station`) and their call flows; a per-organization integration token with a new scope `vox:entry` (it carries SIP
passwords); `GET /integrations/entry/v1/door-stations` and `/door-calls?station=&at=&window_s=`, each naming the organization; the unlock code
`#` must reach the intercom as RFC 2833 on every call path.

**Built** (`app/vox.py`, CRITICAL; migration 0005):
- **Settings > PhotonVox:** an admin pastes the token; PhotonEntry checks it with PhotonVox before keeping it (sealed). PhotonVox's address is
  configuration (`VOX_API_URL`), never an organization's.
- **An intercom's door station:** chosen from PhotonVox's list (never its password shown); its SIP account is copied into the intercom
  (sealed) at once and every hour, so the intercom's settings never wait on PhotonVox. A station PhotonVox no longer has is reported, and the
  intercom keeps its account.
- **Who answered:** after each "Opened from the intercom", the worker asks PhotonVox for that station's call at that moment (after 20 s, so the
  record has landed; given up after 10 minutes) and the door's events say "Answered by Ann Lee (101)". PhotonVox away only delays the name.
- Every answer is checked against the contract and must name the organization the token was connected for; anything else is a sentence for
  the admin, never data.
- **Web:** the PhotonVox tab, the door-station picker (the typed SIP fields go when a station is chosen), and intercom events in the API's own
  words.

**Verified:** 497 Python tests (the client against the contract's samples and every refusal; on Postgres: connecting, the picker, the hourly
copy and a rotated password, matching including PhotonVox away, row-level security) and 175 web tests; 24 CRITICAL modules at 100%.
Screenshots of the tab and the picker, looked at.

**Not verified:** against PhotonVox itself (its side is not built). **A flaky web test** (schedule editing) failed once under coverage load
and passed on its own twice: a timing margin to widen if it recurs.

## 2026-11-14: Step 6, lockdown (part 1)

**Built:**
- **Lockdown as a record** (`lockdown` table, migration 0006; `app/routes/lockdown.py`, CRITICAL): the whole site or chosen doors, a required
  reason, who started it (operators and up) and from where, one command per door (`tdc:LockDownDoor`: the controller holds it with the cloud
  away), each door's state (confirmed, waiting, refused, not confirmed in time, controller out of service), and its end with a reason, by name.
  One active lockdown per site (a unique index settles two at once). A door whose controller is out of service never stops the rest from
  locking down. Everyone at the site can read it; only operators and up start or end it, in their own name; what started it is never rewritten.
- **Web:** "Lock down" asks which doors and why; the Doors page shows the lockdown with each door's state and "End the lockdown" (a reason
  again); every page shows a banner while a site is locked down, checked every 15 s; "Open now" is hidden on locked-down doors (the controller
  ignores it).

**Researched** (`sim/reference/AXIS-LOCKDOWN.md`, public Axis documents): responders and a wired panic input. Axis documents no lockdown
exemption and no door action in the controller's own rules on the VAPIX track; its own "Exempt from lockdown" is in its VMS. Both are bench
items with probes written down; nothing built on a guess. Also found: controllers ship on firmware tracks, and Axis tells integrators to use
the VAPIX track (switching needs a factory reset): noted for buying the bench kit (ARCHITECTURE §3.6).

**Verified:** the lockdown tests (scope, reason, one at a time and the race, door states, out-of-service controllers, who may, row-level
security) at 100% branch coverage; the end-to-end test locks a simulated door down and releases it; web tests for the dialog, the panel and the
banner; screenshots at the three sizes, looked at (two fixes: "Open now" on locked-down doors, the panel's spacing).

## 2026-11-14: Step 6, the commissioning record (part 2)

**Built** (migration 0007; `app/commissioning.py` and `app/routes/commissioning.py`, both CRITICAL):
- **Licenses** (ARCHITECTURE §7.7): a partner's, recorded once by its own staff (an admin grant from the partner, checked in the database by
  `en_partners_staffed()`) and read by every customer it serves; or an organization's own. State, kind (the kinds §7.7 found per state), holder,
  number, expiry; "expires soon" within 30 days; removing one keeps it, because records name it. Settings > Licenses.
- **Each door's record** (§7.2): state (from the site's address, changeable), AHJ reference or permit, lock type and how it is wired, egress,
  special locking (with a UL-verified reader), fire release tested (when, by whom) or none at the door, request-to-exit and contact checked,
  the installer and their license (required in WV: a current SP-LV; any license must be for the site's state and current on the day). Every
  missing part is listed at once. Signed in the admin's own name ("Partner support" to the customer), audited, never edited; "needs
  commissioning again" with a reason; a door moved to another controller door needs it again by itself.
- **Web:** the Doors page shows each door's state; admins commission from it; anyone opens the record and its history.

**Verified:** 538 Python tests (the rules, including the state from an address; licenses and records on Postgres with row-level security)
and 180 web tests; 27 CRITICAL modules at 100%. Screenshots at the three sizes, looked at (the record's wording fixed).

**Open for Connor:** "in service" does not yet stop anything; whether an uncommissioned door should be held back, and how.

## 2026-11-14: Step 6, visitors' passes (part 3)

**Built** (migration 0008; `app/passes.py`, `app/routes/passes.py`, `app/publishing.py`, all CRITICAL):
- **A pass:** issued by operators and up (`entry.visitors.manage`, new, sensitive; ARCHITECTURE §8 already gave operators visitor passes) at
  their sites, in one access group an admin opened to visitors (a new "Visitors' passes may use this group" on the group editor), for at most 31
  days. It is a cardholder of its own with a 6-digit PIN and a 32-bit card number, both unique in the organization and valid only for the
  window (the controller enforces it). Revoking suspends it at once.
- **The system writes it:** operators cannot write cardholders, credentials or settings (row-level security), so the API checks the person in
  their own session first and `app/passes.py` writes the pass as the system, recorded in the person's name: the only escalation, in one module.
- **Published without anyone's drafts:** every publish now keeps the document it sent (`site_publication`); a pass is published from that
  document with today's passes in it. A site never published refuses passes. Passes over for more than a day are no longer sent, by either path.
- **The visitor's page** (`/pass/<token>`, no sign-in, limited per address): where, when, who invited them, and the PIN while it is good.
  Emailed through Postmark when `POSTMARK_TOKEN` is set (PhotonVox's pattern); otherwise the front desk shares the link.
- **Web:** a Visitors page (make a pass, the PIN and link shown once, revoke), the visitor's page.

**Not built:** the QR code. Adding the QR library (`segno`) was refused by the session's permission check, so it waits for Connor's
go-ahead; whether Akuvox reads a QR as the card number is a bench item anyway (ARCHITECTURE §3.4).

**Verified:** 551 Python tests (who issues, which groups, the window rules, the drafts not published, revoking, the visitor's page, ended passes
dropped, no free number, mail failing, row-level security) and 185 web tests; 30 CRITICAL modules at 100%. Screenshots at the three sizes,
looked at (one fix: a new pass now starts at the current minute, not the next quarter hour).

## 2026-11-14: Step 8 preparation: deployable to the suite's operations standard (not deployed)

**Built** (photon-suite OPERATIONS.md Part 2):
- **Images:** `api/Dockerfile` (the API, the migration job and the worker; non-root; the base PhotonGuard pins on the same host, by digest;
  `BUILD_SHA` as label and setting) and `deploy/web/Dockerfile` (built inside the image; the pinned Caddy; `/config.js` from the environment).
- **`docker-compose.yml`** (project `photonentry`): db, one-shot migrate, api, worker, web; memory ceilings, health checks, the shared logging
  limits, read-only filesystems with every capability dropped, no published ports; the owner's password only in `migrate`.
- **`deploy/caddy/entry.caddy`** for the host's Caddy: the four names, each serving only its part (`link.` only `/link/v1`, with a read timeout
  for the long-poll; `prov.` only `/provision/v1`). The provisioning address now defaults to `prov.entry.photonind.com` (BUILD-GUIDE Step 8).
- **`scripts/deploy.sh <env> [<ref>]`:** a clean tree, a commit on `origin/main` (prod), `git archive` to `releases/<sha>`, build there, migrate,
  start, wait for health, the public `/readyz` must report the commit, tag `deploy/<env>/<date>-<n>`, three releases kept.
- **`/readyz`:** the database, migrations at this release's head, the worker heard from within 2 minutes (a heartbeat row, migration 0010),
  `version` and `started_at`; 503 with the reasons. **JSON logs** (`app/obs.py`) with a request id on every line and every answer.
- **`docs/OPERATIONS.md`** in the standard's eight parts.

**Checked on LXC 800** (not a deploy): compose valid, both images build, the stack runs healthy under the hardening, migrations at head,
`/readyz` ready with its version, `/config.js`, JSON logs; both Caddyfiles validate (Caddy itself); everything removed afterwards.

**A mistake, recorded:** the check stack's `.env` came from the production template, so its worker asked the **production** directory a few
times with made-up credentials (refused, 401; nothing changed). The stack was taken down at once; OPERATIONS.md §3 now says a test stack points at
the development PhotonID.

**Not done:** a hash-locked requirements file (OPERATIONS.md §2.9: needs pip-tools), the move to PhotonGuard's signed-image registry, CI, the
host's watch and backup manifest entries (at the first deploy).

## 2026-11-14: lockdown notices by email (ARCHITECTURE §9.6; approved by Connor)

**Built** (`app/notify.py`, CRITICAL; migration 0011): when a lockdown starts and when it ends, the worker emails (Postmark) everyone active with
an email whose role at that site can start or end a lockdown (operators, admins, owners, partner staff included); viewers, inactive people and
other customers' people never. Never the request that locks the doors, so mail cannot delay a lockdown. Each lockdown records when each notice
went: sent once; a failing mail service is tried again on the next pass (some may get it twice rather than someone not at all); with no mail
configured the notices are marked, not kept; a notice over an hour late is dropped (the banner still shows the lockdown).

**Verified:** 4 tests on Postgres at 100% branch coverage (recipients, once, the end, failure and retry, mail off, a late notice, some doors).

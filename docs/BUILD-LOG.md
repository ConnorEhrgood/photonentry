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
- 449 API tests on Postgres and 138 web tests, all passing.
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

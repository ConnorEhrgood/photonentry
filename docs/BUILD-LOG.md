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

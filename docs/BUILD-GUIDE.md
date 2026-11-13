# PhotonEntry: build guide

You are building PhotonEntry: cloud access control with video intercom for integrators. Every door controller (Axis A1210/A1610) is
autonomous. It takes its access settings from our cloud through `entry-link`, our app running on the controller, and sends its events back.

**Read first:**
- `~/projects/photon-suite/ARCHITECTURE.md` and `OPERATIONS.md`;
- then this repo's [ARCHITECTURE.md](ARCHITECTURE.md) **in full** (revision 2, with Connor's answers);
- then this guide.

Work through the steps in order. Stop at every **GATE** and wait for Connor. Items only Connor can provide are marked **(Connor)**.

## Start here (status as of 2026-11-13)

| Item | State |
|---|---|
| Design | `docs/ARCHITECTURE.md` revision 2; Connor's answers recorded 2026-11-13; both build decisions confirmed (HTTPS long-poll; the link service in Python) |
| Hardware | **None, by decision.** The build runs on the simulator (`sim/`) until the bench kit is bought (GATE H) |
| PhotonID directory | Built, not in production. `entry` is not in its catalog yet. Step 2 uses its contract and fake |
| Repo `~/projects/photonaccess` | Git; remote `origin` = github.com/ConnorEhrgood/photonentry (private, created 2026-11-13). Push to `main` as you go, never force-push |
| Step 1 | Done 2026-11-13 (BUILD-LOG.md) |
| Step 2 | Done 2026-11-13 (BUILD-LOG.md): database, directory, the integrator's API, the link on Postgres |
| Step 3 | Done 2026-11-13 (BUILD-LOG.md): the web app on photon-ui and the shared sign-in; templates for offices, schools, multifamily and gates (Connor: all are likely clients). The commissioning record moved to Step 6 |
| Step 4 | Done 2026-11-13 (BUILD-LOG.md): door events in PhotonEntry's words; to PhotonGuard (sent to Guard's documented ingest; Guard's own ingest is not built yet, so not tried against it); the PhotonConsole feed. Next: editing schedules, groups and holidays in the web app (Connor) |

**Dev ports** (they collide with no other agent): API and link **8133**, simulator **8134**, web **5193**.

---

## 0. Context

**What it is.** Integrators manage people, cards, PINs, schedules, holidays and access groups in PhotonEntry. The cloud **compiles** a site's
document into each controller's own settings: users, credentials, access profiles, schedules and special days, in the shapes of Axis's
access-control services. `entry-link` on each controller does three things:
- pulls the settings and applies the differences through the controller's API on loopback;
- reads the controller's events and sends them with sequence numbers (buffered on flash while offline);
- carries remote commands (unlock, lockdown).

The controller makes every access decision itself.

**Decided (do not re-litigate):**
- **Languages:** Python in the cloud (FastAPI, SQLAlchemy, Alembic, Postgres 16, TimescaleDB for door events); **C** for `entry-link` (ACAP
  Native SDK, libcurl, OpenSSL, the vendored cJSON); React 19 + Vite + `@photon/ui` for the web app.
- **The link:** HTTPS long-polling (`POST /link/v1/sync`). Every request is signed with the controller's Ed25519 key, made on the controller.
  There is no shared secret. The contract is in `contract/link/`.
- **The controller decides.** Nothing of ours is ever in a card or PIN decision. Commands expire (a stale unlock is never carried out).
- **No PhotonEdge is required.** No Axis cloud (O3C).
- **Organizations, sites and people come from the PhotonID directory.** Cardholders are PhotonEntry's own records.
- **Roles:** owner, admin, operator, viewer.
- **Desktop and phone equally first-class.**

**House rules:** suite ARCHITECTURE **§2** in full: git identity, **no AI or tool attribution anywhere**, never print secrets, production is
Connor's, and **American spelling**. For PhotonEntry in particular:
- **Never connect to a real door controller or intercom** without Connor naming it. The simulator is the only controller until GATE H.
- **Do not contact Axis or Akuvox, and do not register anywhere** (axis.com included) until Connor says so.
- Do not modify the sister repos unless a step says so and Connor agrees.

---

## 1. Step 1: the scaffold on a simulator (done 2026-11-13)

Testable with no hardware and no database.

| Part | Where |
|---|---|
| Repo layout, `scripts/test-all.sh`, `docs/DEV.md` | root |
| **The site document** (doors, schedules, holiday calendars, access groups, cardholders and credentials, with optional PhotonID person links) and its validation | `api/app/document.py` |
| **The compiler**: site document + a controller's inventory → that controller's Axis settings (users, credentials, access profiles, schedules in iCalendar, special day groups, door timings) | `api/app/compiler/` |
| **The link service**: hello and claim, settings versions, events with sequence numbers (exactly once, in order), commands with expiry, long-poll; Ed25519 request signatures with a nonce window; a store interface with an in-memory store | `api/app/link/` |
| **The contract**: JSON Schemas and samples for every link message and for the compiled settings | `contract/` |
| **The Axis simulator**: the access-control services as Axis documents them (door control, ID points, access points, credentials, users, access profiles, authentication profiles, schedules, special days, the event logger), with a door model (relay, door contact, REX, forced and held-open) and Axis's access decision; a control API for tests (present a card, open a door, move the clock) | `sim/axis_sim/` |
| **`entry-link`** (C): key generation and signing, hello and claim, the sync loop, applying settings by difference, reading events into a persistent queue, commands; a host build for tests; the ACAP manifest | `acap/entry-link/` |
| **Tests**: unit tests (compiler, iCalendar, signatures, store, link service, simulator decisions); **end to end**: the real C `entry-link` against the simulator and the cloud (claim, settings at the door, a card granted and denied by schedule, events in order, an unlock command, a lockdown, the cloud down for a while with nothing lost) | `api/tests/`, `sim/tests/`, `tests/e2e/` |

## 2. Step 2: database and directory (done 2026-11-13)

1. **Migration `0001`:**
   - the three database roles (`entry_app`, `entry_system`, owner);
   - the directory copy (vendored `photonid/directory/client` and its fake, as PhotonVox does);
   - row-level security on every table, with a test that fails if a table has no policy;
   - **audit tables INSERT/SELECT-only for the app role.**
2. **Tables:**
   - sites' doors, controllers (claimed key, site, inventory), cardholders and credentials (card numbers and PINs Fernet-encrypted);
   - access groups, schedules, holiday calendars;
   - settings versions, the command queue, door events (a TimescaleDB hypertable), audit.
3. **The link store on Postgres**, passing the same tests as the in-memory store. A long-poll wakes on Postgres `LISTEN/NOTIFY`.
4. **API with PhotonID sign-in:** claim a controller by code; doors from the controller's inventory; cardholders and credentials (one at a
   time and bulk CSV); groups, schedules, holidays; publish; remote unlock and lockdown (sensitive capabilities, audited); events.
5. Tenant-isolation tests for every route; `scripts/remote-test.sh` on LXC 800 (Postgres 16 in Docker); 100% branch coverage on the CRITICAL
   modules (`link/signing`, `link/service`, `access`, `rls`, the compiler).

## 3. Step 3: the integrator's web app (done 2026-11-13)

- Site wizard: claim controllers, map doors, commission doors (ARCHITECTURE §7.2).
- Templates; cardholders with bulk import; groups, schedules, holidays; door events; the fleet page.
- Every page reviewed at 1440×900, 820×1180 and 390×844.
- ~~GATE 3~~ answered 2026-11-13: templates for all four kinds of site (offices, schools, multifamily, gates).
- The commissioning record (ARCHITECTURE §7.2) is built with the licenses in Step 6.

## 4. Step 4: events onward (done 2026-11-13)

- Events normalized into `door_event` (ARCHITECTURE §6.3), with the audit export and "who can open this door now".
- Guard: events on `door:<id>` bindings, and access incidents for forced and held-open doors (needs Guard's ingest deployed).
- The PhotonConsole feed.

## 5. Step 5: intercoms (Akuvox) and PhotonVox

- **The provisioning server** for Akuvox auto-provisioning (encrypted per-device files): SIP account, 34-bit Wiegand reader mode, card check
  off, the web relay URL, random passwords.
- **`entry-link`'s local endpoint** for the intercom's web relay (unlock from a call) and its action URLs.
- **The Vox side:** the `door_station` extension and call-record lookup. Coordinate with the PhotonVox build; do not edit its repo without
  Connor.

## 6. Step 6: people-facing features

Visitor passes (QR as a credential number, and PIN), the phone unlock page, lockdown (app, and a controller input set up through
`entry-link`), the commissioning record with installers' licenses for PA, OH and WV.

## 7. Step 7: the real controller

1. Build `entry-link` with Axis's ACAP Native SDK container (the free public image) on LXC 800. Use the app service account from D-Bus
   (AXIS OS 11.8+) instead of the simulator's configured login.
2. **GATE H (Connor):** the bench kit (ARCHITECTURE §3.6, about $2.9k). Then bench tests H1–H11, written up in `docs/SPIKES.md`. Any
   difference between the simulator and the real controller is fixed in the simulator first, then in the code.
3. **GATE S (Connor):** an axis.com account for app signing (Photon's name, Connor the holder). The signing key is kept like PhotonBoard's
   release key.

## 8. Step 8: production and a pilot

**GATE P (Connor):**
- `entry.photonind.com`, `api.entry.photonind.com`, `link.entry.photonind.com` and `prov.entry.photonind.com` on the PhotonGuard VPS;
- `entry` in the PhotonID directory catalog, with its product credentials;
- the go-ahead to deploy.

Then a pilot site in PA, OH or WV with a licensed installer (ARCHITECTURE §7.7). Deploys follow OPERATIONS.md Part 2.

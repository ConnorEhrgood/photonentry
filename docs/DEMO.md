# PhotonEntry's part of the demo organization

The shared spec is `photon-suite/DEMO.md` (4ffd90a): the organization `demo`, its sites, the hard rules and the process. This page is
PhotonEntry's plan against it. **Nothing goes to production until the operator brings Connor's go**, and Entry's demo can only ride with
Entry's first production deploy (GATE P).

## 1. What the demo shows

The directory's fixed IDs (id1, 2026-11-14), the same in development and production:

| | ID |
|---|---|
| Organization Photon Demo, `demo` | `3560c835-5885-442d-bf55-6e250e4b5190` |
| `hq` Headquarters, Pittsburgh PA | `72a17302-e998-4a17-9459-dbc61c4ea410` |
| `warehouse` Distribution Center, Washington PA | `736b1e29-7f84-40a8-b06b-1495902f7d2f` |
| `apartments` Riverside Apartments, Wheeling WV | `e8088684-45b6-45f3-aebc-5e0efc638a3c` |

All three sites are `America/New_York`. `billboards` has no Entry part.

| Site | Template | Controllers (simulated) | Doors | Intercom |
|---|---|---|---|---|
| `hq` | Office | `HQ lobby` A1610, `HQ upstairs` A1610 | Main entrance, Staff entrance (lobby); Executive suite, Server room (upstairs) | `Front intercom` at the main entrance (S532) |
| `warehouse` | Gate + Office | `Yard gate` A1210, `Warehouse office` A1610 | Vehicle gate (open in business hours); Office entrance, Dock entrance | none |
| `apartments` | Multifamily | `Lobby` A1610, `Back of house` A1610 | Lobby entrance, Rear entrance (lobby); Package room, Fitness center (back of house) | `Lobby intercom` at the lobby entrance (E12) |

- **People** (all fictional; names from a fixed list, email addresses on `example.com`, no phone numbers):
  - **hq:** 36 staff, 4 managers, 2 IT and 3 cleaning crew.
  - **warehouse:** 22 employees, 6 delivery drivers and 2 managers.
  - **apartments:** 48 residents (unit numbers as their reference), 3 property staff, 2 maintenance and 4 couriers.
  - Most have a 26-bit card. A few have a PIN as well. One card is expired and one person is suspended, so that denials happen.
- **Templates and the rest of the setup:**
  - The office, gate and multifamily templates, applied through the same code the web app uses, with the doors renamed as above.
  - The federal and business holidays.
  - Two visitors' passes at hq (the link only, never emailed).
  - Every door commissioned: a record signed by a fictional installer, "Demo Integrations LLC".
- **Live, all day, in each site's local time:**
  - **Badge-ins** at the hours a real site has them: arrivals, lunch, the cleaning crew in the evening, residents early and late, the gym 6 to 22.
  - **Exit buttons.**
  - **A few denials a day:** outside the schedule, an expired card, an unknown card.
  - **Door alarms:** a forced door about once a day per site, and a dock door held open now and then.
  - **The vehicle gate** opens on its schedule.
  - **Intercom calls:** a call at hq's front about every hour in business hours, and at the apartments' lobby every 30 to 60 minutes from 8 to 21. Most end in an unlock from the intercom; a few end unanswered.
  - **Actions from the app:** unlocks, lockdowns and door modes go through the real path (cloud → entry-link → controller) and show as events. After an unlock, the simulated door is opened and closed, as a person walking through would.
- **History back-filled:** 30 days of the same pattern. On day one the event list, the dashboards and the intercom pages look lived-in.
- **Phone unlock (decision 25):**
  - The QA account (a viewer; every role can open its own doors) is linked, by the email address id1 gives, to a resident, "Quinn Rivera", so the app-store reviewer can open the lobby, package room and gym from **My doors**.
  - The open goes to a simulated controller and shows as an event.
  - m1 notes this for the store review account.

## 2. How it is simulated (the real protocols, nothing real touched)

**One process tree in one container** (compose project `photonentry-demo`, `deploy/demo/`, labeled, capped at 0.5 CPU and 256 MB). It runs:

- **The Axis simulator** (`sim/axis_sim`, the same one the test suite uses), once per controller, each on its own loopback port, running on the real clock.
- **The real `entry-link`** (the C program from `acap/entry-link`), once per controller.
  - Each one dials the cloud's link (`/link/v1`) like a controller in the field: hello, claim, settings, events, commands.
  - The settings it applies to its simulator are the ones the cloud compiled.
- **The simulated intercoms**, which behave like an Akuvox intercom:
  - **Settings:** they fetch their `<MAC>.cfg` from the provisioning server (`/provision/v1`), hourly.
  - **Calls:** they report the call's start and end with the action URLs that file gives them.
  - **Unlocking:** they unlock through entry-link's web relay with the relay password from the same file.
  - **Not done:** no SIP and no audio. Their MAC addresses are locally administered (`02:50:DE:…`), so they never clash with a real device.
- **The driver** (`sim/demo/`): presents cards and PINs, presses exit buttons, and opens, holds and forces doors on the simulators. It also places the intercom calls, all from a seeded random pattern per site and hour.

**Back-filled history goes through the same path.** Before entry-link first starts, the driver writes 30 days of events into each simulator's own event log, with times in the past. That is a demo-only function of the simulator; the log holds 30,000 rows and the plan stays under 20,000 per controller. entry-link then reads that log from row 0, numbers the events and sends them; the cloud stores them as it stores any controller's.

The intercoms' events in the history (call started, opened from the intercom, call ended) are written into the log of the controller at their door, with the topics entry-link itself records. That is the one place the history takes a shortcut. The cloud stores and shows those events exactly as it does live ones.

**The cloud side** (`api/app/demo/`, run in the API container):

- `seed` writes everything:
  - claims the five controllers by their claim codes, to their sites;
  - applies the templates;
  - creates people, cards, passes, intercoms and commissioning records;
  - links the QA account;
  - publishes.
- `remove` takes it all out. It deletes every row of the demo organization in PhotonEntry and disables its controllers; the directory's organization and sites stay, as they are id1's.

`seed` refuses any organization that is not marked `demo` by the directory.

`scripts/demo.sh` runs both sides in order:

| Command | What it does |
|---|---|
| `scripts/demo.sh seed <host>` | Starts the demo project. Waits for its claim codes. Pipes them into the API's `seed`. Pipes the intercoms' provisioning addresses back to the demo container. Checks that every controller reports its settings applied |
| `scripts/demo.sh reset <host>` | `remove`, then `seed`: a clean demo with a fresh 30-day history |
| `scripts/demo.sh remove <host>` | Stops the demo project, deletes its volumes and runs `remove` |

All three are idempotent.

**The demo flag:**

- PhotonEntry copies the directory's `demo` flag (on the organization document; absent means false) to `tenant.demo`.
- **No email at all for a demo organization** (`app/mail.py`):
  - lockdown notices and visitors' passes are logged, never sent;
  - this holds even with Postmark configured, and for every address, Connor's included.
- **Billing and usage counts:** PhotonEntry has none yet; when they come they skip `tenant.demo`.
- **Platform alerts:** PhotonEntry sends no alert to Connor yet; the future controller-offline alert skips demo organizations.
- **History is trimmed:** a worker job keeps 45 days of events for demo organizations only.

**The simulated mark:**

- `controller.simulated` and `intercom.simulated` are set by `seed` and are never set from a device report.
- Photon staff see a "Simulated" badge on the controller and intercom pages. A prospect signed in as a customer does not.

**Other products (not needed for day one):**

| Product | What it would add | Who decides |
|---|---|---|
| PhotonVox | "Answered by" on intercom calls needs v1's demo door stations (docs/VOX.md). Without them the calls still show, with no answerer | v1 |
| PhotonGuard | Door events on the hq and warehouse camera timelines: Guard's own ingest, when d2 has it | d2 |
| PhotonConsole | The door feed into Console's dashboards | d3 |

Each is a link an admin turns on in Entry's Integrations page.

## 3. Development and staging

- **Tests in the suite:**
  - **The history and driver:** each site's day, the denials and alarms, the intercom calls; the history stays under the log's limit.
  - **seed and remove:** run twice gives the same result; refused without the flag; nothing is left after remove.
  - **No mail for a demo organization,** even with a Postmark token configured.
  - **Simulated badges for staff only.**
  - **An end-to-end run** on the runner: the real entry-link binaries against the simulators with history, a card at a reader, a forced door, and an intercom call that ends in an unlock. Everything arrives as events, in order, exactly once.
- **The dev copy:** seeded with the directory's IDs above (the organization row as the directory's sync writes it, `demo: true`).
- **A full run on LXC 800, as production would run it:**
  - the PhotonEntry stack and the `photonentry-demo` project in Docker;
  - `demo.sh seed`, then a few hours live;
  - `demo.sh reset`, then `demo.sh remove`;
  - removed afterwards, as with the 2026-11-14 stack check.
- **Pulling from id1's dev directory** (where `entry` is not in the catalog yet): id1 will add it when asked. It is not needed to build.

## 4. Production steps (after Connor's go, with or after GATE P)

1. **id1:** the organization and sites already have their fixed IDs. With the GATE P deploy, `entry` is switched on for `demo` and the flag reaches PhotonEntry in the next sync. Check: `tenant.demo` is true for `3560c835…`.
2. **The PhotonEntry deploy itself** (GATE P, `scripts/deploy.sh prod`). It carries migration 0014 (`tenant.demo`, `controller.simulated`, `intercom.simulated`).
3. **Build the demo image:** `scripts/demo.sh build prod` builds the `photonentry-demo` image on the host from the deployed release.
4. **Seed:** `scripts/demo.sh seed prod`. The demo container joins `entry-edge` and dials `photonentry-api-1` directly; there is no public port and it does not go through Caddy. Check:
   - the five controllers show online with their settings applied;
   - the event list fills with 30 days of history;
   - a card, a forced door and an intercom unlock appear within the hour.
5. **Hand over:** tell m1 that My doors works for the QA account.

**Rollback:**

- `scripts/demo.sh remove prod` stops the demo container, deletes its volumes and deletes every PhotonEntry row of the demo organization. Nothing of any other organization is touched, since everything is scoped to its tenant ID.
- The migration is additive (three columns with defaults), so it stays in place.
- If a step goes wrong after step 4, `demo.sh reset prod` brings the demo back to a clean state.

## 5. Monthly cost

| | |
|---|---|
| CPU and memory | One container on the existing host, capped at 0.5 CPU and 256 MB; expected a few percent of one CPU and under 150 MB (measured on LXC 800 before the go, and the number here corrected) |
| Database | About 3,000 events a day, ~3 MB a day, kept 45 days: ~150 MB at most, in the nightly backup (cents of B2) |
| Bandwidth | None outside the host: the container talks to the API on the host's own network |
| B2 / media | None (PhotonEntry stores no media) |
| Total | **Under $1 a month**, on the existing host |

## 6. Decisions

- **Connor's:** only the go for the rollout, which for Entry is the same go as GATE P.
- **Settled without him:**
  - The QA account linked to a resident: m1 notes it, and it opens only simulated doors.
  - Vox, Guard and Console links: v1, d2 and d3 decide.

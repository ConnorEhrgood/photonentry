# PhotonEntry (working name PhotonAccess) — architecture

**Status:** plan, revision 1, 2026-11-13, for Connor's approval. Nothing is built, bought or registered. The hardware facts come from desk
research done on 2026-11-13 (vendor documents, store pages, standards bodies). Anything marked **(verify)** came from one weak source or none,
and is on the bench list in §4. Prices are US list or street prices from that day and change often.

Suite-wide topics (PhotonID and organizations, the rules for working on Photon, conventions, hosting, networks) are in
`~/projects/photon-suite/ARCHITECTURE.md` and `OPERATIONS.md`. Read them first. This document follows the PhotonVox and PhotonGuard designs and
uses their pieces: Vox's phone systems and app, Guard's events, bindings and alarm incidents, and PhotonEdge's supervisor and sealing.

**The product in one sentence:** cloud access control with video intercom for integrators. Doors, readers, credentials, schedules and visitor
passes are managed from one place. Each door event comes with its clip, the intercom rings the customer's phones, and every door keeps working
when the internet is down.

---

## Proposed decisions (for Connor)

None of these is decided. Each has a recommendation. The ones that cost money are marked. Questions only Connor can answer are in §13.

| # | Proposal | Why | § |
|---|---|---|---|
| 1 | **Name it PhotonEntry** (directory key `entry`, `entry.photonind.com`) | Suite §1 says to avoid names that echo the Ubiquiti products Photon installs, and "PhotonAccess" next to UniFi Access is exactly that echo. "Entry" covers doors, gates, intercoms and visitors. A trademark search comes before the name is used anywhere public | — |
| 2 | **Tiered hardware.** R1: **UniFi Access** for doors and **Akuvox** door stations for intercoms. R2: open network controllers, **Axis** recommended (**Akuvox A09x** as the budget option once its listing is checked), and **2N** where a customer needs NDAA. Enterprise **Mercury** only when a customer demands it | UniFi doors are UL 294 listed, cheap and license-free, and Photon already installs UniFi. Akuvox works with any SIP server, which fits PhotonVox, and is open. Axis publishes its whole API without an NDA. Mercury requires an application process | 3 |
| 3 | **No home-built door controller.** The PhotonEdge never drives a lock relay or an OSDP reader that controls a door. Readers and locks are always wired to a listed controller | A Linux box is not UL 294 listed. The codes require listed locking units on the doors where locks matter most (§7) | 3, 7 |
| 4 | **Three layers, each able to run without the one above.** The **controller** decides at the door. The **PhotonEdge** (`entry-agent`) coordinates the site. The **cloud** manages. A grant or deny never waits on the PhotonEdge or the cloud | Site autonomy (suite §3). It is also the only honest answer for doors | 5 |
| 5 | **A PhotonEdge is required at every PhotonEntry site** (Lite profile is enough, on the same UPS as the controllers) | UniFi Access has no cloud API (the API is local, on port 12445), and Akuvox's cloud has no public API. Something on site has to talk to the controllers | 5 |
| 6 | **PhotonEntry is the source of truth.** People, credentials, groups, schedules and holidays are compiled into each controller's own model. A hand edit in the UniFi app or an Akuvox web page is detected, reported and replaced at the next publish | The same rule as Vox decision 5. It is what makes sites supportable and templates possible | 6 |
| 7 | **Cardholders are PhotonEntry's own records**, optionally linked to a PhotonID person (needed only for signing in to unlock from the app). Credentials belong to the cardholder | Issuing 200 badges must not mean 200 PhotonID invitations (the same as Vox decision 15) | 8 |
| 8 | **Roles: owner, admin, operator, viewer**, all but owner site-limitable. Remote unlock, lockdown, issuing credentials and emergency unlock-all are sensitive capabilities | The same role shape as Guard. These are the actions that the partner privacy controls (suite §5) must be able to gate | 8 |
| 9 | **Akuvox stays off SmartPlus (Akuvox's cloud) in R1**: devices are managed locally through the PhotonEdge | Avoids Akuvox's per-door cloud fees and its lock-in. SmartPlus reserves SIP account 1. Devices must also be listed in a distributor's MAC library. What we lose is Akuvox's BLE, NFC and Wallet unlock (R3 brings our own) | 3 |
| 10 | **Intercom calls go through PhotonVox.** The door station registers as a Vox **door station** extension. A call flow outcome rings extensions, ring groups, a mobile number and later the PhotonVox app | One phone system for the customer, so the intercom follows business hours and holidays | 9.2 |
| 11 | **Unlock from a call.** R1: the door station's own DTMF unlock during a call, wired through a **secure relay indoors**, with the audit entry filled in by matching the call record. R2: an **Unlock** button in the PhotonVox app that goes through PhotonEntry | DTMF works today, offline and on any desk phone. The button gives a named, per-person audit entry and needs no code to remember | 9.2 |
| 12 | **The intercom camera is a Guard camera.** Its video in the PhotonVox app comes over Guard's peer-to-peer live view, while the audio travels as a SIP call. SIP video goes to desk video phones on a best-effort basis | Early SIP video through ring groups is unreliable (community reports). Guard's live view already works and is metered | 9.1, 9.2 |
| 13 | **An intercom camera's live view is included with PhotonEntry**, with no Guard plan needed. Recording it needs a Guard plan | An intercom without a picture is not a video intercom. Recording is Guard's business | 9.1 |
| 14 | **Door events go to Guard as events on bindings** (`door:<id>`), with a clip. **Forced and held-open doors open Guard alarm incidents** (a new incident source next to alarm panels) | Guard's ingest, bindings and incidents (Guard §7.6, §16) already do this | 9.1 |
| 15 | **Fire alarm release is hardwired and never in software.** The fire panel's relay cuts lock power at the lock power supply. PhotonEntry only reports the state (through the controller's emergency input) and offers no override | Code and AHJ practice. Software must never sit in the life-safety path | 7 |
| 16 | **A door cannot be put in service until a commissioning record is signed.** The record covers the lock type (fail-safe or fail-secure), free mechanical egress, fire release tested, and the AHJ reference where special locking applies | It puts the integrator's responsibility on record and stops the cloud from being mistaken for the safety system | 7 |
| 17 | **Lockdown in R1**: from the app, from a hardwired panic input at the controller (works offline), and later from a Vox feature code. It locks fail-secure doors and suspends ordinary credentials. It **never affects egress or fire release** | Schools and offices ask for it first. It is also the seed of the suite's emergency-alerts idea (§9.6) | 9.6 |
| 18 | **The audit trail is append-only**: the app's database role cannot update or delete it. Every event keeps source time and ingest time. Default retention is 3 years, set per organization | Investigations, insurers and the customer's own HR. Three years is a common expectation (Connor to confirm) | 7.4 |
| 19 | **No biometrics in R1** (face, fingerprint, palm). Later only with written consent and templates kept on the device, never in the cloud | BIPA (Illinois), Texas and Washington biometric laws carry statutory damages | 7.5 |
| 20 | **Price per door per month, wholesale to partners. Cardholders and visitor passes are unlimited.** An intercom counts as a door. Wallet passes that cost us money are passed through | Easy to quote and in line with the market ($10–25 per door per month retail, §10). Charging per credential punishes customers for adding people | 10 |
| 21 | **Hosting: R1 runs as its own compose project on the PhotonGuard VPS**, beside the PhotonEdge hub, with its own hostnames so it can move. *Moving to its own VPS later costs money* | The cloud carries no door decisions, so sharing a host is acceptable. `photon-infra-a` is full | 11 |
| 22 | **Order: start after D1 and E1 are live.** The intercom piece waits for Vox R1's engine work, and the app video waits for the PhotonVox app (Vox phase A) | PhotonEntry is built from those pieces | 12 |

---

## Terms (what the integrator sees, and what the code calls it)

| User-facing | Internal | Meaning |
|---|---|---|
| **door** | `door` | One opening with a lock: a door, a gate, a turnstile. Belongs to a site |
| **reader** | `reader` | What a person presents a credential to (card, PIN, phone, QR). Entry or exit side |
| **controller** | `controller`, with `kind` `unifi` / `akuvox` / `axis` / later `mercury` | The listed device that decides and drives the lock: a UniFi hub, an Akuvox A09x, an Axis A1210/A1610 |
| **intercom** | `door_station` | A device with a call button, camera and speaker at a door. It is also a Vox extension and a Guard camera |
| **cardholder** | `cardholder` | A person who can open doors. Not necessarily someone who signs in |
| **credential** | `credential`, with `kind` `card` / `pin` / `mobile` / `qr` / `plate` | What a cardholder presents |
| **access group** | `access_group` | Doors plus a schedule. Cardholders are members. Controllers call these "policies" or "access levels" |
| **schedule**, **holiday** | `schedule`, `holiday_calendar` | When access groups apply, and when doors unlock on their own |
| **visitor pass** | `visitor_pass` | A time-boxed QR code or PIN for a guest, issued by a host |
| **lockdown** | `lockdown` | A site or door state that locks doors and suspends ordinary credentials |
| **door event** | `door_event` | Something that happened at a door (§6.3) |
| **PhotonEdge** | `box` | The on-site unit. PhotonEntry's service on it is `entry-agent` |

---

## 1. What PhotonEntry is

**A tool for integrators to deploy and run access control and intercoms quickly**, on hardware they already know, joined up with the rest of
the suite. The integrator is the primary user. The customer's admin, front desk and staff come second.

| Task | Target |
|---|---|
| A new site: doors from a template, controllers found on the network, schedules, holidays | **under 15 minutes** for a typical small office, after the wiring is done |
| 200 cardholders with card numbers | **one paste or one CSV** and a review screen |
| A visitor pass | **one form**; the guest receives a QR code or PIN by email or text |
| Change who can open what, or when | one screen, published in seconds |
| What happened at the back door last night | one page: door events with their clips |
| Is anything wrong (offline controller, door held, tamper, low battery) across all customers | one page |

What the customer gets: card, PIN and phone unlock; schedules and holidays; visitor passes; an intercom that rings their phones with video;
door events with video; lockdown; an audit trail they can export.

---

## 2. Principles carried over from the suite

| Rule | What it means here |
|---|---|
| Tenancy in every table, RLS on | `tenant_id` (the directory organization id) everywhere, and a tenant-isolation test for every route |
| PhotonID says who; products decide what | A read-only copy of the directory (notify, then pull). Cardholders are PhotonEntry's own records (decision 7) |
| Devices talk only outbound | Controllers and intercoms talk only to the PhotonEdge on the site's access-control segment (`10.152/13`, suite §9). Intercoms also reach Vox's SIP addresses. Nothing else, and nothing listens on the internet |
| **Site autonomy** | **Absolute for doors** (decision 4): a site with no uplink still grants, denies, runs schedules, logs, and carries out a hardwired lockdown |
| Two timestamps | Every door event keeps controller time and ingest time. A controller's clock drift is reported |
| Staff act visibly | Partner and Photon staff show as "Partner support". Every remote unlock names its person |
| Never dark over billing | A restricted account keeps every door working and every credential valid. Only changes (new cardholders, new doors) stop |
| Declarative configuration | A site's access configuration is a JSON document. Controllers are generated from it (decision 6) |
| Monitored by PhotonConsole | `GET /integrations/console/v1/doors` (§9.5) |

---

## 3. Hardware: what we researched, and the recommendation

### 3.1 The candidates

| | **UniFi Access** | **Akuvox** | **Axis** (A1210, A1610; A8207, I8016) | **2N** (Axis company) | **Mercury** (HID) MP series | **OSDP readers on the PhotonEdge** |
|---|---|---|---|---|---|---|
| What it is | Hubs plus PoE readers, managed by the Access app on a UniFi OS console on site | Door stations, indoor monitors, and A0x access controllers | Network door controllers; door stations | Premium intercoms and access units | The controller most enterprise platforms run on (Genea, Brivo, Avigilon Alta) | A Linux box driving readers over RS-485 (libosdp, Apache-2.0) |
| API | **Local only:** HTTPS on port 12445, Bearer token with scopes, about 130 operations: users, visitors, NFC import, PIN, QR, policies, schedules, holidays, unlock with actor, lock rules, lockdown/evacuation. The cloud Site Manager API has **no Access endpoints** | **Local:** the unified HTTP API (new_api V1.0, published 2026-11-10) covers users, PIN, cards, QR, plate, schedules, relays, inputs, door, call and event logs. Auth is Digest. **The SmartPlus cloud has no public API** | **VAPIX physical access control**: public, no NDA. Covers doors, users, credentials, schedules, events. ONVIF Profile A/C | HTTP API, **free since OS 2.35 (2022)**. The Gold license is still needed for automation | **Not public**; OEMs only. The new Embedded Application Environment (commercial since March 2026) is an application process: proposal, evaluation, security review | Ours to write |
| Events | Signed webhooks (`Signature: t=…,v1=…`): unlock with method and actor, door position, doorbell, emergency. **No forced or held-open event** on the developer API (verify) | Action URL (HTTP GET) for calls, relays, inputs, valid/invalid card, PIN, QR, break-in. Event log includes "door opened" alarms | VAPIX events, ONVIF events | HTTP API events | Through the OEM | Ours |
| Door hardware, price | Door Hub **$199** (2 REX, DPS, remote release, **emergency input**); Gate Hub $279; Enterprise Access Hub EAH-8 **$999** (8 doors, battery input); readers G3 **$159**, G3 Pro $379; G3 Intercom **$479**; a console is needed (UDM Pro/SE, Cloud Gateway Max, UNVR, Cloud Key+) | A095 **~$1,155** (4 doors, PoE+, OSDP); A094 ~$1,650; A01–A08 $445–595; SR01 secure relay **$125** | A1210 (1 door) ~€440; A1610 (2 doors+) **$800–870** | Access Unit 2.0 ~£560 before VAT | MP1502 price not published (LP1502 listed at $500–1,100) | A USB-to-RS-485 adapter, plus a relay board, lock power and supervised inputs |
| Intercom | G3 Intercom: third-party SIP since firmware 1.7.29. Video over SIP and DTMF not confirmed (verify). Its camera appears in Protect | **Any SIP server**, 2 accounts, H.264 video, DTMF unlock, RTSP and ONVIF. Door stations: E12 $525, S532 $925, E18 $1,345, X912 $1,495 | A8207-VE Mk II $1,570–2,220: SIP, ONVIF | IP Verso 2.0 ~$1,490: any SIP PBX | — | — |
| Credentials | UA-Card (DESFire EV3 with Ubiquiti's own key layer, ~$3 each); reads MIFARE/DESFire. **Third-party cards: unclear** (verify). HID Prox and iCLASS only through Wiegand readers on the Retrofit Hub. PIN, QR, BLE (UniFi's app), **Apple/Google Wallet Touch Pass** (~$5 per user per year, verify), face (G3 Pro), plate (Gate Hub + Protect) | 125 kHz EM, MIFARE, DESFire (keys set with its encoder), HID iCLASS on HID models, PIN, QR (local, or checked by a third-party server), plate (pushed from an LPR camera), face. BLE, NFC and Wallet **only through SmartPlus** | OSDP readers of your choice | PIN, RFID, BLE Mobile Key | OSDP and Wiegand readers of your choice | Your choice |
| **UL 294** | **Yes**: all hubs and readers, Level I, tested by Eurofins MET Labs | **Not found** (verify in UL Product iQ) | A1601 was listed; A1210/A1610 likely (verify) | **Not found** (verify) | Yes (the industry reference) | **No**, and it would never be |
| Offline | Hubs hold credentials and keep working with the console down. **Not the Ultra or Door Hub Mini** | Controllers hold up to 50k users locally | Controllers decide locally | Local | Local | — |
| Licensing | Access is free; Touch Pass is paid; UniFi Professional Integrators program $999 a year (optional) | SmartPlus per door and per app (prices not published in the US); none if run locally | None for the API | Gold for automation | OEM agreement | — |
| Lock-in | UniFi hardware and console; proprietary cards | Low when run locally; high on SmartPlus | Low | Low | Low hardware lock-in, high business barrier | None |
| Risks | API is local and v1 only; reported to disappear if a console moves to Identity Enterprise (verify); forced and held events missing | Security record: 13 CVEs on the E11 (Claroty, 2023, root SSH on by default, CISA ICSA-23-068-01), S539 CVEs published 2025-12; a Chinese vendor (Xiamen); latest NDAA statement found is from 2021; **FCC covered-list status to check** | Price | Price | Months of process before a line of code | Not listable; a safety liability |

### 3.2 Recommendation

**Tier 1 (R1): UniFi Access for doors, Akuvox for intercoms.**
- **Why UniFi Access:**
  - UL 294 listed.
  - Inexpensive: a door is about $360 in hardware (hub plus reader), plus a console the site may already have.
  - No license fee.
  - Hubs keep working on their own.
  - A real local API with signed webhooks.
  - Photon and its partners already install UniFi, so customers recognize it.
- **Why Akuvox:**
  - It is the intercom that fits PhotonVox: any SIP server, H.264, and DTMF unlock.
  - RTSP and ONVIF feed Guard.
  - A local API that covers everything we need, with no cloud fees.
- **What we accept in R1:**
  - UniFi's proprietary cards.
  - Forced and held-open events worked out by `entry-agent` (§6.3).
  - Akuvox kept on a closed VLAN because of its security record (§7.6).

**Tier 2 (R2): open network controllers for sites that are not UniFi.**
- **Axis A1210/A1610 is recommended:** a public API, OSDP readers of any brand, NDAA-compliant, and listed (verify).
- **Akuvox A094/A095 is the budget option**, only if a UL 294 listing is found.
- On these sites PhotonEntry is the whole system, with no other vendor's app.
- **2N** replaces Akuvox as the intercom where a customer cannot accept a Chinese vendor (government, schools, some enterprises).

**Enterprise (later, on demand):**
- **Mercury MP**, through the Embedded Application Environment. Apply only when a real customer requires Mercury (an existing Mercury
  install to take over, or a specification that names it). The application process is long and the terms are under NDA.

**Not recommended:**
- **A controller built on the PhotonEdge** (decision 3). OSDP readers belong on a listed controller. libosdp stays useful for bench tests and
  for reading reader health.
- **ONVIF Profile A/C as our control path.** Adoption is thin; vendors' own APIs are richer.

### 3.3 What we must test on real hardware first (gate before R1's build)

| # | Test | Pass |
|---|---|---|
| H1 | UniFi API: create a cardholder; import a third-party DESFire or MIFARE card by number; PIN; policy, schedule and holiday; unlock with actor; lockdown and evacuation through the API | All by API; nothing needs the UniFi app |
| H2 | UniFi events: the webhook payload and signature; what arrives for denied, forced and held-open doors; derived forced and held events from door-position and relay state | Every event in §6.3 either arrives or is derived reliably |
| H3 | UniFi offline: console off; PhotonEdge off; uplink off. What keeps working, for how long, and what catches up afterwards | Doors keep granting and denying, and events backfill |
| H4 | UniFi console types: does the API survive a firmware upgrade? Does it disappear under Identity Enterprise? | Known and written down |
| H5 | Akuvox door station (S532 or E18) registered to a **staging FusionPBX**: audio, H.264 video to a Grandstream video phone, early video through a ring group, DTMF unlock, call log | Audio and DTMF work through a ring group. Video results written down |
| H6 | Akuvox DTMF unlock through an **SR01 secure relay** indoors, and through a UniFi Door Hub's remote-release input | The door opens; pulling the outdoor unit off its mount does not open the door |
| H7 | Akuvox RTSP into `guard-agent` through the PhotonEdge's MediaMTX; live view in Guard | Live view works, using one camera session |
| H8 | Akuvox HTTP API (new_api) users, cards, PIN, QR, schedules; Action URL events; QR checked by `entry-agent` (remote verification) | All work; latency under 500 ms on the LAN |
| H9 | Akuvox hardening: SSH off, firmware current, Digest auth, no route out except PhotonEdge and Vox SIP; a port scan from the VLAN | Nothing unexpected listening |
| H10 | UniFi G3 Intercom third-party SIP to FusionPBX: audio, video, DTMF | Written down (decides whether UniFi intercoms enter R2) |
| H11 | A bench door: maglock (fail-safe) and strike (fail-secure), a lock power supply with a fire-alarm input, a REX, a door-position switch, a simulated fire relay | Fire release drops the maglock whatever the software says; the emergency input is reported |
| H12 | Listings: UL Product iQ for Akuvox, Axis A1210/A1610 and 2N; the FCC covered list for Akuvox | Written down before Tier 2 is decided |

The bench kit (approximate, **Connor decides; nothing is bought**):
- UniFi Door Hub, G3 Reader and G3 Intercom, ~$840. A console that runs Access, if Photon has none.
- Akuvox S532 (or E12) and an SR01, ~$650–1,050.
- A maglock, a strike, a lock power supply with a fire-alarm input, a REX and a door-position switch, ~$250.
- UA-Cards and a few DESFire and HID cards.

---

## 4. The big picture

```
 CLOUD                                            SITE (access-control VLAN 10.152, on a UPS)
 entry-web ── entry-api ── Postgres + Timescale     PhotonEdge ── entry-agent ──LAN──▶ UniFi console :12445 ─▶ hubs ─▶ readers, locks
   ▲             │   │                                  ▲    │  (cache, events, lockdown,  ──LAN──▶ Akuvox door stations / A09x ─▶ secure relay ─▶ lock
   │             │   └─ directory sync (PhotonID)       │    │   derived alarms, QR checks) ──LAN──▶ Axis controllers (R2)
 people          ├─ Guard: events, alarms, cameras      │    └─ guard-agent + MediaMTX ◀─RTSP── intercom camera
 (web, app)      ├─ Vox: door stations, unlock          │
                 └─ Console feed               outbound HTTPS only                  intercom ──SIP/TLS──▶ PhotonVox engine
                                                                                    fire alarm panel ──hardwired──▶ lock power supply (+ emergency input)
```

| Piece | What it does | Stack |
|---|---|---|
| **entry-api** | Directory copy and authorization; sites, doors, controllers, cardholders, credentials, groups, schedules, visitor passes; the compiler; door events and the audit trail; links to Guard, Vox and Console | FastAPI + Postgres 16 + TimescaleDB (door events) |
| **entry-worker** | Publishing to agents, drift reports, visitor-pass delivery (Postmark; texts later through Vox), the Console feed, retention | same image |
| **entry-web** | The integrator's app and the customer's app: desktop and phone equally first-class (suite §6). It includes the **unlock page** people use on their phones | React 19 + Vite + `@photon/ui` |
| **entry-agent** | On the PhotonEdge: one connector per controller kind; applies the compiled configuration; collects and buffers events; derives forced and held-open alarms; checks QR codes; carries out lockdowns; reports health | Go (the suite's on-site language), a PhotonEdge service with the **safety** priority |

---

## 5. Three layers, and what happens when each one fails

| What is down | Doors | Credentials | Remote unlock, intercom unlock | Events |
|---|---|---|---|---|
| Nothing | Normal | Changes reach the controllers in seconds | Works (1–3 s) | Live in the cloud and in Guard |
| **Cloud** (entry-api) | Normal | Changes wait; the PhotonEdge holds the last published configuration | App unlock **does not work**; DTMF unlock in a call still works (decision 11) | Buffered on the PhotonEdge, sent with their source time later |
| **Uplink** | Normal | Changes wait | App unlock does not work; DTMF unlock works if the Vox engine is reachable, otherwise not | Buffered on the PhotonEdge |
| **PhotonEdge** | Normal: controllers decide alone, schedules included | Changes wait; nothing is lost | App unlock does not work; DTMF unlock works | Buffered in the controllers (UniFi hubs, Akuvox logs); backfilled when the PhotonEdge returns |
| **UniFi console** | Hubs keep working (not the Ultra or Door Hub Mini: we do not sell those for doors that must keep working) | Changes wait | Through UniFi, nothing | Held in the hubs (verify in H3) |
| **Controller power** | Battery backup, then each lock goes to its **wired** state: fail-safe unlocked, fail-secure locked | — | — | Gap |

- **The cache.** Controllers hold every credential for their own doors; that is what they are for. The PhotonEdge holds the **compiled site
  configuration** (sealed with PhotonEdge sealing, `photonedge/docs/SEALING.md`) so it can re-apply it to a controller that was replaced or
  reset without the cloud.
- **Revocation while offline:** a credential revoked while a site is cut off stays valid there until the site reconnects. The app says so
  ("Back door: not yet applied, site offline since 14:02") and lists unapplied changes per site.
- **Lockdown from a hardwired input** (a panic button wired to a controller's input) works with everything above the controller down. A
  lockdown from the app needs the cloud and the PhotonEdge.

---

## 6. Configuration, compilers and events

### 6.1 The site document

Integrators edit outcomes: doors, access groups ("Staff: front and side doors, weekdays 6–20"), unlock schedules ("front door open 8–17 on
business days"), holiday calendars, visitor rules, lockdown scope. This is the JSON document of decision 6. Templates are documents with
blanks, cloned within one partner's customers (as in Vox).

**Holidays** are a **site calendar**. Vox's business hours and holidays ought to read the same calendar, so a customer marks Thanksgiving once.
That is proposed in §14 as a suite topic.

### 6.2 Compiling into controllers

Each connector in `entry-agent` turns the document into its controller's own model:
- **UniFi:** users, groups, policies, schedules, holiday groups, NFC and PIN credentials, visitors.
- **Akuvox:** users with PIN, CardCode, QR, ScheduleRelay, HolidayExemption and LockDownBypass; schedules; relays.
- **Axis:** VAPIX access rules.

Controllers differ. Each connector publishes the **capabilities** it supports, and the app offers only what a door's controller can do.
Examples: anti-passback, two-person rule, first-person-in, and whether QR is read locally.

**Drift:** the agent reads each controller back every 10 minutes and on every event it does not recognize. Anything PhotonEntry did not write
is reported. At the next publish it is replaced, or adopted if an admin chooses that.

### 6.3 One door-event model

```
door_event
  id, tenant_id, site_id, door_id, reader_id, controller_id
  kind        granted | denied | opened | closed | forced | held_open | held_cleared | unlocked | locked
              | intercom_call | intercom_answered | intercom_unlock | tamper | offline | online | lockdown_on | lockdown_off
              | emergency_release | battery_low
  method      card | pin | mobile | qr | plate | remote | schedule | rex | dtmf | emergency
  result      reason for a denial: unknown credential | outside schedule | expired | lockdown | suspended
  cardholder_id, credential_id (nullable), actor (person or system who acted remotely)
  occurred_at (controller time), received_at (ingest time), source_ref (controller event id)
  guard_event_id, vox_call_id (links)
```

- **Forced and held-open doors are worked out by `entry-agent`** wherever the controller does not report them (UniFi's developer API, verify
  in H2):
  - **forced** = the door-position switch opens with no unlock, REX or schedule in the window;
  - **held open** = the door stays open longer than the door's held time after a valid open.
- One rule, the same for every controller. Each door has its own held time and alarm schedule.
- Events are a TimescaleDB hypertable (decision 18), kept for the organization's retention.

---

## 7. Safety, code and the honest limits

### 7.1 What a cloud access product may control

**PhotonEntry is not a life-safety system and never claims to be.** Life safety is the integrator's code-compliant installation, approved by the
authority having jurisdiction (AHJ). It is made of listed hardware, free mechanical egress and a hardwired fire-alarm interface. PhotonEntry
adds **restriction and convenience on top of that**: who may enter, when, and from where. Building it this way is what makes it safe for us to
sell.

| Concern | Rule |
|---|---|
| **Egress** | Free mechanical egress always: a lever or panic hardware on the egress side. Software is never in the egress path. Delayed and controlled egress (IBC 2021 §1010.2.13 and §1010.2.14; NFPA 101 §7.2.1.6.1) only with listed hardware and the AHJ's approval, never configured from the cloud alone |
| **Fail-safe or fail-secure** | A property of the lock and its wiring, recorded on the door, never switchable in software. Typical setup: maglocks fail-safe, as required for sensor release (IBC §1010.2.12: unlock on sensor, on power loss and on a manual button; on fire alarm or sprinkler activation where those exist); strikes on egress doors fail-secure, with free egress from the lever; stairwell doors per re-entry rules (NFPA 101 §7.2.1.5.7) |
| **Fire alarm release** | **Hardwired**: the fire panel's relay cuts power to fail-safe locks at a lock power supply with a fire-alarm input (NFPA 72 chapter 21). The controller's emergency input reports it (UniFi's evacuation cannot be canceled from the app). PhotonEntry shows "Fire release active" and offers no override (decision 15) |
| **UL 294** | It lists **hardware units**, not cloud software (cloud software security is the UL 2900 series). The 8th edition, in force since 2025-05-24, adds requirements for remote access and firmware updates on listed units. IBC special locking (§1010.2.11–.14) requires listed locking units. So we sell listed controllers (Tier 1 and 2) and **never write "UL 294 listed" about PhotonEntry itself**, only "runs on UL 294 listed hardware" for specific models |
| **Lockdown** | Locks fail-secure doors and suspends credentials. It never touches egress or fire release. Schools: several states' Alyssa's Laws require silent panic alarms that reach 911 directly. PhotonEntry's lockdown is not one, and must not be sold as one |
| **Remote unlock and unlock-all** | Security functions, not life safety. Unlock-all ("emergency open") is an owner-only sensitive capability with a confirmation, a reason and an alert to every admin |

### 7.2 Commissioning record (decision 16)

A door becomes **in service** only after the integrator records:
- the lock type and its wired failure state;
- the egress hardware;
- that fire release was tested (date, who) where the door has it;
- the REX and door-position checks;
- the AHJ approval reference where special locking applies.

The record is signed by name, kept in the audit trail, and shown on the door's page. Changing a door's lock type returns it to "needs
commissioning". The partner agreement states that installation and compliance are the partner's (counsel to write it, §13).

### 7.3 Who may do what remotely

Remote unlock, lockdown, issuing credentials and unlock-all are **sensitive capabilities**: `entry.door.unlock`, `entry.lockdown`,
`entry.credential.issue`, `entry.emergency.open`. These are the actions the partner privacy controls (suite §5) will gate. Until those exist,
every remote action by partner or Photon staff is audited and shown to the customer as "Partner support".

### 7.4 The audit trail (decision 18)

- **Door events and configuration changes are kept, append-only.** Configuration changes include who changed which cardholder, credential,
  group, schedule, door or lockdown, with before and after values.
- The app's database role has INSERT and SELECT only on audit tables; a test fails if it has more. Retention is deletion by the system role only.
- Export to CSV and PDF per door, cardholder or period. A report shows who can open a given door right now (the question auditors ask).

### 7.5 Privacy

- Cardholder data is the customer's, and only what is needed is kept: name, email or phone for passes, photo optional.
- Card numbers are stored encrypted (suite Fernet `SECRETS_KEY`). PINs are kept only on controllers and as a hash in the cloud.
- No biometrics in R1 (decision 19). License plates count as personal data: retention applies to them too.

### 7.6 Device security

- Controllers and intercoms go on the access-control VLAN (`10.152`). Their only allowed routes:
  - the PhotonEdge;
  - for intercoms, the Vox engine's SIP and media addresses;
  - NTP through the site gateway.
- That containment is the answer to Akuvox's history.
- Default passwords are replaced by random ones that the cloud manages and the PhotonEdge seals, as Guard does for camera passwords.
- SSH and unused services are turned off. Firmware stays at a version Photon has tested.
- UniFi API tokens are scoped to what PhotonEntry needs.

---

## 8. PhotonID: people, organizations, sites, roles

```
directory organization ── site ─< door ─< reader ; door >── controller
     │                                      └─ door_station (intercom) ── vox extension ; guard camera
     └─ cardholder (optional person_id) ─< credential
             >─< access_group ── doors + schedule ; holiday_calendar (site) ; visitor_pass (host = cardholder)
```

- **Organizations and sites come from the directory**, and doors belong to sites.
- **Cardholders** are PhotonEntry's own records (decision 7). A cardholder with a linked PhotonID person can sign in to unlock from the app.
  Others can **pair their phone with a one-time QR code** an admin shows, as Vox decision 25 does. **Bulk import:** CSV or a paste of name,
  email, card number and group; an HR or identity-provider sync (SCIM) later.
- **Roles** (published to the directory):

| Role | Site-limitable | Can |
|---|---|---|
| `owner` | no | Everything, including unlock-all and retention |
| `admin` | yes | Doors, controllers, cardholders, credentials, groups, schedules, visitor rules, commissioning |
| `operator` | yes | The front desk: see events and live intercom video, unlock remotely, issue visitor passes, start or end a lockdown |
| `viewer` | yes | Events and door state |

- **Fine limits stay in PhotonEntry:** door groups narrow a grant to some doors. A host may issue visitor passes only for their own doors.
- Integrators act through partner grants. A partner technician is typically `admin`.

---

## 9. The suite

### 9.1 PhotonGuard

- **Door events onto cameras:** each door has a Guard **binding** (`door:<id>` → the cameras that see it). `entry-api` posts to Guard's
  `POST /ingest/v1/events` (Guard §7.6):
  - granted, denied, forced, held-open and intercom events;
  - with `occurred_at` set to the controller's time;
  - `record` 10 seconds before to 20 seconds after.
- The door event shows the clip and a link. Guard's timeline shows "Denied: unknown card, back door" on the camera.
- **Forced and held-open doors are alarm incidents** in Guard. This is a new incident source, `access`, next to alarm panels in Guard §16.
  It gets the same lifecycle, verification links and central-station delivery. Held-open opens on the door's alarm schedule and closes when
  the door closes. (A change to Guard's design: §14.)
- **The intercom camera is a Guard camera** (decision 12). `guard-agent` pulls its RTSP stream through the PhotonEdge's MediaMTX (one session,
  the suite rule). UniFi intercoms and reader cameras arrive through Guard's Protect connector.
- Live view is included with PhotonEntry (decision 13: a Guard entitlement `intercom` with live view only). Recording needs a Guard plan.
- **Ingest auth:** a per-organization Guard ingest token with scope `guard:events:write`, created once per organization when both products are
  switched on. The cross-product check compares organization ids.

### 9.2 PhotonVox

- **A door station is a Vox extension of a new kind** (`door_station`). Vox provisions its SIP account 2 (account 1 is left for SmartPlus,
  which we do not use) over the Akuvox API through `entry-agent`, or by hand in R1 if that is simpler.
- Its **call flow** is an ordinary Vox outcome. Example: "rings the front desk ring group; after hours, the manager's mobile; after 30 seconds,
  voicemail off, call ends." It follows the same business hours and holidays.
- **Calls from the door are internal calls.** They use no trunk minutes, except a forward to a mobile number.
- **Unlock from a call** (decision 11):
  - **R1, DTMF.** The person answering presses the door's code. The door station's relay drives an **SR01 secure relay indoors**, or the
    remote-release input of a UniFi Door Hub, so opening the outdoor unit opens nothing. `entry-api` matches the relay event to Vox's call
    record (door station, answering extension, time) and writes "Unlocked by Jane Doe (ext. 104) from a call". The code is random per door
    and changeable; it works only during a call.
  - **R2, a button.** The PhotonVox app shows **Unlock** during a door call. The app asks `entry-api` with the call's id and the user's
    session. `entry-api` checks `entry.door.unlock` for that door and asks the PhotonEdge. An unlock from a phone with no PhotonEntry right
    is refused, even if that person took the call. Desk phones keep DTMF.
- **Video:**
  - **In the PhotonVox app (R2, after Vox phase A):** a door call shows the door's live picture over **Guard's peer-to-peer live view**
    (WebRTC from the PhotonEdge), started as the call rings. The audio stays a normal Vox call. This avoids early SIP video, which is
    unreliable through ring groups, and needs no video in Vox's calling engine.
  - **Desk video phones** (Grandstream GXV, if a customer has them): SIP H.264 video, best effort.
  - **Audio-only phones** hear the door.
  - Being tested in H5.
- **Lockdown by phone (R2):** a Vox feature code (for example `*55` plus a PIN; never a code containing 911) starts a site lockdown from any
  desk phone.
- What Vox needs to add: the `door_station` extension kind; call records PhotonEntry can query by door station and time; the feature code; in
  the app, the door call screen.

### 9.3 PhotonEdge

- **`entry-agent` is a PhotonEdge service** (manifest priority: **safety**, the same level as Guard's recording). It runs on the access-control
  segment, or with a route to it.
- It holds controller credentials **sealed**, and the compiled configuration sealed. Its token audience is PhotonEntry.
- It talks only to its controllers and to `entry-api` (signed requests, as Guard's agent does).
- **Its local jobs:**
  - apply configuration;
  - collect and buffer events (at least 30 days on the PhotonEdge's SSD);
  - derive forced and held-open;
  - check QR visitor passes;
  - carry out lockdowns;
  - re-apply the configuration to a replaced controller.
- None of these is a grant decision for a card or PIN, except **QR codes**, which controllers check through `entry-agent` (remote
  verification). Visitor passes therefore need the PhotonEdge up. Fallback: a visitor PIN, which controllers check alone.
- **Lockdown triggers** with the uplink down: a hardwired input at a controller, or an input the PhotonEdge sees.

### 9.4 PhotonID directory

PhotonEntry is a directory product (`entry`) with the roles in §8, the sensitive capabilities in §7.3, and `home_region` stored from the first
migration. Sync is notify, then pull, as for every product.

### 9.5 PhotonConsole

`GET /integrations/console/v1/doors`, with a per-organization token (the suite pattern), reports:
- door state: locked or unlocked, open or closed, lockdown, fire release;
- controller and intercom health: online, battery, tamper, firmware;
- counts of forced, held-open and denied events.

Console shows doors beside the rest of the building and can raise its own rules, for example "the server-room door opened after hours". Console
**actions on doors** (unlock from an automation) are not offered: a misfiring automation must never open a door. Lockdown from a Console
automation could come later, on request, as a sensitive capability.

### 9.6 Lockdown and the emergency-alerts idea

- **Lockdown, R1** (decision 17), with a scope (site, or door groups) and a reason.
  - **It starts from:** the app or web (operators and up); a hardwired panic input; later a Vox feature code, a Guard alarm (for example a
    panic zone) and a Console automation.
  - **Effects:**
    - fail-secure doors locked, unlock schedules suspended;
    - ordinary credentials refused;
    - a **responders** group kept working (UniFi lockdown; Akuvox LockDownBypass);
    - every admin and operator notified.
  - **It ends** only by a person with the capability, with a reason. Egress and fire release are never affected (§7.1).
- **Emergency alerts (suite idea, not designed):** a lockdown is an **emergency event** that other products can act on:
  - Vox pages every phone and plays a message, or calls a list;
  - Board shows a message on the site's signs;
  - Guard bookmarks every camera at the site and opens an incident;
  - Console records it.
- That deserves its own suite design pass (§14). PhotonEntry only publishes the event in a shape that pass can adopt.

---

## 10. Product shape

### 10.1 For the integrator

- **Site wizard:**
  - pick a template;
  - find controllers (UniFi console by address and token; Akuvox and Axis by discovery on the VLAN);
  - map doors;
  - commission each door (§7.2).
- **Templates:** small office; office with front-desk intercom; multifamily lobby with intercom and package room; gate with keypad and
  plate reader.
- **Bulk import** of cardholders and card numbers (CSV or paste, with a review screen). For UniFi, UniFi's NFC import. **Card migration:**
  HID Prox and iCLASS cards keep working through Wiegand HID readers on a UniFi Retrofit Hub, or OSDP readers on an Axis controller.
- **Schedules and holidays** shared across a site's doors (§6.1). **Visitor passes:** a host creates one; the guest receives a QR code
  (email, text later through Vox) valid for a window and named doors. A PIN is the fallback.
- **The fleet page:** every customer's doors, controllers and intercoms, with status by the suite's status edge.

### 10.2 For the end user

- **Unlock from the phone (R1): a mobile web page**, installable as a home-screen app.
  - Sign in with PhotonID or pair by QR (§8), then a list of the doors the person may open, with **Unlock**.
  - It goes through the cloud and the PhotonEdge to the controller, in 1–3 seconds. It needs both the phone and the site to be online.
- **In the PhotonVox app (R2):** door calls with video and Unlock (§9.2), and the same door list. For a customer without Vox: the decision
  between a separate app and one suite app is §13's question.
- **Guest QR:** the pass in an email or text, shown to the reader.
- **Wallet and tap-to-open (R3):**
  - UniFi Touch Pass through the API on UniFi sites (a cost per user, passed through);
  - Photon's own mobile credentials need readers that accept third-party mobile credentials and Apple's and Google's programs for
    employee badges in Wallet, a separate research item.

### 10.3 Pricing ideas (not decided)

| Benchmark (2026) | Per door per month, retail |
|---|---|
| Verkada | ~$21 (about $249 per door per year), proprietary hardware |
| Brivo | $13.50–50 |
| Kisi | from ~$13.50 |
| Genea (Mercury-hosted, older figure) | $8–10 |

- **Suggested: wholesale per door per month to partners**, about **$5–8**. Partners resell at **$12–20**. An intercom counts as a door.
- Cardholders, visitor passes and events are unlimited.
- **Pass-through** for Wallet passes and SMS.
- Guard recording of the intercom camera is a Guard plan.
- Vox door-station extensions are free inside a Vox phone system.
- Hardware is sold by the partner; Photon may supply kits.
- Billing waits for the suite's billing (suite §13.3).

### 10.4 Releases

| Release | Contents |
|---|---|
| **R1** | UniFi Access doors and Akuvox intercoms. Site wizard, templates, bulk import, cardholders, cards, PIN, access groups, schedules, holidays, visitor QR and PIN, the commissioning record, drift. Forced and held-open derived; Guard events with clips and access alarm incidents; intercom live view. Vox door-station calls with DTMF unlock. The mobile unlock page. Lockdown (app and hardwired). Audit trail and export. The Console feed |
| **R2** | Open controllers: Axis (and Akuvox A09x if listed); 2N intercoms; UniFi intercoms if H10 passes. The PhotonVox app: door calls with video and Unlock. Lockdown from Vox and Guard. Touch Pass on UniFi sites. Texted visitor passes. SCIM or HR import. Metering |
| **R3** | Photon's own mobile credentials (BLE, NFC, Wallet); emergency alerts across the suite; elevators and floors; anti-passback and occupancy; multifamily (resident app, property-management sync); Mercury through its embedded app environment if a customer requires it; billing |

---

## 11. Hosting, names, repo

- **Cloud:** a compose project (`entry-api`, `entry-worker`, `entry-web`, Postgres + TimescaleDB, a one-shot migrate service) on the PhotonGuard
  VPS at first (decision 21), behind its Caddy. It follows OPERATIONS.md Part 2 from the first deploy; its database joins the nightly encrypted
  backup.
- **Names:**
  - hostnames `entry.photonind.com` and `api.entry.photonind.com`;
  - directory key `entry`;
  - database owner `photonentry`, roles `entry_app` and `entry_system`;
  - scope `entry:read`; header `X-PhotonEntry-Signature`.
  - The repo stays `photonaccess` until the name is decided, then is renamed.
- **Repo layout** (as in the sister repos): `api/` (FastAPI, Alembic, tests), `agent/` (Go, `entry-agent`), `web/`, `contract/` (site document,
  compiled configurations, door events, the Guard and Vox payloads, the Console feed), `docs/`.

---

## 12. Order of work

| Step | What | Needs |
|---|---|---|
| **0** | Bench: H1–H12 (§3.3); write down the results in `docs/SPIKES.md` | The bench kit (Connor); a staging FusionPBX (Vox has one: CT 610); a PhotonEdge on the bench |
| **1** | Skeleton: directory copy, roles, sites, doors, cardholders, RLS, tenant tests | D1 (or the directory's fake) |
| **2** | `entry-agent` with the UniFi connector: apply, read back, events, derived alarms, offline buffer | E1, Step 0's UniFi results |
| **3** | Integrator app: wizard, templates, import, groups, schedules, holidays, commissioning, events, fleet | Steps 1–2 |
| **4** | Akuvox connector, Vox door station, DTMF unlock with call matching | Vox R1's engine adapter |
| **5** | Guard: events, clips, access incidents, intercom cameras | Guard's ingest and incidents deployed |
| **6** | Visitor passes, mobile unlock page, lockdown, audit export, Console feed; a pilot site | — |

---

## 13. Questions only Connor can answer

1. **The name:** PhotonEntry, or another? A trademark search first.
2. **The bench kit** (§3.3, roughly $1.7–2.2k plus a console if needed): may we buy it? Which UniFi console can we test with (a spare UDM Pro/SE or
   Cloud Gateway Max)? Does Photon already have any UniFi Access or Akuvox hardware?
3. **First customers:** offices, schools, multifamily, gates? It decides the first templates, and whether lockdown or the resident intercom comes first.
   How many doors in year one?
4. **Licensing and liability:**
   - Which states will Photon and its partners install in? Many require a security, alarm or locksmith license for access control.
   - Does Photon hold one?
   - Who drafts the partner agreement's installation and compliance clauses?
   - Is Photon's liability insurance right for door products?
5. **Akuvox's origin:** acceptable as the default intercom, with 2N for customers who need NDAA? Any government or school customers in view?
6. **The phone app for customers without Vox:** the same PhotonVox app, a separate PhotonEntry app, or one suite app later? (Recommended: the
   mobile web page in R1; decide before R2.)
7. **Intercom live view included without a Guard plan** (decision 13): agreed?
8. **Audit retention** default of 3 years (decision 18): agreed?
9. **Pricing direction** (§10.3): per door, roughly $5–8 wholesale?
10. **Partners' own UniFi gear:** may PhotonEntry take over the configuration of an existing UniFi Access install (decision 6 replaces hand edits),
    or must it also support "monitor only" on existing sites?

---

## 14. Proposed changes to other documents (not applied)

- **Suite ARCHITECTURE §1:** a PhotonEntry row (planned). §5 role table: owner, admin, operator, viewer, all but owner site-limitable. §7: Entry → Guard
  (events, incidents), Entry ↔ Vox (door stations, call records, unlock), Entry → Console (feed). §11: a phase for PhotonEntry R1 after D1 and E1.
- **Suite topics to design:** a shared **site calendar** (business hours and holidays for Vox and Entry); **emergency alerts** across Entry, Vox,
  Board and Guard.
- **PhotonGuard:** an incident source `access` (§16), the `intercom` live-only entitlement, bindings of kind `door`.
- **PhotonVox:** the `door_station` extension kind, call-record lookup for Entry, the lockdown feature code, the app's door-call screen (phase A).
- **PhotonEdge:** `entry-agent` in the manifest with the safety priority; PhotonEdges on the access-control segment `10.152`.
- **photonid:** `entry` in the directory catalog once PhotonEntry publishes its roles.

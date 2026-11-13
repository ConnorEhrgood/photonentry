# PhotonEntry — architecture

**Status:** revision 2, 2026-11-13, with Connor's answers to it recorded the same day ("Answers to revision 2" below); the build has started
(BUILD-GUIDE.md). Nothing is bought or registered. Revision 2 follows Connor's answers to
revision 1 (below). It replaces revision 1's hardware choice (UniFi doors behind a PhotonEdge) with **autonomous Axis controllers fed directly
from the cloud**, and adds licensing in Pennsylvania, Ohio and West Virginia. Hardware facts come from desk research done on 2026-11-13 (vendor
documents, datasheets, store pages, state codes). Anything marked **(verify)** came from one weak source or none, and is on the bench list in
§3.6. Prices are US street prices from that day.

Suite-wide topics (PhotonID and organizations, the rules for working on Photon, conventions, hosting, networks) are in
`~/projects/photon-suite/ARCHITECTURE.md` and `OPERATIONS.md`; read them first. This document follows the PhotonVox and PhotonGuard designs and
uses their pieces: Vox's phone systems and app, Guard's events, bindings and incidents, and PhotonEdge where a site has one.

**The product:** cloud access control with video intercom for integrators. Doors, readers, credentials, schedules and visitor passes are
managed in one place. Every door event comes with its clip. The intercom rings the customer's phones. **Every door controller is autonomous**
and keeps working when everything above it is gone.

**Connor's direction (2026-11-13):**
> "Ideally, each door controller would be entirely autonomous, just taking updated access settings from the cloud."

**What he decided:**
- The name is **PhotonEntry**. The folder stays `photonaccess` for now.
- Operations are in **PA, OH and WV** only, for now.
- **Akuvox** is the default intercom (Chinese vendors are fine for most customers), with Axis and 2N as options.
- He sees the **Axis** controllers as good options. Ideally there is no PhotonEdge requirement per site; the PhotonEdge stays optional, for
  cameras and other on-site work.

**Answers to revision 2 (Connor, 2026-11-13; decided):**
- **Start the build without hardware.** No bench kit is bought for now. The build runs against a simulator of the Axis access-control API made
  from Axis's public documentation (BUILD-GUIDE Step 1); the bench tests in §3.6 wait for hardware.
- **Assume the latest AXIS OS lets a third-party app use the access-control API.** (§3.2's firmware-track question becomes a bench check, not a blocker.)
- **`entry-link` does not affect the UL 294 listing**: Connor's position.
- **Avoid Axis's cloud (O3C).** `entry-link` connects out on its own. O3C is kept only as a documented fallback, not in the plan of record.
- **Akuvox comes from Nelly's Security and SS&Si** (Connor's distributors). Closed.
- **No contact with Axis or Akuvox for now.** The axis.com account for app signing is a later step, for when `entry-link` is ready to sign.

**Build decisions (2026-11-13, made while writing the build guide; Connor confirms or reverses):**
- **The link is HTTPS long-polling, not a WebSocket.** `entry-link` is C on the controller; with libcurl alone (in the ACAP SDK) a held
  `POST /link/v1/sync` carries settings, events and commands both ways within about a second, needs no WebSocket client, and passes every proxy.
- **The link service is part of the Python API** (the same image, its own hostname `link.entry.photonind.com`), not a Go service: a long-poll
  needs nothing a FastAPI worker cannot do, and one language in the cloud keeps one data layer.
- **PINs are stored encrypted (Fernet), not hashed**, because they must reach the controllers in clear (§7.5 corrected).

---

## Decisions

Rows marked **decided** are Connor's. The rest are proposals with a recommendation; those that cost money are marked. The questions only
Connor can answer are in §13.

| # | Decision | Why | § |
|---|---|---|---|
| 1 | **Name: PhotonEntry**: directory key `entry`, `entry.photonind.com`. The folder stays `photonaccess` for now. **Decided** | "PhotonAccess" echoed UniFi Access (suite §1) | — |
| 2 | **Operating area: Pennsylvania, Ohio, West Virginia** for now. **Decided** | Connor's market | 7.7 |
| 3 | **Doors in R1: Axis network door controllers**: the A1210 (1 door) and the A1610 (2 doors; 4 OSDP readers). Second choice: Suprema CoreStation CS-40. UniFi Access in R2 for UniFi sites. Akuvox controllers are **not** used on doors that need a listed system. Mercury only when a customer requires it | It ranks first for Connor's model (§3.1). Its controllers are autonomous (250k credentials on the device; its event log keeps the last 30,000 events) and UL 294 listed. The API is public with no NDA. **Software can run on the controller itself** (§3.2). It costs about $440–530 per door and is stocked by ADI and Anixter | 3 |
| 4 | **The controller is fed by `entry-link`, our ACAP app running on the controller.** It connects out to our cloud, pulls access settings, applies them through the device's own API, pushes events back, and buffers them while offline. **No PhotonEdge is required.** Fallbacks if the app route fails on hardware, in order: a PhotonEdge running the same protocol, or a WireGuard tunnel from the site router. Axis's O3C stays documented only (Connor: avoid it) | This is Connor's model exactly. Genetec ships the same design today ("Axis Powered by Genetec": an ACAP connects A1210/A1610 controllers directly to Genetec's cloud) | 3.2, 5 |
| 5 | **The controller decides; nothing of ours sits in a card or PIN decision.** `entry-link` and the cloud only deliver settings and carry events and remote commands | Site autonomy at its strongest: the doors work with the app, the internet and the cloud all gone | 5 |
| 6 | **PhotonEntry is the source of truth.** Settings are compiled into the controller's model (VAPIX access-control services). Edits made elsewhere are reported and replaced | The same rule as Vox decision 5 | 6 |
| 7 | **Intercoms: Akuvox by default**, with Axis and 2N as options; **bought from Nelly's Security and SS&Si**. **Decided.** Akuvox's cloud, SmartPlus, is not used: Akuvox settings come from our cloud through Akuvox's auto-provisioning | No per-door Akuvox fees and no lock-in. Auto-provisioning is outbound, so it works without a box | 3.4 |
| 8 | **The Akuvox intercom can act as the card reader** for an Axis door, by Wiegand output (34-bit). Its own card check and relay are off, so **the Axis controller decides and drives the lock, with one audit trail**. **Not** on doors that need a listed system (special locking): there, a UL-verified reader (Axis A4120-E or HID Signo 20) is fitted, and the intercom only takes calls | Answers Connor's question (§3.4). The Axis listing names its verified readers, and Akuvox is not one | 3.4 |
| 9 | **Unlock from a call goes through the Axis controller, never through the intercom's relay.** The person answering presses the door's code. The Akuvox "web relay" calls `entry-link` on the controller over the LAN. `entry-link` asks the controller to open the door, and the audit entry names the person from Vox's call record. The PhotonVox app's Unlock button (R2) takes the cloud path | Works with the internet down. An intercom torn off the wall opens nothing. One audit trail | 3.4, 9.2 |
| 10 | **Cardholders are PhotonEntry's own records**, optionally linked to a PhotonID person. Credentials belong to the cardholder | Issuing 200 badges must not mean 200 invitations (as Vox decision 15) | 8 |
| 11 | **Roles: owner, admin, operator, viewer.** All but owner can be limited to sites. Remote unlock, lockdown, issuing credentials and unlocking every door at once are sensitive capabilities | The same shape as Guard. These are what partner privacy controls must be able to gate (suite §5) | 7.3, 8 |
| 12 | **Intercom calls go through PhotonVox.** The door station is a Vox **door station** extension, and its call flow is a Vox outcome | One phone system for the customer, following its hours and holidays | 9.2 |
| 13 | **Intercom video:** at a site with a PhotonEdge, the intercom camera is a Guard camera and the PhotonVox app shows Guard's live view. At a site without one, the video travels over SIP through Vox (bench test H6). Live view is included with PhotonEntry; recording needs a Guard plan | No box required. The best path is used where a PhotonEdge already exists | 9.1, 9.2 |
| 14 | **Door events go to Guard**: as events on bindings with their clips. **Forced and held-open doors open Guard incidents** (a new incident source, `access`) | Guard's ingest and incidents do this already. Axis reports forced and held-open doors itself | 9.1 |
| 15 | **Fire alarm release is hardwired, never in software.** PhotonEntry reports it and offers no override | Codes and AHJ practice | 7 |
| 16 | **A door enters service only after a signed commissioning record**: lock type, egress hardware, fire release tested, REX and door contact checked, the AHJ reference, and **the licensed installer** (WV low-voltage license number; Ohio fire-protection certification for a fire tie-in) | Puts the integrator's responsibility on record (§7.7) | 7.2 |
| 17 | **Lockdown in R1**: from the app (cloud → `entry-link`), and from a hardwired panic input set up on the controller itself, which works offline. Later from a Vox feature code. It never affects egress or fire release | Schools and offices ask for it first. The seed of suite emergency alerts | 9.6 |
| 18 | **Audit trail append-only**: 3 years by default, per organization. The controller's own event log (the last 30,000 events) is the second copy and fills gaps | Investigations and insurers | 7.4 |
| 19 | **No biometrics in R1** | BIPA-style laws; none needed for R1 | 7.5 |
| 20 | **Price per door per month**, wholesale to partners. Cardholders and visitor passes unlimited | Easy to quote; in line with the market | 10.3 |
| 21 | **Hosting: R1 as its own compose project on the PhotonGuard VPS**, with `link.entry.photonind.com` for controllers. *Its own VPS later costs money* | The cloud makes no door decisions | 11 |
| 22 | **Photon holds no installer license and does not dispatch.** Partners hold the licenses their state and city require; Photon collects them at partner onboarding. PhotonEntry raises door alarms to people, never to police or a central station on its own | No PA, OH or WV license covers a cloud provider. Monitoring with dispatch could bring in local alarm ordinances | 7.7 |
| 23 | **Visitor QR codes** carry a time-boxed credential number. The Akuvox reads the code and passes the number by Wiegand like a card, so the controller checks it offline. Visitor PINs are the fallback | Box-free and offline-safe (bench H9) | 10.1 |
| 24 | **Order:** the build starts now, on a simulator (Connor, 2026-11-13); the bench tests run when hardware is bought; the directory (D1) before production. **E1 is no longer a prerequisite** | No PhotonEdge dependency | 12 |

---

## Terms (what the integrator sees, and what the code calls it)

| User-facing | Internal | Meaning |
|---|---|---|
| **door** | `door` | One opening with a lock (a door, gate or turnstile), at a site |
| **reader** | `reader` | Where a credential is presented: an OSDP or Wiegand reader, or an intercom acting as one |
| **controller** | `controller`, `kind` `axis` (later `suprema`, `unifi`) | The listed device that decides and drives the lock |
| **intercom** | `door_station` | Call button, camera and speaker at a door; a Vox extension; optionally a reader; a Guard camera where a PhotonEdge exists |
| (never shown) | `entry-link` | Our app running on each Axis controller: settings in, events out, remote commands |
| **cardholder** | `cardholder` | A person who can open doors; not necessarily someone who signs in |
| **credential** | `credential`, `kind` `card` / `pin` / `qr` / `mobile` | What a cardholder presents (`mobile` = app unlock over the network) |
| **access group** | `access_group` | Doors plus a schedule; cardholders are members (Axis: access profile) |
| **schedule**, **holiday** | `schedule`, `holiday_calendar` | When groups apply and doors unlock on their own |
| **visitor pass** | `visitor_pass` | A time-boxed QR code or PIN for a guest |
| **lockdown** | `lockdown` | Doors locked and ordinary credentials suspended |
| **door event** | `door_event` | Something that happened at a door (§6.3) |

---

## 1. What PhotonEntry is

**A tool for integrators to deploy and run access control and intercoms quickly**, joined up with the rest of the suite. The integrator is the
primary user; the customer's admin, front desk and staff come second.

| Task | Target |
|---|---|
| A new site: controllers claimed, doors from a template, schedules, holidays | **under 15 minutes** for a small office, after the wiring |
| 200 cardholders with card numbers | **one paste or CSV** and a review screen |
| A visitor pass | **one form**; the guest gets a QR code or PIN |
| Change who can open what, or when | one screen; at the doors in seconds |
| What happened at the back door last night | one page of door events with their clips |
| Anything wrong across all customers (controller offline, door held, tamper) | one page |

---

## 2. Principles carried over from the suite

| Rule | What it means here |
|---|---|
| Tenancy in every table, RLS on | `tenant_id` (directory organization id) everywhere, and a tenant-isolation test for every route |
| PhotonID says who; products decide what | A read-only copy of the directory (notify, then pull); cardholders are PhotonEntry's own (decision 10) |
| **Devices talk only outbound** | `entry-link` dials out (WSS 443). Intercoms pull their settings and register to Vox outbound. Nothing at a site listens on the internet |
| Device credentials are their own namespace | Each controller's `entry-link` has its own key made on the device; one revocation per controller |
| **Site autonomy** | **Absolute for doors** (decision 5) |
| Two timestamps | Every door event keeps the controller's time and ingest time; clock drift is reported |
| Staff act visibly | Partner and Photon staff show as "Partner support"; every remote unlock names its person |
| Never dark over billing | A restricted account keeps every door and credential working; only changes stop |
| Declarative configuration | A site's access settings are one JSON document, compiled into controllers (decision 6) |
| Monitored by PhotonConsole | `GET /integrations/console/v1/doors` (§9.5) |

---

## 3. Hardware

### 3.1 Ranking for our model

Connor's model, in order of weight: autonomous controller, fed from our cloud with no box, an open API, UL 294 listed, cost, and available
from PA/OH/WV distribution.

| # | Platform | Autonomous | Cloud-fed without a box | Open API | UL 294 | ~$ per door | PA/OH/WV supply |
|---|---|---|---|---|---|---|---|
| **1** | **Axis A1210 / A1610** | Yes: 250k credentials on the device; event log of 30,000 | **Yes, by an app on the controller** (Genetec ships this); O3C as a fallback (terms not public) | **Public** (VAPIX, ONVIF A/C) | **Yes** (A1210, A1610: indoor, Class 2 power, UL-verified readers) | $400–530 + reader | ADI, Anixter (Wesco is headquartered in Pittsburgh) |
| 2 | Suprema CoreStation CS-40 (UL) | Yes | **Yes, natively**: the device connects to a gateway we would run in our cloud (G-SDK "device to server") | Public (G-SDK, gRPC); license terms not stated | ETL listed to UL 294 | ~$350 + reader | ADI |
| 3 | HID Mercury MP / HID Aero | Yes | Yes: the panel connects to its host (proven by Brivo, Genea, Feenics) | **OEM only**, NDA, terms not public | Yes | $425–850 | Through OEMs |
| 4 | UniFi Access | Yes (hubs; not the Ultra or Door Hub Mini) | **No**: the API is local on the UniFi console; a PhotonEdge or tunnel is needed | Local API, public | Yes (Eurofins MET) | ~$180 + reader, plus a console | Broad |
| 5 | ISONAS RC-04 (Allegion) | Yes | Client mode to a configurable host; a third-party host needs an old SDK (verify) | SDK, terms unclear | Yes | $900–1,200 | ADI |
| 6 | **Akuvox A08 / A095 controllers** | Yes (20k–100k users) | **No**: the user API is inbound only. Remote verification fails closed after 3 s and is not on the A09x | Local, partly public | **Not found** | $290–600 | **No PA/OH/WV distributor found** |
| 7 | 2N Access Unit | Yes | Only through 2N's cloud (My2N) | Local API public | Not found | $580–730 | ADI |
| — | ZKTeco / Armatura | Yes | Yes (PUSH over HTTP) | Semi-public | Claimed by a retailer only | Lowest | ADI; procurement risk |
| — | Brivo, Kisi, Verkada, Alta, Genea, Paxton, Gallagher, Hanwha, PDK | — | Their own cloud only | — | — | — | Closed: not for us |

**Result:** Axis first. It meets every weight, and Connor already leans to it. **Suprema is the alternative if the Axis app route fails.** It is
the only other platform that is open, listed and box-free by design. **UniFi Access** stays for sites already on UniFi (R2, with a PhotonEdge).
**Akuvox controllers** are out for doors that need a listed system. They could serve gates and interior doors where no listing is required,
behind a PhotonEdge, later and only if asked.

### 3.2 Axis: how the controller is fed with no box

| Option | How | Status |
|---|---|---|
| **A. `entry-link`, an ACAP app on the controller (recommended)** | Our app (Native SDK, C; small) runs on the controller. It holds a **long-polled HTTPS link to `link.entry.photonind.com`**, authenticated by a key it generates and keeps on the device (claimed with a code, as a PhotonEdge is). It calls the controller's own access-control API on loopback, with the service account AXIS OS gives apps (AXIS OS 11.8+). It pulls the compiled settings, applies the differences, reports the version applied, streams events with sequence numbers, buffers them in flash (2 GB) while offline, and carries remote unlock and lockdown | **Proven by Genetec** (same controllers, direct to the cloud, no Cloudlink box). The A1210 datasheet lists ACAP (Native SDK); the A1610 manual has Apps. Open: which **firmware track** allows a third-party app to use the access-control API (Axis tells integrators to use the VAPIX track, 10.12, which predates app service accounts; the Secure Entry track 12.x does run apps); the chip architecture; **app signing** (required from AXIS OS 12; AXIS OS 13 removes unsigned apps; the ACAP Signing Service takes any axis.com account). Bench H1–H3 and a question to Axis |
| B. O3C (**documented fallback only**; Connor: avoid Axis's cloud) | The controller's built-in cloud connection is redirected by Axis's dispatcher to an O3C server we run; the cloud then calls the controller's API through it | On the A1210 (A1610 verify). Partner terms are not public |
| C. Site router tunnel | The site's MikroTik joins mgmtnet (WireGuard); the cloud calls the controller's API through it; events also go out over AXIS OS's MQTT client | Works on any Axis, with no Axis permission. But it makes doors' management depend on mgmtnet, which the suite keeps for management only |
| D. A PhotonEdge | `entry-agent` on a PhotonEdge drives the controllers over the LAN | Revision 1's design. Kept for UniFi and Akuvox controllers, and as a last resort |

The cloud speaks **one link protocol** (settings versions, events, commands; JSON schemas in `contract/`) whatever carries it. `entry-link` on
the controller is the first implementation; `entry-agent` on a PhotonEdge (option D) speaks the same protocol for controllers that cannot host it.

### 3.3 Axis models, readers, listing

- **A1210** ($440–585): 1 door, 2 OSDP readers (multidrop) or 1 Wiegand, supervised REX and door contact, 2 aux I/O, 1 relay, PoE.
- **A1610** ($750–870): 2 doors, 4 OSDP or 2 Wiegand readers, 2×2 supervised inputs, 2 relays (2 A), 4 aux I/O, 2 external I/O, PoE or 12/24 V.
  The A1214 is a kit of four A1210-B in a cabinet ($2,035–2,319). The A1710-B (4 doors) and A1810-B (8 doors) are larger; their listings are
  unchecked.
- **OSDP Secure Channel**: SIA "Secure Profile" verified. Wiegand custom formats (bit length, card and facility fields).
- **UL 294** (A1210, A1610): Destructive attack I, Line security I, Endurance IV, Standby power I.
  - **Conditions:** indoors, inside the protected premises; power from a UL 294/603 Class 2 supply or the AXIS T8133 midspan; readers
    **verified by UL: AXIS A4020-E, AXIS A4120-E, HID Signo 20**.
  - The "-B" barebone variants are recognized components that need an enclosure (verify).
- Door forced, held open and tamper are reported by the controller itself (ONVIF door alarm states).
- **Lockdown** is a door-control command (ONVIF/VAPIX lock-down). A hardwired input can be set up on the controller to trigger it (verify in H4).

### 3.4 Akuvox intercoms with Axis (Connor's question: can the intercom be the card reader?)

**Yes, by Wiegand.** The Axis controller decides and drives the lock, and the intercom only reports what it read. One audit trail, at the
controller. OSDP works only on some models and is untested with third-party controllers, so it waits for the bench.

| Model | ~Price | Wiegand out | OSDP as a reader | Reads | PIN to Wiegand | QR to Wiegand |
|---|---|---|---|---|---|---|
| **S532** | $925 | Yes | No (input only) | EM 125 kHz, MIFARE Classic, DESFire EV1–3 | Yes | Not documented |
| **S535** | $1,355 | Yes | **Yes** | same | Yes | Not documented |
| **S539** | $3,645 | Yes | Yes | same | Yes | **Yes** (as the matched card number) |
| **E18** | $1,345 | Yes | No | same; no MIFARE Plus | Yes | Not documented |
| **E16V2** | — | Yes | No | MIFARE, DESFire (no 125 kHz) | Not documented | **Yes** |
| **X912** | $1,495 | Yes | No (input only) | 125 kHz, MIFARE, DESFire | Yes | Not documented |
| **X915V2** | $2,995 | Yes (custom 1–128 bits) | Yes | + HID Prox/iCLASS with the HID module | Yes | **Yes** |
| **R29** | $1,795+ | Yes | Yes | 125 kHz, MIFARE, DESFire | Yes | Not documented |
| **E12V2** | $525 | Yes | No (no RS-485) | MIFARE, DESFire (no 125 kHz) | Not documented | Not documented |
| **R20** | $495 | Yes | No (input only) | 125 kHz, MIFARE, DESFire | Not documented | Not documented |

**Card security:**
- With the encoder (ACR-CID01), Akuvox reads a **credential number of up to 4 bytes stored in a keyed DESFire application or MIFARE sector**,
  not just the card's serial. That is the secure option.
- Outputting it needs **34-bit Wiegand** (26-bit drops a byte), with a matching 34-bit format on the Axis.
- Plain card serial numbers work everywhere but can be cloned. We issue DESFire EV3 cards with our own application key.
- Wiegand itself is unencrypted on the wire; the wire stays inside the building.
- No Akuvox model reads HID Seos.

**Credentials that reach the Axis controller:**
- **cards:** yes;
- **PIN:** yes, on the models marked (sent as keypad digits or as one number; Axis's PIN settings to match on the bench);
- **QR:** as a card number on the models marked;
- **face:** only by sending the matched user's card number, which needs users stored on the intercom (not in R1);
- **Akuvox's own BLE and NFC mobile unlock:** **no**, because they require SmartPlus. Phone unlock is ours, over the network (§10.2).

**The wiring pattern (recommended):**

```
 Akuvox intercom ── Wiegand D0/D1/GND (34-bit; its own card check OFF; its relay NOT wired) ──▶ Axis reader port
 Axis controller ── relay ──▶ lock (via the lock power supply with fire-alarm input) ; REX, door contact ──▶ Axis supervised inputs
 Akuvox ── SIP/TLS ──▶ PhotonVox (calls)      Akuvox ── "web relay" HTTP on the LAN ──▶ entry-link on the Axis ──▶ open the door
```

- **The intercom's relay is never wired to the lock.** An intercom pried off the wall opens nothing.
- **Unlock from a call** (decision 9):
  1. The person answering presses the door's code.
  2. Akuvox's web relay sends an HTTP request on the LAN to `entry-link`.
  3. `entry-link` opens the door through the controller's API, and records the call's door station and time.
  4. The cloud joins that record to Vox's call record to name the person.
- This path needs no internet. It does need `entry-link` running; when it is not, the caller is told to use a credential.
- **Doors that need a listed system** (special locking: maglocks with sensor release, delayed egress) get a **UL-verified reader** on the Axis
  (A4120-E or Signo 20). The intercom beside it only takes calls (decision 8).
- **Akuvox settings without SmartPlus** come from our cloud by **auto-provisioning**:
  - what is set: SIP account, Wiegand mode, card check off, web relay URL, passwords, firmware;
  - files encrypted per device; HTTPS where the model supports it (verify per model);
  - the intercom pulls them on power-up and every hour.
- **Akuvox events** (tamper, calls) go to `entry-link` on the LAN by Akuvox's action URLs. Calls are also known to Vox.

### 3.5 Other findings

- **Akuvox controllers**:
  - No UL 294 listing found for any product.
  - The user API is inbound only. Auto-provisioning documents card and PIN lists only for door phones, not the A0x/A09x.
  - Remote verification fails closed after 3 seconds and is not available on the A094/A095.
  - The A092 is end of life.
  - Security support runs to at least 2027-12-31.
  - **Not for doors that need a listed system.**
- **Akuvox security** (it is our default intercom):
  - **Record:** Claroty's 13 CVEs on the E11 (2023); S539 CVEs published 2025-12; default admin/admin; MD5 Digest on the API; "high security
    mode" only after a factory reset; and between Akuvox devices, a shared default OSDP key if none is set.
  - **Mitigations:**
    - the intercom VLAN reaches only the Axis controller, Vox's SIP and media addresses, our provisioning address and NTP;
    - random passwords set by provisioning;
    - firmware pinned to a version we have tested.
  - **Akuvox's FCC and NDAA standing:** not on the FCC covered list; a Section 889 statement from about 2022; very likely not TAA compliant.
    Government buyers get Axis or 2N intercoms.
- **Akuvox supply:** **Nelly's Security and SS&Si** (Connor's distributors; decided 2026-11-13).
- **Axis supply:** ADI and Anixter (Wesco). The Tri-Ed branch in Cranberry Township, PA is now Anixter. Branches still to confirm.

### 3.6 Bench tests (gate before the build)

| # | Test | Pass |
|---|---|---|
| H1 | **`entry-link` on an A1610**: chip architecture; firmware track; install a test app; get the app service account; reach the access-control API on loopback (users, credentials, access profiles, schedules, door commands, events) | All work on one firmware track, written down with its version |
| H2 | `entry-link` over its HTTPS link to a staging cloud: apply 1,000 cardholders; change one; revoke one; time to the door | Changes at the door within 5 seconds; a revocation is never lost |
| H3 | Offline: uplink cut for 24 hours; doors keep working; events buffered and backfilled in order; the controller rebooted while offline | No lost events; no change in door behavior |
| H4 | Controller events: forced, held open, tamper, REX, a lockdown triggered by a local input (no cloud) | All reported; lockdown works offline |
| H5 | Akuvox (S535) as a reader: 34-bit Wiegand into the A1610; a DESFire card with our key, through the encoder; MIFARE and a 125 kHz card; PIN in both modes; card check off; relay idle | The Axis decides every credential; the intercom never fires its relay |
| H6 | Akuvox calls through a **staging FusionPBX**: audio, DTMF, H.264 to a Grandstream video phone, early video through a ring group, video to a WebRTC softphone | Audio and DTMF through a ring group; video results written down |
| H7 | Unlock from a call: DTMF → Akuvox web relay → `entry-link` → door, with the internet cut | The door opens; the event names the call |
| H8 | Akuvox auto-provisioning from a staging server: HTTPS, encrypted files, every setting in §3.4 | All settings applied with no web-page visit |
| H9 | QR visitor pass: a QR code with a credential number read by the Akuvox, passed by Wiegand, accepted by the Axis within its time window | Works offline (needs a QR-to-card model: S539, X915V2 or E16V2) |
| H10 | Bench door: strike (fail-secure), maglock (fail-safe), lock power supply with fire-alarm input, REX, door contact, simulated fire relay | Fire release drops the maglock whatever the software says |
| H11 | UL Product iQ: A1210 and A1610 listings and their conditions; the -B variants | Written down |

**The bench kit (Connor decides; nothing is bought):**

| Item | ~Price | For |
|---|---|---|
| AXIS A1610 network door controller (02653-001) | $750–870 | H1–H5, H7, H9, H10 |
| AXIS A1210 (02368-001), optional | $440–585 | The one-door model; a second firmware |
| AXIS A4120-E reader (verify price), and/or HID Signo 20 | ~$200–350 each | A UL-verified reader for special-locking doors |
| AXIS T8133 midspan (or a UL 294/603 Class 2 supply) | ~$100 (verify) | Listed power |
| Akuvox **S535** (OSDP as a reader, Wiegand, PIN) | $1,355 | H5–H8 (the S532 at $925 also works but has no OSDP output) |
| Akuvox X915V2 or E16V2, optional, later | — | H9 (QR to card) |
| A strike, a maglock, a lock power supply with a fire-alarm input, a REX sensor, a door contact, end-of-line resistors | ~$300 | H10 |
| DESFire EV3, MIFARE Classic and 125 kHz cards; Akuvox ACR-CID01 encoder (verify price) | ~$100 | H5 |

**About $2.9k** for the A1610, one reader, the midspan, the S535, the bench door and cards. **About $3.6k** with the A1210 and the second reader.
FusionPBX staging exists already (Vox's CT 610).

---

## 4. The big picture

```
 CLOUD                                                 SITE (access-control VLAN 10.152; no Photon box required)
 entry-web ── entry-api ── Postgres + Timescale        Axis controller ── entry-link (our app) ──WSS out──▶ link.entry.photonind.com
   ▲            │  ├─ link service (WSS) ◀─────────────────│   └─ its own API (loopback)  ─▶ relays, readers, REX, door contacts
 people         │  ├─ provisioning (Akuvox) ◀── HTTPS pull ─── Akuvox intercom ── Wiegand ──▶ Axis reader port
 (web, app)     │  ├─ Guard: events, incidents                    └── SIP/TLS ──▶ PhotonVox engine ; web relay (LAN) ──▶ entry-link
                │  ├─ Vox: door stations, call records
                │  └─ Console feed, directory sync      fire alarm panel ──hardwired──▶ lock power supply (+ controller input)
                                                        PhotonEdge (optional): Guard cameras, intercom live view; entry-agent for UniFi
```

| Piece | What it does | Stack |
|---|---|---|
| **entry-api** | Directory copy and authorization; sites, doors, controllers, cardholders, credentials, groups, schedules, passes; the compiler; door events and the audit; links to Guard, Vox, Console | FastAPI + Postgres 16 + TimescaleDB |
| **link service** | Controllers' long-polled HTTPS link: claim, settings versions, event intake with sequence numbers, commands; refuses unknown or revoked keys | Part of the Python API (build decision, 2026-11-13) |
| **entry-worker** | Compiling and publishing, drift reports, visitor passes (Postmark), Akuvox provisioning files, the Console feed, retention | Python, same image as the API |
| **entry-web** | The integrator's and customer's app, including the phone unlock page; desktop and phone equally first-class | React 19 + Vite + `@photon/ui` |
| **entry-link** (on the controller) | Applies settings, buffers and sends events, carries commands, receives the intercom's web relay | ACAP Native SDK (C), signed |
| **entry-agent** (optional) | The same protocol on a PhotonEdge, for controllers that cannot host `entry-link` (UniFi, R2) | Go, PhotonEdge service |

---

## 5. What keeps working when something fails

| What is down | Doors (cards, PINs, schedules, QR passes) | Changes | Remote and app unlock | Unlock from an intercom call | Events |
|---|---|---|---|---|---|
| Nothing | Normal | At the door in seconds | 1–3 s | Works | Live |
| **Cloud** | **Normal** | Wait; nothing lost | No | **Works** (LAN path) | Buffered by `entry-link`, sent later with source time |
| **Uplink** | **Normal** | Wait | No | **Works** if the intercom still reaches Vox; otherwise no call | Buffered |
| **`entry-link`** (crashed, updating) | **Normal**: the controller decides alone | Wait | No | No: use a credential | Kept in the controller's event log (the last 30,000); backfilled when it returns |
| **Controller power** | Battery or listed supply backup, then each lock goes to its **wired** state | — | — | — | Gap |

- **Revocation offline:** a credential revoked while a site is cut off stays valid there until it reconnects. The app shows unapplied changes
  per door ("Back door: not applied, offline since 14:02").
- **A replaced controller** is claimed, and the cloud sends it the whole configuration; nothing on site is needed.
- `entry-link` updates are signed releases, rolled out by channel (lab → early → stable), with the previous version kept (PhotonEdge's release
  model, on the controller). The doors never depend on it.

---

## 6. Configuration, compiling, events

### 6.1 The site document

Integrators edit outcomes:
- doors;
- access groups ("Staff: front and side doors, weekdays 6–20");
- unlock schedules;
- holiday calendars;
- visitor rules;
- lockdown scope and responders.

That is one JSON document (decision 6). Templates are documents with blanks, cloned within one partner's customers. **Holidays** are a site
calendar, which Vox's business hours should read too (§14).

### 6.2 Compiling

- The compiler turns the document into **per-controller settings**: users, credentials, access profiles, schedules, holidays and door modes, in
  the shape of the controller's access-control services.
- Settings are versioned. `entry-link` applies the difference from the version it holds and reports the version applied.
- **Capabilities** per controller kind decide what the app offers.
- **Drift:** `entry-link` reads the controller back hourly and after any change it did not make. The difference is reported and replaced at
  the next publish.

### 6.3 One door-event model

```
door_event
  id, tenant_id, site_id, door_id, reader_id, controller_id
  kind     granted | denied | opened | closed | forced | held_open | held_cleared | unlocked | locked | intercom_call | intercom_unlock
           | tamper | offline | online | lockdown_on | lockdown_off | emergency_release | power_fail
  method   card | pin | qr | mobile | remote | schedule | rex | intercom
  reason   for a denial: unknown | outside schedule | expired | lockdown | suspended
  cardholder_id, credential_id, actor (who acted remotely or answered the call)
  occurred_at (controller time), received_at, source_ref (controller event id), seq (per controller)
  guard_event_id, vox_call_id
```

- Sequence numbers per controller make backfill exact.
- Axis reports forced, held open and tamper itself. UniFi (R2) needs them worked out by `entry-agent`, as in revision 1.

---

## 7. Safety, code, licensing

### 7.1 What a cloud access product may control

**PhotonEntry is not a life-safety system and never claims to be.** Life safety is the partner's code-compliant installation, approved by the
authority having jurisdiction (AHJ). It is built from listed hardware, free mechanical egress and a hardwired fire-alarm interface.
PhotonEntry adds restriction and convenience on top.

| Concern | Rule |
|---|---|
| **Egress** | Free mechanical egress always. Delayed and controlled egress (IBC 2021 §1010.2.13–14; NFPA 101 §7.2.1.6.1) only with listed hardware and the AHJ's approval |
| **Fail-safe or fail-secure** | Set by the lock and its wiring, recorded on the door, never switchable in software. Maglocks are fail-safe (sensor release, IBC §1010.2.12: unlock on sensor, on power loss, by a manual button, and on fire alarm or sprinkler where those exist). Strikes on egress doors are fail-secure, with free egress by the lever |
| **Fire alarm release** | **Hardwired**: the fire panel's relay cuts lock power at a lock power supply with a fire-alarm input (NFPA 72 ch. 21). A controller input reports it. No override in PhotonEntry |
| **UL 294** | It lists hardware, not cloud software. The 8th edition (in force since 2025-05-24) adds remote-access and firmware-update requirements for listed units. Special locking requires listed locking units. We say "runs on UL 294 listed Axis controllers", never that PhotonEntry is listed. **`entry-link` runs inside a listed unit**: Axis is asked whether a third-party app affects the listing (Genetec's product suggests not; verify) |
| **Lockdown** | Locks fail-secure doors and suspends credentials; never touches egress or fire release. It is not an Alyssa's Law panic alarm |
| **Remote unlock, unlock every door** | Security functions, not life safety. Unlocking every door at once is owner-only, with confirmation, a reason and an alert to every admin |

### 7.2 Commissioning record (decision 16)

A door is **in service** only after the installer records:
- lock type and wired failure state;
- egress hardware;
- fire release tested (date, who), where present;
- REX and door contact checked;
- the reader is UL-verified, where special locking applies;
- the AHJ reference or permit number;
- **the installer and their license** for the state (§7.7).

It is signed by name, kept in the audit trail, and shown on the door. A change of lock type returns the door to "needs commissioning".

### 7.3 Who may act remotely

`entry.door.unlock`, `entry.lockdown`, `entry.credential.issue` and `entry.emergency.open` are sensitive capabilities, gated by the partner
privacy controls when they exist (suite §5). Until then, every remote action by partner or Photon staff is audited and shown as "Partner support".

### 7.4 The audit trail (decision 18)

- **Kept, append-only:** door events and every configuration change (who changed which cardholder, credential, group, schedule, door or
  lockdown, before and after).
- The app's database role has INSERT and SELECT only on audit tables; a test fails if it has more.
- **Exports:** CSV or PDF per door, cardholder or period, and a report of "who can open this door right now".

### 7.5 Privacy

- Cardholder data is the customer's, and minimal.
- Card numbers are encrypted (Fernet `SECRETS_KEY`).
- PINs are encrypted in the cloud (Fernet), because the controllers need them in clear; they are never shown again after entry.
- No biometrics in R1.

### 7.6 Device security

- **Network:** controllers and intercoms on the access-control VLAN (`10.152`). Allowed routes:
  - `entry-link`: out to `link.entry.photonind.com`;
  - intercoms: to the Axis controller, Vox, our provisioning address and NTP.
- **Passwords:** random, set by our cloud: the Axis root account through `entry-link` at claim time, Akuvox by provisioning.
- **Firmware:** pinned to versions we have tested.
- **`entry-link`:**
  - signed;
  - its device key never leaves the controller;
  - each controller can only fetch its own settings;
  - a controller can be disabled in the cloud with one click.

### 7.7 Licensing in Pennsylvania, Ohio and West Virginia (research 2026-11-13; not legal advice: confirm with counsel and the boards)

| | **Pennsylvania** | **Ohio** | **West Virginia** |
|---|---|---|---|
| State license to install access control | **None statewide.** Local only: **Philadelphia** requires a licensed electrical contractor for all electrical work, low voltage included, with permits; **Pittsburgh** an Electrical Trade License and a permit, with a low-voltage scope. HICPA registration for residential work of $5,000 or more a year | **None under 50 V**: ORC 4740.13(D) exempts alarm, cabling and communication work under 50 V from OCILB licensing (access control fits by reading: confirm with OCILB). Line-voltage commercial work (the lock power supply's feed) needs an **OCILB electrical contractor** | **Yes**: each technician needs a **Specialty Low-Voltage Electrician (SP-LV)** license from the State Fire Marshal (W.Va. Code §29-3B-3), and the firm needs a **WV Contractor Licensing Board** license above the threshold ($5,000 residential / $25,000 commercial per the code site; verify) |
| Fire-alarm tie-in | Philadelphia: licensed electrical contractor and a full permit; testing by a licensed Fire Alarm Systems Inspector | **State Fire Marshal Fire Protection Certification** (individual **and** company, "Fire Alarm and Detection Equipment") for anyone installing or servicing for profit (ORC 3737.65; OAC 1301:7-7-09). Columbus also requires registration | SP-LV covers the wiring; no separate state fire-alarm license found (verify with the Fire Marshal) |
| Security, guard or alarm-business license | None | **Not applicable**: ORC 4749 covers guards, patrols, dogs and armored cars, not alarms (some sites claim otherwise; the current text does not) | Not applicable (§30-18 covers detectives and guards) |
| Building code (egress locks) | UCC: 2021 IBC since 2026-01-01 | 2024 Ohio Building Code (2021 IBC) | Fire code NFPA 101 (2021) prevails; building 2018 IBC (rule under revision) |
| Local | Pittsburgh alarm **user** permits | Cleveland alarm **user** registration; some cities license alarm businesses (e.g. Canton) | Charleston: license or registration and a permit for contracting |

- **Photon as a cloud provider:** no state license found in any of the three. That is why Photon does not dispatch (decision 22): monitoring
  with police dispatch could bring in local alarm ordinances.
- **Partners:**
  - WV: SP-LV technicians and a WVCLB license.
  - OH: OCILB for line voltage; State Fire Marshal certification for fire tie-ins; city registrations.
  - PA: Philadelphia and Pittsburgh licenses and permits; HICPA for residential.
  - Everywhere: permits and AHJ approval for electrically locked egress doors.
- **What the product does about it:**
  - Partner onboarding records licenses per state (number, holder, expiry), with reminders before expiry.
  - The commissioning record names the licensed installer.
  - The partner agreement puts installation, permits and compliance on the partner (counsel drafts it).

---

## 8. PhotonID: people, organizations, sites, roles

```
directory organization ── site ─< door ─< reader ; door >── controller (entry-link)
     │                                     └─ door_station (intercom) ── Vox extension ; Guard camera (where a PhotonEdge exists)
     └─ cardholder (optional person_id) ─< credential >─< access_group (doors + schedule) ; holiday_calendar ; visitor_pass
```

- Organizations and sites come from the directory, and doors belong to sites.
- **Cardholders** are PhotonEntry's own (decision 10). A linked PhotonID person can sign in to unlock from the app; others **pair a phone by a
  one-time QR code** (as Vox decision 25).
- **Bulk import:** CSV or paste; HR or identity-provider sync (SCIM) later.

| Role | Limitable to sites | Can |
|---|---|---|
| `owner` | no | Everything, including unlocking every door and retention |
| `admin` | yes | Doors, controllers, cardholders, credentials, groups, schedules, visitor rules, commissioning |
| `operator` | yes | Front desk: events, live intercom video, remote unlock, visitor passes, start or end a lockdown |
| `viewer` | yes | Events and door state |

Fine limits stay in PhotonEntry (door groups; hosts issue passes only for their doors). Integrators act through partner grants.

---

## 9. The suite

### 9.1 PhotonGuard

- **Door events onto cameras:**
  - each door has a Guard binding (`door:<id>`);
  - `entry-api` posts granted, denied, forced, held-open and intercom events to Guard's `POST /ingest/v1/events`, with the controller's time;
  - the clip runs from 10 s before to 20 s after;
  - the door event shows the clip.
- **Forced and held-open doors are Guard incidents** (source `access`, beside alarm panels): the same lifecycle, verification links and
  central-station delivery.
- **The intercom camera** is a Guard camera at sites with a PhotonEdge. `guard-agent` reads it through MediaMTX. Live view is included with
  PhotonEntry, and recording needs a Guard plan (decision 13).
- **Clips need the cameras to be in Guard**: a PhotonEdge, or Photon cameras. Without either, door events stand alone.

### 9.2 PhotonVox

- **A door station is a Vox extension of a new kind** (`door_station`). Its SIP account comes from Vox; Akuvox provisioning (§3.4) puts it on
  the intercom.
- **Its call flow is a Vox outcome.** Example: "front desk ring group; after hours the manager's mobile; then the call ends." It follows the
  site calendar.
- **Unlock from a call:**
  - **Desk phones, R1:** the code, through Akuvox's web relay to `entry-link` (decision 9). The audit entry names the answering extension's
    user from Vox's call record.
  - **The PhotonVox app, R2:** an **Unlock** button. It goes from the app to `entry-api` (the user's session and the call id), which checks
    `entry.door.unlock`, then to `entry-link`.
- **Video:**
  - **Sites with a PhotonEdge:** Guard's peer-to-peer live view in the app as the call rings.
  - **Sites without one:** H.264 over SIP through Vox to the app and to video desk phones, if H6 shows it works through ring groups.
  - Otherwise audio only, with a snapshot (the intercom can post one to `entry-link`; verify).
- **What Vox adds:** the `door_station` kind; call records PhotonEntry can query by door station and time; a lockdown feature code (for
  example `*55` plus a PIN, never a code containing 911); the app's door-call screen.

### 9.3 PhotonEdge (optional)

Not needed for doors. Where a site has one (for Guard), it adds intercom live view and Guard clips. It runs `entry-agent` for controllers that
cannot host `entry-link`: UniFi Access in R2, and Akuvox controllers if ever used.

### 9.4 PhotonID directory

PhotonEntry is a directory product (`entry`), with the roles in §8 and the sensitive capabilities in §7.3. It stores `home_region` from its
first migration and syncs by notify, then pull.

### 9.5 PhotonConsole

`GET /integrations/console/v1/doors`, with a per-organization token, reports:
- door state (locked or unlocked, open or closed, lockdown, fire release);
- controller and intercom health (online, tamper, firmware, `entry-link` version);
- counts of forced, held-open and denied events.

Console offers **no door actions**: an automation must never open a door.

### 9.6 Lockdown and emergency alerts

- **Lockdown (decision 17)** has a scope (the site or door groups) and a reason.
  - **It starts from:**
    - the app (operators and up);
    - a **hardwired panic input** set up on the controller, which works with everything above it down;
    - later, a Vox feature code, a Guard alarm and a Console automation.
  - **It does:**
    - locks fail-secure doors and suspends unlock schedules;
    - refuses ordinary credentials, while the **responders** group keeps working;
    - notifies every admin and operator.
  - **It ends** only by a person with the capability, with a reason. Egress and fire release are never affected.
- **Emergency alerts** (suite idea, not designed): a lockdown publishes an emergency event that Vox (paging, call lists), Board (messages on
  signs), Guard (incident, bookmarks) and Console can act on. It deserves a suite design pass (§14).

---

## 10. Product shape

### 10.1 For the integrator

- **Site wizard:**
  1. Pick a template.
  2. **Claim controllers.** Install `entry-link` (factory-loaded on Photon-supplied units, or uploaded from the wizard on the LAN) and enter
     its claim code.
  3. Map doors and readers.
  4. Add intercoms (by MAC: the intercom finds our provisioning server by DHCP option or Akuvox's discovery).
  5. Commission each door (§7.2).
- **Templates:** small office; office with an intercom at the front desk; multifamily lobby with intercom and package room; gate with
  keypad.
- **Bulk import** of cardholders and card numbers.
  - **Card migration:** existing HID Prox and iCLASS cards keep working through HID OSDP readers on the Axis, or through an X915V2 with the
    HID module.
  - **New cards:** DESFire EV3 with Photon's (or the partner's) application key.
- **Schedules and holidays** are shared across a site.
- **Visitor passes:**
  - a QR code carrying a time-boxed credential number, read by a QR-capable intercom and checked by the controller offline (decision 23);
  - or a visitor PIN;
  - sent by email (by text later, through Vox).
- **The fleet page:** every customer's doors, controllers and intercoms, with the status edge.

### 10.2 For the end user

- **Phone unlock (R1):** a mobile web page that can be installed on the home screen.
  - Sign in with PhotonID or pair by QR, then **Unlock** on the doors you may open.
  - The path is cloud → `entry-link`, 1–3 s. The phone and the site must both be online.
- **The PhotonVox app (R2):** door calls with video and Unlock, and the same door list.
- **Guest:** the pass in an email or text, shown to the intercom.
- **Tap or Wallet credentials (R3):** need readers that accept third-party mobile credentials. Candidates: HID Signo with HID's mobile
  platform (paid per credential), or Apple's and Google's employee-badge programs. A research item.

### 10.3 Pricing ideas (not decided)

| Benchmark (2026) | Per door per month, retail |
|---|---|
| Verkada | ~$21 |
| Brivo | $13.50–50 |
| Kisi | from ~$13.50 |
| Genea (older figure) | $8–10 |

- **Suggested:** **$5–8 per door per month wholesale**, resold by partners at $12–20.
  - An intercom counts as a door.
  - Unlimited cardholders, visitor passes and events.
  - Text messages and any third-party mobile credentials passed through at cost.
  - Recording the intercom's camera is a Guard plan.
- **Hardware:** sold by partners. Photon may supply Axis units with `entry-link` preloaded.

### 10.4 Releases

| Release | Contents |
|---|---|
| **R1** | **Axis controllers with `entry-link` (no box)**; Akuvox intercoms as readers and door stations with provisioning, calls through Vox and unlock from a call; site wizard, templates, bulk import; cardholders, cards, PIN, access groups, schedules, holidays; visitor QR and PIN; commissioning with licenses; Guard events, clips and access incidents; phone unlock page; lockdown (app and hardwired); audit and export; Console feed |
| **R2** | The PhotonVox app: door calls with video and Unlock. UniFi Access sites through `entry-agent` on a PhotonEdge. Suprema if needed. 2N and Axis intercoms. Lockdown from Vox and Guard. Texted passes. SCIM. Metering |
| **R3** | Mobile tap and Wallet credentials; emergency alerts across the suite; elevators; anti-passback and occupancy; multifamily (resident app, property-management sync); Mercury if a customer requires it; billing |

---

## 11. Hosting, names, repo

- **Cloud:**
  - one compose project (`entry-api` with the link service, `entry-worker`, `entry-web`, Postgres + TimescaleDB, one-shot migrate);
  - on the PhotonGuard VPS at first, behind its Caddy (decision 21);
  - OPERATIONS.md Part 2 from the first deploy, and its database joins the nightly encrypted backup.
  - Each controller holds one long-poll open at a time (an idle coroutine), so thousands fit on the VPS.
- **Names:**
  - `entry.photonind.com`, `api.entry.photonind.com`, `link.entry.photonind.com` (controllers), `prov.entry.photonind.com` (intercom
    provisioning);
  - directory key `entry`; database owner `photonentry`, roles `entry_app` and `entry_system`; scope `entry:read`; header
    `X-PhotonEntry-Signature`.
  - The folder stays `photonaccess` (Connor, 2026-11-13).
- **Repo:**
  - `api/` (FastAPI, Alembic, tests);
  - `acap/` (`entry-link`, C, ACAP Native SDK; built with Axis's SDK container on LXC 800);
  - `sim/` (the Axis access-control API simulator, from Axis's public documentation);
  - `web/`;
  - `contract/` (site document, compiled settings, link protocol, door events, Guard and Vox payloads, Console feed);
  - `docs/`.
- **`entry-link` signing key:** a release key kept like PhotonBoard's (in `~/keys`, Bitwarden and one other place). The Axis signing account
  is Photon's, with Connor as the holder.

---

## 12. Order of work

| Step | What | Needs |
|---|---|---|
| **1** | Scaffold on a simulator: repo, link service, settings model and compiler, `entry-link` skeleton, the Axis simulator, tests end to end | Nothing (started 2026-11-13) |
| **2** | Database and directory: migration with RLS, directory copy, cardholders and credentials stored, the link on Postgres | D1 (or the directory's fake) |
| **later** | Bench H1–H11 (`docs/SPIKES.md`) and app signing | The bench kit and an axis.com account (Connor, when ready) |
| **3** | Integrator app: wizard, templates, import, groups, schedules, holidays, commissioning, events, fleet | Steps 1–2 |
| **4** | Akuvox: provisioning, reader mode, Vox door station, unlock from a call | Vox R1's engine adapter; H5–H8 |
| **5** | Guard: events, clips, access incidents, intercom cameras | Guard's ingest and incidents deployed |
| **6** | Visitor passes, phone unlock, lockdown, audit export, Console feed; a pilot site in PA, OH or WV | — |

---

## 13. Questions only Connor can answer

Answered 2026-11-13: the bench kit (not now), Axis contact (not now; the signing account later), Akuvox supply (Nelly's Security and SS&Si).

1. **When to buy the bench kit** (§3.6, about $2.9k): it gates the bench tests, and production on real doors.
2. **The axis.com account for app signing**, when `entry-link` is ready to sign (Photon's name, Connor the holder).
3. **The two build decisions** above (HTTPS long-poll; the link service in Python).
4. **First customers:** offices, schools, multifamily or gates? This decides the first templates and whether lockdown or the resident
   intercom comes first. How many doors in year one?
5. **Partners' licenses and the agreement:**
   - Which partners (or Photon's own technicians) will install in WV? They need SP-LV licenses.
   - Who does fire-alarm tie-ins in Ohio? That needs State Fire Marshal certification.
   - Who drafts the partner agreement's compliance clauses?
   - Is Photon's liability insurance right for door products?
6. **The phone app for customers without Vox:** the PhotonVox app, a separate app, or one suite app later? (Recommended: the phone page in R1;
   decide before R2.)
7. **Defaults:**
   - intercom live view included without a Guard plan (decision 13);
   - 3-year audit retention (decision 18);
   - per-door pricing at roughly $5–8 wholesale (decision 20).
8. **Existing UniFi Access sites:** support them in R2 (with a PhotonEdge), or not at all?

---

## 14. Proposed changes to other documents (not applied)

- **Suite ARCHITECTURE:**
  - §1: a PhotonEntry row (planned).
  - §5 roles: owner, admin, operator, viewer.
  - §7: Entry → Guard (events, incidents), Entry ↔ Vox (door stations, call records, unlock), Entry → Console (feed), controllers → the
    Entry link service.
  - §11: a PhotonEntry R1 phase after D1. It does not need E1.
- **Suite topics to design:**
  - a shared **site calendar** (Vox and Entry);
  - **emergency alerts** (Entry, Vox, Board, Guard);
  - a **suite release-key list** that includes `entry-link`'s signing key.
- **PhotonGuard:** incident source `access`; the `intercom` live-only entitlement; bindings of kind `door`.
- **PhotonVox:** the `door_station` extension kind; call-record lookup for Entry; the lockdown feature code; the app's door-call screen.
- **PhotonEdge:** `entry-agent` as an optional service (UniFi, R2).
- **photonid:** `entry` in the catalog once PhotonEntry publishes its roles.

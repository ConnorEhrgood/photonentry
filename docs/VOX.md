# PhotonEntry and PhotonVox: door stations and call records (BUILD-GUIDE §5, ARCHITECTURE §9.2)

Status: **proposed 2026-11-14**, PhotonEntry's side built against a fake. PhotonVox's side is PhotonVox's work (v1), with Connor's go-ahead; this
document does not change PhotonVox's repo. The contract: `contract/vox/` (schemas and samples).

## What each product owns

| | PhotonVox | PhotonEntry |
|---|---|---|
| The door station (an extension of kind `door_station`), its number and SIP account | ✓ (it is an extension like any other) | reads it |
| Its call flow ("front desk; after hours the manager's mobile") | ✓ (a Vox outcome, on the site calendar) | |
| The intercom's settings file (SIP account included) | | ✓ (Akuvox provisioning, `app/akuvox.py`) |
| Opening the door from a call | the DTMF reaches the intercom | ✓ (the intercom's web relay to entry-link) |
| Who answered | ✓ (call records) | asks, and names them in the door's events |

PhotonVox never provisions the intercom, and PhotonEntry never edits a phone system. Opening the door never depends on PhotonVox's API: only
naming who answered does.

## How it connects

1. In PhotonVox, an admin of the organization makes an **integration token for PhotonEntry**, scope **`vox:entry`** (it carries SIP passwords,
   so it is not `vox:read`, the PhotonConsole feed's scope), and pastes it into PhotonEntry (Settings > PhotonVox). As with PhotonGuard's
   ingest token: shown once, sealed in PhotonEntry, revocable in PhotonVox; PhotonVox's address is PhotonEntry's configuration
   (`VOX_API_URL`), never an organization's.
2. Each intercom in PhotonEntry picks its door station. PhotonEntry copies the station's SIP account into the intercom (sealed) at once and every
   hour after, so the intercom's settings never depend on PhotonVox being up.
3. After every "Opened from the intercom", PhotonEntry asks who answered that station's call at that moment, and records the answer with the event.

## The two endpoints (PhotonVox)

Both `GET`, `Authorization: Bearer <token>`, JSON, on `https://api.vox.photonind.com`. Each document names the organization (`organization_id`,
the directory's id); PhotonEntry refuses one naming another organization than the one it connected, as PhotonConsole does with the feeds.

- **`/integrations/entry/v1/door-stations`** (`door-stations.schema.json`): the organization's door stations, each with `id`, `name`,
  `site_id`, `extension` and its `sip` account (server, port, transport, username, password) and `updated_at`.
- **`/integrations/entry/v1/door-calls?station=<id>&at=<UTC>&window_s=<1..600>`** (`door-call.schema.json`): the call from that station in
  progress at `at`, else the one that ended last within `window_s` before it; `answered_by` is the extension that answered, its name and its
  directory person if it has one. `call: null` when there is none (yet). A station of another organization is 404.

Answers: 401 for an unknown or revoked token, 403 for a token without `vox:entry`, 404 as above, 200 otherwise. PhotonEntry asks a few times
a minute per organization at most.

## What PhotonVox would build

- **The `door_station` kind** in the phone-system document: a name, a site, an extension number, a call-flow outcome, and no voicemail. Its SIP
  account is made like any extension's (random password, TLS where the engine has it).
- **The DTMF path for the unlock code:** the person answering presses `#` (PhotonEntry's `UNLOCK_CODE`; ask before changing it). It has to
  reach the intercom as RFC 2833 telephone-events on every path a door station's call can take (desk phones, ring groups, a mobile through a
  trunk), and must not be taken by the engine as a feature code. Akuvox sends and receives RFC 2833 (`Config.Account1.DTMF.*`).
- **Integration tokens with scope `vox:entry`** and the two endpoints, from data PhotonVox keeps (call records: `v_xml_cdr` on the engine,
  by caller extension and time; the answering leg's extension and its user). Call records are CPNI: only the organization's own token reads
  them, and only for its door stations.
- **Later (ARCHITECTURE §9.2):** the lockdown feature code (`*55` and a PIN, never a code containing 911) calling PhotonEntry's lockdown, and the
  PhotonVox app's Unlock button (R2), which goes to PhotonEntry's API with the person's own session.

## Agreed with v1 (2026-11-14; PhotonVox is building its side, not deployed)

- `sip.server` is the phone system's SIP domain (FusionPBX is multi-tenant by domain), `username` the extension number (register name = auth
  name); port and transport come from the engine (5060/udp today, TLS later).
- A door station's account reaches only its own call flow: any digits it dials go there, except 911/933 (with or without 8 or 9), which go to
  the emergency route. **PhotonEntry sets the intercom's call button to "0"** (the Akuvox key for it is a bench item: AKUVOX-AUTOP.md §6). No
  "dial" field in the contract.
- Door flows ring users and ring groups, open or closed by hours; menus and voicemail are refused as door targets (a menu would swallow the
  `#`). v1 proves `#` as RFC 2833 on the user and ring-group paths on staging. No outside-number outcome yet.
- `door-calls`: `call.id` is FreeSWITCH's call UUID; `ended_at` can lag the hangup by the engine's call-record import interval (seconds), so a
  call that just ended may briefly read as in progress (PhotonEntry asks 20 s after the door opened, and again until 10 minutes). An outside
  number answering is "…1234". `person_id` is the directory person whose email matches the answering user's, else null.
- Tokens `pvx_entry_<random>`, stored hashed, shown once, revocable; PhotonVox capability `vox.entry.manage` (admin, owner; sensitive).
- `door-stations` lists the **published** phone system's doors (never a draft), each once its SIP password exists; station ids are the
  document's door keys (`^[a-z0-9-]+$`). 400 for a bad `at` or `window_s`.
- `sip.outbound_proxy` ("host:port" or null; always sent): customer SIP domains sit under a wildcard that resolves publicly to their engine, so
  it is normally null; PhotonVox sets it per engine where filtered or split DNS needs it, and PhotonEntry puts it in the intercom's
  `Config.Account1.OUTPROXY.*` keys (migration 0009).

## PhotonEntry's side (built 2026-11-14)

`app/vox.py` (the client, the SIP-account sync and the call matching), the `vox_link` table and `intercom.vox_station_id` (migration 0005),
Settings > PhotonVox in the web app, the door-station picker on an intercom, and "Opened from the intercom by <name> (<extension>)" in the events.
Tested against a fake that follows `contract/vox/`; never against PhotonVox itself.

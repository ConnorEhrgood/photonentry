# Akuvox auto-provisioning (Autop), without SmartPlus

Compiled 2026-11-14 from **public** Akuvox documents only (no account, no contact with Akuvox), for `api/app/akuvox.py`. Nothing here has been
tried on a device: **everything is to be confirmed on the bench (GATE H)**. Keys differ by model and firmware; before trusting a model, export its
Autop template from its web page (Upgrade > Advanced > Automatic Autop, or System > Auto Provisioning on newer firmware) and compare.
**UNVERIFIED** marks what no source states.

## Sources

| Tag | What |
|---|---|
| FN | KB "Upgrade Devices via Local Auto-Provisioning" (file-name table): https://knowledge.akuvox.com/docs/upgrade-devices-via-local-auto-provisioning |
| R29X | R29 Autop command sheet (fw 29.30.10.123), linked from https://knowledge.akuvox.com/docs/autop-commandsdoor-phones |
| R20X | R20A Autop command sheet (fw 320.30.11.42), same page |
| ALL | KB "AutoP Commands" master sheet (all models): https://knowledge.akuvox.com/docs/autop-commands-for-all-models |
| X915 | X915 Administrator Guide V1.0 (2021) |
| BW | BroadSoft Partner Config Guide, Akuvox (2017, sample templates) |
| R5X | SP-R5x auto-provisioning manual (2015, IP phones) |
| KB7, KB17 | https://knowledge.akuvox.com/docs/auto-provisioning-7, https://knowledge.akuvox.com/docs/auto-provisioning-via-configuration-file-17 |
| WR, RS | KB "Configure Web Relay on Door Phones"; KB R29 Relay Settings |
| AU, AUX | KB "Set up Action URL"; the per-model Action URL sheet |
| SEC | KB R29 Security (High Security Mode) |
| WG2, WG15, WGO | KB Wiegand integration pages; "Akuvox devices work as Wiegand output" |

## 1. Files

- **Per device:** `<MAC>.cfg`, upper-case hex without separators (`0C110504AE5B.cfg`) [X915]. Case of the request: UNVERIFIED (we answer either).
- **Per model ("general"):** fetched first, then the MAC file [X915, KB17, R5X]: S532 `r000000000532.cfg`, S535 `…535`, S539 `…539`, E18 `…018`,
  X912 `…912` (V2.0: `r000000002912`), X915 `…915` (V2 possibly `r000000002915`: UNVERIFIED), R29 `…029`, E12 V2 `r000000000012P`,
  R20 `r000000000020P` (older guide: `…020`), E16 V2 `…216` [FN]. We answer every general file with a file holding only comments.
- The configured URL is a **directory**; the device appends the file name [X915].
- **Syntax:** `Config.<Module>.<SECTION>.<Key> = <value>`, one per line; `#` starts a comment [BW, R5X]; booleans 0/1. Use the key case of the
  current sheets (`Config.Account1.SIP.Server`).
- "Clear MD5": the device skips a file whose content has not changed [KB17].

## 2. Where the device finds us

- **Static ("Manual Autop"):** `Config.Autoprovision.GENERAL.Url` (+ `.UserName`, `.Pwd`) [R29X, ALL]. Manual provisioning requires PNP and DHCP
  options off [KB7]: `Config.Autoprovision.PNP.Enable = 0`. Typed in by the installer once; our file repeats it.
- **Schedule:** `Config.Autoprovision.MODE.Mode`: 0 off, 1 power on, 2 repeatedly, 3 power on + repeatedly, **4 hourly** [R29X, R20X, ALL].
  Whether mode 4 also fetches at power-up: UNVERIFIED.
- **HTTPS** is supported for Autop [X915]. Whether the device validates the server's certificate: UNVERIFIED (assume not: the token in the
  address is the protection, and the address is HTTPS with a publicly trusted certificate).

## 3. Encryption: not used (yet)

`Config.Autoprovision.AES.Key16` (general file) and `.Key16Mac` (MAC file) hold 16-character keys [R29X, ALL, BW], i.e. AES-128. **The mode,
padding, IV and whether the whole file is encrypted are documented nowhere public**, and Akuvox's tool is not public. A wrong guess leaves the
intercom unable to read its settings, so PhotonEntry serves the files in clear over HTTPS, at an address holding a per-device random token.
Bench item: encrypt a file with Akuvox's tool, find the scheme, then add `Key16Mac`.

## 4. Keys PhotonEntry sets

| What | Key | Value |
|---|---|---|
| SIP account 1 on | `Config.Account1.GENERAL.Enable` | 1 |
| Label, display name | `Config.Account1.GENERAL.Label`, `.DisplayName` | the intercom's name |
| Register name (SIP user; the UI's "Register Name") | `Config.Account1.GENERAL.UserName` | |
| Auth name (the UI's "User Name") | `Config.Account1.GENERAL.AuthName` | the same user |
| SIP password | `Config.Account1.GENERAL.Pwd` | |
| Server, port | `Config.Account1.SIP.Server`, `.Port` | |
| Transport | `Config.Account1.SIP.TransType` | 0 UDP, 1 TCP, 2 TLS [R29X, BW] |
| SRTP | `Config.Account1.ENCRYPTION.SRTPEncryption` | 2 optional, with TLS; 0 otherwise |
| Web admin password (user admin) | `Config.Settings.WEB_LOGIN.Password` | random [ALL] |
| Wiegand mode | `Config.DoorSetting.GENERAL.WiegandMode` | 1 output |
| Wiegand format | `Config.DoorSetting.GENERAL.WiegandType` | 1 W34 (26-bit drops a byte, §3.4) |
| Card check off (forward every card) | `Config.DoorSetting.GENERAL.WiegandOutVerify` | 0 |
| Wiegand never opens the local relay | `Config.DoorSetting.GENERAL.WiegandOpenRelayA` / `B` | 0 |
| PIN output | `Config.DoorSetting.GENERAL.WiegandPINCodeOutput` | 2 (4 bits a digit; to match the Axis PIN setting on the bench) |
| Tamper never fires the relay | `Config.DoorSetting.GENERAL.TamperOptions` | 0 alarm only |
| DTMF never opens the local relay | `Config.DoorSetting.RELAY.DTMFUnlock` / `Config.DoorSetting.DTMF.WhitelistEnable` | 0 (R20A / R29 names) |
| Web relay only | `Config.DoorSetting.WEBRELAY.RelayType` | 1 |
| Web relay target | `Config.DoorSetting.WEBRELAY.IpAddress` | blank: the action is a full URL [WR] |
| Web relay auth | `Config.DoorSetting.WEBRELAY.AuthorizationMode` | 0 none (only None or Digest exist) |
| Action 1 and its DTMF code | `Config.DoorSetting.WEBRELAY.WebRelay_Action_1`, `.WebRelay_Key_1` | `http://<controller>/v1/relay?intercom=<id>&key=<key>`, the unlock code |
| DTMF code length, code | `Config.DoorSetting.DTMF.Option`, `Config.DoorSetting.DTMF.Code1` | 0 (one digit), the unlock code ("the same in the Web Relay Key field and DTMF settings" [WR]) |
| Action URLs on, GET, no auth | `Config.Features.ACTIONURL.Enable`, `.Type`, `.AuthorizationMode` | 1, 0, 0 |
| Call started, ended | `Config.Features.ACTIONURL.MakeCall`, `.HangUp` | `…/v1/event?…&kind=call_start&remote=$remote` (`$remote`) |
| Tamper | `Config.Features.ACTIONURL.TamperAlarmTriggered` | `…&kind=tamper`; key sourced for A092/A094 only, E18/E16V2 list a tamper event: UNVERIFIED on the rest |

## 5. Web relay and action URLs: the requests

- Web relay: HTTP **GET** [WR]. A relative action goes to `IpAddress`; a full URL ignores it [RS]. How the device joins IP and action, whether
  `user:pass@` in a URL becomes Basic auth, and whether HTTPS works: UNVERIFIED. Hence the full URL with the key as a parameter; entry-link also
  accepts the key as a Basic login.
- During a call the far end sends the DTMF code in `WebRelay_Key_N` and the device sends Action N [WR].
- Action URLs: GET (POST on some models), `$remote`, `$mac`, `$ip`, `$card_sn`, `$code`, `$alarmstatus` [AU, AUX]. Whether arbitrary query
  syntax survives: UNVERIFIED.

## 6. Bench checklist (GATE H)

1. Each model fetches `<MAC>.cfg` from an HTTPS directory URL; the general file's 200-with-comments is accepted.
2. Every key above takes effect (compare the exported template); mode 4 also fetches at power-up.
3. With card check off, cards and PINs reach the Axis A1210/A1610 as 34-bit Wiegand; the local relay stays off for cards, DTMF and tamper.
4. The web relay's full URL with a query string reaches entry-link; the unlock code during a call from a PhotonVox desk phone opens the door.
5. MakeCall, HangUp and tamper action URLs arrive; `$remote` is filled.
6. AES: the scheme of Akuvox's tool, then `Key16Mac`.
7. High Security Mode (on after a factory reset [SEC]) does not block any of it.

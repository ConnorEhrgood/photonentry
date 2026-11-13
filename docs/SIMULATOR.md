# The Axis door controller simulator (`sim/`)

A simulated **AXIS A1210 / A1610** network door controller, built only from Axis's public VAPIX documentation for physical access
control. `entry-link` and the cloud are tested against it end to end until real controllers are on the bench (BUILD-GUIDE GATE H).

- **The reference:** `sim/reference/AXIS-PACS.md`, compiled 2026-11-13 from developer.axis.com (calling convention, door control, access
  control, users, schedules, ID points, events, the event logger, ACAP loopback access). Axis's JSON examples are quoted there verbatim;
  51 points Axis does not document are marked INFERRED.
- **The rule:** when the bench shows a difference, **fix the simulator first** (and this file), then the code, so the test suite keeps
  describing the real device.

## What it does

| Area | Simulated |
|---|---|
| Calling convention | `POST /vapix/{doorcontrol,pacs,schedule,idpoint,eventlogger}` with `{"prefix:Method": {...}}`; bare responses; `{"Token": [...]}` for every Set; Axis's JSON fault body; the method prefixes each endpoint accepts |
| Authentication | Digest (MD5, qop=auth, realm `AXIS_<MAC>`) and Basic, both offered on a 401; default account `root` / `pass` |
| Objects | Get, GetList (paged with `Limit`, `StartReference`, `NextStartReference`), GetInfo, GetInfoList, Set (generated tokens `Axis-<mac>:<epoch>.<n>`), Remove, for doors, door configurations, door schedule configurations, access points, the access controller, authentication profiles, access profiles, credentials, users, schedules, ID points |
| Checks on Set | References must exist (schedules, access points, access profiles, door schedules), iCalendar must parse, `CardNr` unique, IdData names unique per credential, names up to 64 characters, tokens up to 64 |
| Factory state | A commissioned controller: doors with a relay lock and a door monitor; on an A1610 two readers on door 1 (in, out) and one on door 2; access points with `CardOnly` and `PINOnly`; Axis's schedules `standard_always`, `standard_office_hours`, `standard_weekends`; Axis's authentication profiles `CardOnly`, `PINOnly`, `CardPlusPin`, `REXOnly` |
| Doors | Modes `Locked`, `Unlocked`, `Accessed`, `Blocked`, `LockedDown`, `LockedOpen`, `DoubleLocked`; `AccessDoor` for AccessTime; relocking when the door closes after an access; forced open; held open with the pre-alarm warning; door schedules (the first active ScheduledState's EnterAction, applied when it changes and when the configuration is set) |
| Decisions | Access point enabled → authentication profiles active by schedule → matching credentials by `IdDataEqual` → credential enabled and valid → its access profiles valid, enabled, active → an access policy for this access point with an active schedule. REX by `OperatorValueEqual` grants anonymously. Reasons as Axis and ONVIF name them |
| Schedules | Axis's iCalendar subset: local times, `DTSTART`/`DTEND`, whole days, `RRULE` WEEKLY with BYDAY, DAILY, MONTHLY with BYMONTHDAY, YEARLY, INTERVAL, UNTIL, `RDATE` dates; exception definitions; "any active, none excepted" |
| Events | The event logger's records (`rowid`, `token`, `UUID`, `UtcTime`, `KeyValues` with `topic0..3` and Axis's tags), 30,000-event capacity with the oldest dropped, `axlog:FetchEvents` with `RowID`, `Limit` (at most 1000), `Filters`, `Descending`, `More` |
| Remote activities | `axtid:IndicateRemoteActivities` (card, PIN, REX), as an IP reader or an intercom's unlock would use it |
| Test control | `/sim/present` (a credential at a reader), `/sim/door` (open, close), `/sim/clock` (move time), `/sim/offline` (the API answers 503), `/sim/state`. No authentication: the simulator is only ever bound to loopback |

## Choices Axis does not document (INFERRED)

Each is a guess to check on the bench (ARCHITECTURE §3.6).

1. **HTTP status of a fault:** 400 for `env:Sender`, 500 for `env:Receiver`.
2. **MaxLimit:** 100 by default (Axis gives no number), configurable; the end-to-end tests run with 2 to force paging.
3. **Denial reason when a valid profile has no active policy:** `NotPermittedAtThisTime` if a policy exists for the access point (outside
   its schedule), `Unauthorized` if none does.
4. **Several authentication profiles on one access point:** a credential is accepted if it satisfies any active one.
5. **Door actions while locked down or locked open:** a `ter:Failure` fault (Axis: "an error to the caller"). Lock down over locked open is
   allowed.
6. **Priorities:** one level (Axis's default `Standard` configuration): a door action and a schedule's enter action replace each other. The
   priority stack itself is not simulated.
7. **Set checks:** references are checked strictly (Axis documents the fault names, not every check).
8. **A factory-new controller** has no doors; the simulator starts from the commissioned state an installer leaves.
9. **Pulse schedules** (no DTEND) are accepted and never "active"; `COUNT` is not evaluated.
10. **Card data:** a credential's `Card` is compared with the reader's raw hex. 34-bit cards are padded to 10 hex digits by the 26-bit
    example's rule (`api/app/compiler/wiegand.py`; bench H5).

## Not simulated

Anti-passback, areas, duress, multi-controller peer networks (`aconn`), I/O assignment (`/vapix/pin`), the keystore, OSDP secure channel,
card-format configurations (`IdDataConfiguration`), the alarm list and its filters, the event WebSocket and ONVIF pull points, SOAP, the
ACAP D-Bus service account (the simulator takes a configured login).

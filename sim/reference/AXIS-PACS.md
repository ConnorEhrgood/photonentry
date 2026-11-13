# Axis A1210 / A1610 network door controller - VAPIX Physical Access Control (PACS) API reference for a simulator

Compiled 2026-11-13 from Axis's public docs only (no sign-up):
- https://developer.axis.com/vapix/physical-access-control/ (overview) and sub-pages: access-control-service, door-control-service, idpoint-service, schedule-service, user-service, event-logger-service, connection-service, io-assignment-service, keystore-service, peripherals, system-integration-examples, third-party-credential-service
- https://developer.axis.com/vapix/authentication/
- https://developer.axis.com/vapix/network-video/event-streaming-over-websocket/
- https://developer.axis.com/acap/how-to-guides/VAPIX-access-for-ACAP-applications/
- ONVIF Access Control Service Spec and ONVIF Door Control Service Spec PDFs (onvif.org/specs/srv/access/..., /srv/door/...), for event message descriptions.

Conventions in this file: "verbatim" blocks are copied from the docs (whitespace may differ). Anything marked INFERRED is my reading, not stated in the docs. `[min][max]` cardinalities are from the docs' message tables. The docs show both JSON and SOAP; only JSON is reproduced here.

Cleaned text dumps of every source page are kept next to this file in `txt/` (`*.j.txt` = JSON-only, cleaned) if a detail needs re-checking.

## 1. Calling convention

### 1.1 Endpoints
Supported services (table "Supported services and namespaces", verbatim content):

| Service | SOAP namespace | Prefix | JSON endpoint | Controllers |
|---|---|---|---|---|
| Connection service | http://www.axis.com/vapix/ws/connection | `aconn` | `/vapix/aconn` | A1001 |
| Door control service | http://www.onvif.org/ver10/doorcontrol/wsdl | `tdc` | `/vapix/doorcontrol` | A1001, A1210, A1601, A1610 |
| (Door control, Axis ext.) | http://www.axis.com/vapix/ws/DoorControl | `axtdc` | `/vapix/doorcontrol` | A1001, A1210, A1601, A1610 |
| Event logger service | http://www.axis.com/vapix/ws/EventLogger | `axlog` | `/vapix/eventlogger` | A1001, A1210, A1601, A1610 |
| (Event logger config) | http://www.axis.com/vapix/ws/EventLoggerConfig | `axloc` | `/vapix/eventlogger` | A1001, A1210, A1601, A1610 |
| IdPoint service | http://www.axis.com/vapix/ws/IdPoint | `axtid` | `/vapix/idpoint` | A1001, A1210, A1601, A1610 |
| I/O assignment service | http://www.axis.com/vapix/ws/AxisIo | `axisio` | `/vapix/pin` | A1001, A1210, A1601, A1610 |
| AccessControl service | http://www.onvif.org/ver10/accesscontrol/wsdl | `tac` | `/vapix/pacs` | A1001, A1210, A1601, A1610 |
| (AccessControl, Axis ext.) | http://www.axis.com/vapix/ws/pacs | `pacsaxis` | `/vapix/pacs` | A1001, A1210, A1601, A1610 |
| Schedule service | http://www.axis.com/vapix/ws/schedule | `axsch` | `/vapix/schedule` | A1001, A1210, A1601, A1610 |
| User service | http://www.axis.com/vapix/ws/user | `axudb` | `/vapix/pacs` | A1001, A1210, A1601, A1610 |
| Service discovery service | http://www.axis.com/vapix/ws/AxisServiceDiscovery | `axissd` | `/vapix/axissd` | A1001, A1210, A1601, A1610 |
| Remote I/O service | http://www.axis.com/vapix/ws/axrio | `axrio` | `/vapix/axrio` | A1001, A1210, A1601, A1610 |
| Keystore service | http://www.axis.com/vapix/ws/KeyStore | `axkey` | `/vapix/axkey` | A1001, A1210, A1601, A1610 |
| Third party credential service | http://www.axis.com/vapix/ws/thirdpartycredential | `axtpc` | `/vapix/axtpc` | A1001 |

Also used: `axconf` = `http://www.axis.com/vapix/ws/Config` (Name/Value configuration types), `pt` (ONVIF common types, `pt:ReferenceToken`), `tt` (ONVIF schema), `ter` (ONVIF error codes), `env` (SOAP envelope), `tns1` (ONVIF topic namespace), `tnsaxis` (Axis topic namespace).

There are NO endpoints `/vapix/credential`, `/vapix/accesspolicy`, `/vapix/accessrules`, and no `axcred`/`axel` prefixes. Credentials, access profiles, authentication profiles, access points, areas, access controller and users are all on `/vapix/pacs`. Note that the Connection service row lists A1001 only, yet the overview's UUID section uses `aconn:GetPeerList` generically (INFERRED: present on all models).

SOAP alternative: everything also via `POST /vapix/services` with a SOAP envelope (not needed for a JSON simulator, but a client may use it).

### 1.2 Request / response shape (JSON)
- HTTP `POST` to the service endpoint (curl `-d` / `--data`). Examples use either no content type (`curl -d`, i.e. `application/x-www-form-urlencoded`) or `-H "Content-Type: application/json"`. INFERRED: the device ignores the request Content-Type; a simulator should accept both.
- Body: a JSON object with exactly one key, the prefixed method name, whose value is the request message object (field names exactly as in the message tables; `{}` for empty requests):
```
{
    "pacsaxis:GetAccessControllerList": {}
}
```
- Response: the response message's fields directly as a JSON object, with NO method/"Response" wrapper:
```
{
    "AccessController": [
        {
            "token": "Axis-00408c184bdb AccessController",
            "Name": "Axis-00408c184bdb AccessController",
            "Description": "",
            "AccessPoint": []
        }
    ]
}
```
- Empty response message -> `{}` (shown verbatim for `axtid:IndicateRemoteActivities`).
- Set responses -> `{"Token": [...]}` (verbatim from Entry Manager examples, including for `axudb:SetUser` and `pacsaxis:SetCredential`):
```
{
    "Token": ["Axis-00408c184bd9:1350638010.566278000"]
}
```
- JSON mapping of the XML schema (as seen across all examples): XML attribute `token` -> key `"token"` (lowercase); element `Token` in requests -> `"Token"` (capitalised); list-typed fields `[0][unbounded]` / `[1][unbounded]` are always JSON arrays even with one item (e.g. `"Token": ["..."]` for Get/Remove, `"Schedule": ["standard_always"]`); a single-valued `[1][1]` field like `GetDoorState.Token` is a plain string. Booleans are JSON booleans; ints are JSON numbers (`MinPINSize: 4`, `Limit: 2`); durations and dateTimes are strings (`"PT10S"`, `"2038-01-01T00:00:00Z"`); Name/Value lists use string values even for numbers (`{"Name":"BitCount","Value":"26"}`). Optional strings commonly come back as `""` rather than absent (e.g. `ValidFrom: ""`). Some guide examples show a single object instead of an array (`"Credential": {...}`, `"AccessPoint": {...}`) - those are object dumps, not request shapes.
- Some request examples in the docs have a key typo or alternative prefix (e.g. `"axkey:SetEncryptionKey": {"axkey:EncryptionKey": [...]}` uses a prefixed inner key). INFERRED: the device tolerates a namespace prefix on inner keys.
- curl example (verbatim):
```
$ curl --anyauth "http://<user>:<password>@<servername>/vapix/pacs" -s -d '{"pacsaxis:GetAccessControllerList":{}}'
```

### 1.3 Errors / faults
The docs give ONE verbatim JSON fault body (from the SmartIntego whitelist section):
```
{
    "Fault": "env:Sender",
    "FaultCode": "ter:InvalidArgs",
    "FaultSubCode": "ter:InvalidCredentialFault",
    "FaultReason": "Invalid argument",
    "FaultMsg": "Id data XX required for credential 'xx'"
}
```
So the JSON fault shape is: `Fault` (SOAP env code: `env:Sender` | `env:Receiver`), `FaultCode` (first ter subcode), `FaultSubCode` (second ter subcode), `FaultReason` (human text), `FaultMsg` (detail). The message tables list faults as three codes `env:X ter:Y ter:Z`, e.g. `env:Sender ter:InvalidArgVal ter:NotFound`, which map to Fault / FaultCode / FaultSubCode.
INFERRED (not documented): HTTP status for a fault (likely 4xx/5xx; real Axis SOAP faults are HTTP 500 - choose 400 for Sender and 500 for Receiver, or 500 for both, and make it configurable); `FaultReason` text values other than "Invalid argument".

Fault triples that appear in the docs:
- `env:Sender / ter:InvalidArgVal / ter:NotFound` - token not found (door actions, Remove*, GetDoorState, ...)
- `env:Sender / ter:InvalidArgVal / ter:InvalidStartReference` - bad/expired StartReference
- `env:Sender / ter:InvalidArgs / ter:TooManyItems` - Get with more tokens than MaxLimit
- `env:Sender / ter:InvalidArgs` - generic invalid Set
- `env:Receiver / ter:ActionNotSupported / ter:NotSupported` - op not supported / not allowed to remove
- `env:Receiver / ter:ActionNotSupported / ter:NotAllowed` and `env:Sender / ter:ActionNotSupported / ter:NotAllowed` (SetAccessController)
- `env:Receiver / ter:Action / ter:Failure` - door could not change state
- Type-specific: `ter:InvalidCredentialFault`, `ter:InvalidAccessProfileFault`, `ter:InvalidDoorConfigurationFault`, `ter:InvalidDoorScheduleFault`, `ter:InvalidScheduleFault`, `ter:InvalidIdPointConfigurationFault`, `ter:InvalidConfigurationFault`, `ter:ConfigurationNotFound` (GetLastCredential), `ter:InvalidStartTime` / `ter:InvalidStopTime` (FetchEvents), `ter:None` (GetCredentialStatistics, anti-passback).
INFERRED: an unknown method name or malformed JSON returns a fault too (shape as above; e.g. `env:Sender / ter:InvalidArgVal`); not documented.

### 1.4 Authentication
- HTTP Digest (recommended on HTTP) or Basic (recommended on HTTPS). First request without credentials -> `401 Unauthorized` with `WWW-Authenticate` header naming supported method(s); examples use `curl --anyauth`. Policy configurable via parameter `Network.HTTP.AuthenticationPolicy`.
- Digest realm format seen: `AXIS_ACCC8EC43707` (`AXIS_<MAC>`), `algorithm=MD5`, `qop="auth"`.
- Roles: Administrator, Operator, Viewer. PACS doc: "admin level is required for all actions" (administrative user distribution section). ONVIF access classes are listed per method (PRE_AUTH, READ_SYSTEM, READ_SYSTEM_SENSITIVE, READ_SYSTEM_SECRET, ACTUATE, WRITE_SYSTEM, READ_CAPABILITIES). INFERRED mapping: PRE_AUTH = no auth; READ_* = viewer+; ACTUATE = operator+; WRITE_SYSTEM = admin.
- Default account on the door controllers (verbatim): user name `root`, password `pass`.
- Admin user management is outside PACS: `/axis-cgi/pwdgrp.cgi` (VAPIX users) and `/onvif/device_service` (ONVIF users); replicated to all peers by "administrative user distribution".

### 1.5 Tokens, UUIDs, multi-controller
- Device-generated tokens look like `Axis-<mac12 lowercase>:<unix seconds>.<9-digit fraction>` e.g. `Axis-00408c184bdb:1352121495.979065000`. The default access controller token is `Axis-<mac> AccessController`. Client-chosen tokens are allowed (e.g. `myDoor`, `Main entrance in`, with spaces).
- Tokens are unique per data type; different types may share a token. Door/DoorConfiguration/DoorScheduleConfiguration (Entry Manager convention), IdPoint/IdPointConfiguration, AccessController/AccessControllerConfiguration are linked by SAME token.
- Device UUID format: `5581ad80-95b0-11e0-b883-00408c184bdb` (fixed prefix `5581ad80-95b0-11e0-b883-` + MAC, as in every example). `DeviceUUID`/`DoorDeviceUUID` empty -> the receiving device. In a multi-controller network any controller accepts requests and routes by UUID. `aconn:GetPeerList` lists peers (`Self.ID` = MAC uppercase e.g. `00408C184BDB`).
- Max name lengths: Name 64 chars, Description 1024 chars (ONVIF types).

Contents: 1 Calling convention | 2 Door control | 3-5 Access control (access controller, access points, areas, credentials, authentication profiles, access profiles, RequestAccess, anti-passback) | 4 Users (axudb) | 6 Schedules (axsch) | 7 IdPoint (readers, card formats, remote activities) | 8 Events (topics, fields, event logger, pull-point, websocket) | 9 ACAP loopback | 10 Other services + Entry Manager conventions | 11 Simulator checklist

## 2. Door control service (`tdc` + `axtdc`), JSON endpoint `/vapix/doorcontrol`

Source: https://developer.axis.com/vapix/physical-access-control/door-control-service/

Namespaces:
- `tdc` = `http://www.onvif.org/ver10/doorcontrol/wsdl` (ONVIF Door Control)
- `axtdc` = `http://www.axis.com/vapix/ws/DoorControl` (Axis extension: Door config, priorities, schedules)
- `axconf` = `http://www.axis.com/vapix/ws/Config` (the `Configuration` / `ConfigurationInfo` Name/Value types)
- `pt:ReferenceToken` = ONVIF reference token (string; ONVIF limits to 64 chars - INFERRED from ONVIF common types, not stated on the Axis page)

Which prefix goes with which method (as written in the docs): `tdc:` for GetServiceCapabilities, GetDoorInfoList, GetDoorInfo, GetDoorState, AccessDoor, LockDoor, UnlockDoor, BlockDoor, LockDownDoor, LockDownReleaseDoor, LockOpenDoor, LockOpenReleaseDoor, DoubleLockDoor. `axtdc:` for SetDoor, GetDoorList, GetDoor, RemoveDoor, ReleaseDoor, AccessDoorWithoutUnlock, Get/Set/Remove PriorityConfiguration(+List), GetDoorPriorityState, Get/Set/Remove DoorConfiguration(+List, +Info), Get/Set/Remove DoorScheduleConfiguration(+List). (The guide text says "calling `axtdc:SetDoor`"; the API table's Door/GetDoorList response type is written `tdc:Door` - a doc inconsistency; the Door type is defined under the `axtdc` heading. Treat `axtdc:SetDoor/GetDoor/GetDoorList/RemoveDoor` as the canonical names. INFERRED that `tdc:GetDoorList` is not accepted.)

Access classes (ONVIF): GetServiceCapabilities PRE_AUTH; GetDoorInfoList/GetDoorInfo/GetDoorConfigurationInfo READ_SYSTEM; GetDoorState, GetDoorList, GetDoor, GetDoorPriorityState, Get*Configuration* READ_SYSTEM_SENSITIVE; all door actions ACTUATE; Set*/Remove* WRITE_SYSTEM.

### 2.1 ServiceCapabilities (`tdc:GetServiceCapabilities`)
Request: empty -> `{"tdc:GetServiceCapabilities":{}}`. Response: `Capabilities` [1][1] (`tdc:ServiceCapabilities`):
- `MaxLimit` - max entries returned by a single GetList or Get request.
- `GetDoorSupported` - true if GetDoor and GetDoorList supported.
- `SetDoorSupported` - true if SetDoor and SetDoorList supported.
- `PriorityConfigurationSupported` - true if PriorityConfigurations can be modified.
INFERRED JSON response shape: `{"Capabilities":{"MaxLimit":..., "GetDoorSupported":true, "SetDoorSupported":true, "PriorityConfigurationSupported":true}}` (no JSON example in docs; in ONVIF these are XML attributes, and the Axis JSON flattens attributes to plain keys as it does for `token`).

### 2.2 DoorInfo / DoorCapabilities
`DoorInfo` fields: `token` (required), `Name` (required, <=64 chars), `Description` (optional, <=1024 chars), `Capabilities` (required, `DoorCapabilities`).

`DoorCapabilities` (all booleans except PriorityLevels): `Access`, `AccessTimingOverride`, `Lock`, `Unlock`, `Block`, `DoubleLock`, `LockDown`, `LockOpen`, `DoorMonitor`, `LockMonitor`, `DoubleLockMonitor`, `Alarm`, `Tamper`, `Fault`, `Warning`, `Configurable`, `PriorityLevels` (int: number of priority levels supported, 0 or 1 = priorities not supported).

`tdc:GetDoorInfoList` request: `Limit` xs:int [0..1], `StartReference` xs:string [0..1]. Response: `NextStartReference` [0..1], `DoorInfo` [0..n]. Fault: `env:Sender/ter:InvalidArgVal/ter:InvalidStartReference`.
`tdc:GetDoorInfo` request: `Token` [1..n] (array of tokens). Response: `DoorInfo` [0..n]. Unknown tokens ignored. Fault if more than MaxLimit: `env:Sender/ter:InvalidArgs/ter:TooManyItems`.

### 2.3 DoorState (`tdc:GetDoorState`)
Request: `{"tdc:GetDoorState":{"Token":"<door token>"}}` (Token [1][1]). Response: `DoorState` [1][1]. Fault: `env:Sender/ter:InvalidArgVal/ter:NotFound`.

`DoorState` fields:
- `DoorMode` (required, `DoorMode`)
- `DoorPhysicalState` (optional; present if DoorMonitor capability) - `DoorPhysicalState`
- `LockPhysicalState` (optional; LockMonitor capability) - `LockPhysicalState`
- `DoubleLockPhysicalState` (optional; DoubleLockMonitor capability) - `LockPhysicalState`
- `Alarm` (optional; Alarm capability) - `DoorAlarmState`
- `Tamper` (optional; Tamper capability) - `DoorTamper` object `{State, Reason?}`
- `Fault` (optional; Fault capability) - `DoorFault` object `{State, Reason?, DoorMonitorFault?, LockFault?, DoubleLockFault?, LockMonitorFault?}`

Enums (exact):
- `DoorMode`: `Unknown`, `Locked`, `Unlocked`, `Accessed`, `Blocked`, `LockedDown`, `LockedOpen`, `DoubleLocked`
- `DoorPhysicalState`: `Unknown`, `Open`, `Closed`, `Fault`
- `LockPhysicalState`: `Unknown`, `Locked`, `Unlocked`, `Fault`
- `DoorAlarmState`: `Normal`, `DoorForcedOpen`, `DoorOpenTooLong`
- `DoorWarningState` (used by the DoorWarning event): `Normal`, `DoorOpenTooLongWarn`
- `DoorTamperState`: `Unknown`, `NotInTamper`, `TamperDetected`
- `DoorFaultState`: `Unknown`, `NotInFault`, `FaultDetected`
- `DoorFault` booleans: `DoorMonitorFault`, `LockFault`, `DoubleLockFault`, `LockMonitorFault`

INFERRED JSON GetDoorState response (no JSON example in docs):
```
{"DoorState":{"DoorPhysicalState":"Closed","LockPhysicalState":"Locked","Alarm":"Normal","DoorMode":"Locked"}}
```

DoorMode semantics (from docs):
- `Locked`: momentary access via AccessDoor possible.
- `Unlocked`: permanent access; forced/open-too-long alarms masked.
- `Accessed`: momentary access; "door forced" alarms masked. Returns to previous state when AccessTime elapses (or when door is closed after opening - guide: "automatically locked again when closed or when AccessTime expires if not opened").
- `Blocked`: locked, AccessDoor requests ignored.
- `LockedDown`: locked until LockDownReleaseDoor; AccessDoor, LockDoor, UnlockDoor, BlockDoor, LockOpenDoor are ignored. Guide: "All other attempts to change the door state will generate an error to the caller".
- `LockedOpen`: unlocked until LockOpenReleaseDoor; AccessDoor, LockDoor, UnlockDoor, BlockDoor, LockDownDoor ignored (guide says error to caller).
- `DoubleLocked`: secondary lock also locked; if no DoubleLock treat as Locked. "Requesting tdc:UnlockDoor will move the door state to Locked" (guide table) / "When changing to an Unlocked mode from the DoubleLocked mode, the door may first go to Locked state before unlocking" (spec).
- LockDownReleaseDoor: only succeeds if current mode is LockedDown; next state "typically Locked". LockOpenReleaseDoor: only if LockedOpen; next "typically Unlocked".

### 2.4 Door action commands (all: response is empty `{}`; INFERRED that JSON success body is `{}`)
| Method | Request fields | Faults |
|---|---|---|
| `tdc:AccessDoor` | `Token` [1], `UseExtendedTime` xs:boolean [0..1], `AccessTime` xs:duration [0..1], `OpenTooLongTime` xs:duration [0..1], `PreAlarmTime` xs:duration [0..1], `Extension` [0..1] | `env:Sender/ter:InvalidArgVal/ter:NotFound`; `env:Receiver/ter:Action/ter:Failure` ("Failed to go to Accessed state and unlock the door") |
| `axtdc:AccessDoorWithoutUnlock` | same as AccessDoor (`Token`, `UseExtendedTime`, `AccessTime`, `OpenTooLongTime`, `PreAlarmTime`, `Extension`) | `env:Receiver/ter:InvalidArgVal/ter:NotFound` (sic, Receiver); `env:Receiver/ter:Action/ter:Failure` |
| `tdc:LockDoor` | `Token`, `PriorityLevel` xs:string [0..1] ("if empty use default priority"), `Extension` | NotFound; Failure ("Failed to go to Locked state") |
| `tdc:UnlockDoor` | `Token`, `PriorityLevel`, `Extension` | NotFound; Failure |
| `tdc:BlockDoor` | `Token`, `PriorityLevel`, `Extension` | NotFound; Failure |
| `tdc:LockDownDoor` | `Token`, `PriorityLevel`, `Extension` | NotFound; Failure |
| `tdc:LockDownReleaseDoor` | `Token`, `PriorityLevel`, `Extension` | NotFound; Failure |
| `tdc:LockOpenDoor` | `Token`, `PriorityLevel`, `Extension` | NotFound; Failure |
| `tdc:LockOpenReleaseDoor` | `Token`, `PriorityLevel`, `Extension` | NotFound; Failure |
| `tdc:DoubleLockDoor` | `Token`, `PriorityLevel`, `Extension` | NotFound; Failure |
| `axtdc:ReleaseDoor` | `Token`, `PriorityLevel`, `Extension` | NotFound |

Note: `PriorityLevel` on lock/unlock/etc. is an Axis addition (not in ONVIF tdc). AccessDoor has no PriorityLevel field in the docs.

Verbatim JSON examples:
```
{
    "tdc:AccessDoor": {
        "Token": "Axis-00408c184bdb:1352121495.979065000"
    }
}
```
```
{
    "tdc:UnlockDoor": {
        "Token": "Axis-00408c184bdb:1352121495.979065000"
    }
}
```
```
{
    "axtdc:AccessDoorWithoutUnlock": {
        "Token": "Axis-00408c184bdb:1352121495.979065000"
    }
}
```
```
{
    "tdc:UnlockDoor": {
        "Token": "Axis-00408c184bdb:1352121495.979065000",
        "PriorityLevel": "Medium"
    }
}
```
```
{
    "axtdc:ReleaseDoor": {
        "Token": "Axis-00408c184bdb:1352121495.979065000",
        "PriorityLevel": "Medium"
    }
}
```
"No return values are given by the API functions, but the API function may raise errors, e.g. if specified token is not found."

`AccessDoorWithoutUnlock`: door goes to `Accessed` without driving the lock; used so that no `DoorForcedOpenAlarm` (sic) is raised when someone opens a manually-unlockable door during the grant window.

Door states table (guide, verbatim meaning):
| State | API function |
|---|---|
| `Locked` | `tdc:LockDoor` |
| `Unlocked` | `tdc:UnlockDoor` |
| `Accessed` | `tdc:AccessDoor` ("Call to tdc:UnlockDoor is possible to keep the door unlocked") |
| `Blocked` | `tdc:BlockDoor` |
| `LockedDown` | `tdc:LockDownDoor` |
| `LockedOpen` | `tdc:LockOpenDoor` |
| `DoubleLocked` | `tdc:DoubleLockDoor` |

### 2.5 Door (axtdc config entity) - `axtdc:SetDoor`, `GetDoorList`, `GetDoor`, `RemoveDoor`
`Door` fields: `token`, `Name` (<=64), `Description` (optional, <=1024), `AccessTime`, `OpenTooLongTime`, `PreAlarmTime`, `ExtendedAccessTime`, `ExtendedOpenTooLongTime`, `HeartbeatInterval` (0 = no heartbeat events), `PriorityConfiguration` (token; default config is called `Standard`), `DefaultPriority` (if empty, PriorityConfiguration's DefaultPriority used). All times are `xs:duration` strings (e.g. `"PT10S"`).

Timing semantics: AccessTime starts when door goes to Accessed; OpenTooLongTime starts when door is opened, `DoorAlarm` event sent if still open when reached; PreAlarmTime = how long before OpenTooLongTime expires a `DoorWarning` event is sent.

Verbatim:
```
{
    "Door": [
        {
            "token": "Axis-00408c184bdb:1352121495.979065000",
            "Name": "Front Door",
            "Description": "Front door description",
            "AccessTime": "PT10S",
            "DefaultPriority": "",
            "OpenTooLongTime": "PT10S",
            "PreAlarmTime": "PT5S",
            "ExtendedAccessTime": "PT30S",
            "ExtendedOpenTooLongTime": "PT30S",
            "PriorityConfiguration": "Standard"
        }
    ]
}
```
Full SetDoor request verbatim:
```
{
    "axtdc:SetDoor": {
        "Door": [
            {
                "Name": "My Door",
                "Description": "My door description",
                "AccessTime": "PT7S",
                "DefaultPriority": "Normal",
                "OpenTooLongTime": "PT30S",
                "PreAlarmTime": "PT10S",
                "ExtendedAccessTime": "PT30S",
                "ExtendedOpenTooLongTime": "PT60S",
                "HeartbeatInterval": "PT600S",
                "token": "myDoor",
                "PriorityConfiguration": "myPriorityConfiguration"
            }
        ]
    }
}
```
- SetDoor: request `Door` [1..n]; response `Token` [0..n] (tokens of added/updated). Faults `env:Sender/ter:InvalidArgs`, `env:Receiver/ter:ActionNotSupported/ter:NotSupported`. Tokens may be user-chosen ("myDoor") or omitted/empty -> device generates (format seen: `Axis-<mac>:<epoch>.<nanos>`, e.g. `Axis-00408c184bdb:1352121495.979065000`).
- GetDoorList: `Limit`, `StartReference` -> `NextStartReference`, `Door` [0..n].
- GetDoor: `Token` [1..n] -> `Door` [0..n]; TooManyItems fault.
- RemoveDoor: `Token` [1..n] -> empty. Faults `env:Receiver/ter:ActionNotSupported/ter:NotSupported` ("Not allowed to remove the Door"), `env:Sender/ter:InvalidArgVal/ter:NotFound`.
- INFERRED JSON Set response: `{"Token":["myDoor"]}`. (Docs: "The response to a set request is a list of existing tokens.")

### 2.6 DoorConfiguration (hardware) - `axtdc:SetDoorConfiguration`, `GetDoorConfigurationList`, `GetDoorConfiguration`, `RemoveDoorConfiguration`, `GetDoorConfigurationInfo`
Fields: `token` (same token as the Door - "the token ... is the link between Door and DoorConfiguration"), `DeviceUUID` (door controller UUID; empty = local), `Configuration` (list of `{Name, Value}`, `axconf:Configuration`), `DoorScheduleConfiguration` (optional token).
`GetDoorConfigurationInfo` request `Token` [1][1] -> `ConfigurationInfo` [0..n] of `axconf:ConfigurationInfo` {`Name`, `Value`, `Enums` (suggested/allowed values), optional `Type` (e.g. xs:string, xs:boolean, xs:int), `DependOnName`, `DependOnValue`, `Description`}.
Faults: SetDoorConfiguration `env:Sender/ter:InvalidArgVal/ter:InvalidDoorConfigurationFault`; Remove NotFound.

Verbatim:
```
{
    "DoorConfiguration": [
        {
            "token": "Axis-00408c184bdb:1352121495.979065000",
            "DeviceUUID": "",
            "DoorScheduleConfiguration": "",
            "Configuration": [
                { "Name": "Lock.Type", "Value": "Standard" },
                { "Name": "DoorMonitor.ValueWhenOpen", "Value": "Input Open" },
                { "Name": "DoorMonitor.ValueWhenClosed", "Value": "Input Ground" }
            ]
        }
    ]
}
```
Note: the docs' "Step 4" example wraps it oddly - verbatim: `{"axtdc:SetDoorConfiguration": [ { "DoorConfiguration": [ { "token": ..., "DeviceUUID": "", "Configuration": [...] } ], "DoorScheduleConfiguration": "myDoorScheduleConfiguration" } ] }` (an array as the method value, and DoorScheduleConfiguration outside the DoorConfiguration item). This looks like a doc error; the normal shape (INFERRED) is `{"axtdc:SetDoorConfiguration":{"DoorConfiguration":[{...,"DoorScheduleConfiguration":"..."}]}}`. A lenient simulator could accept both.

Configuration Name/Value keys (table in docs; Valid values / Default):
| Name | Valid values | Default |
|---|---|---|
| `Lock.Type` | `None`, `Standard`, `Relay`, `RS485HD`, `RemoteIO`, `TCPIP` | `None` (None = virtual lock for testing) |
| `Lock.LockWhenDoorOpens` | `true`, `false` | `false` |
| `Lock.ValueWhenLocked` | `Gnd`, `Float`, `12V` | `Gnd` |
| `Lock.ValueWhenUnlocked` | `Gnd`, `Float`, `12V` | `12V` |
| `Lock.RelayStateWhenLocked` | `Open`, `Closed` | `Open` |
| `Lock.BoltOutTime` | ms | 700 |
| `Lock.BoltInTime` | ms | 700 |
| `Lock.LockMonitor.ValueWhenLocked` | `None`, `Input Open`, `Input 12V`, `Input Ground` | `None` |
| `Lock.LockMonitor.ValueWhenUnlocked` | same | `None` |
| `Lock.Hardware.Address` | string (Aperio 6-hex-digit; SmartIntego hex e.g. 0x200; RemoteIO `remote/<token>/<id>`) | |
| `Lock.Hardware.Id` | string (SmartIntego "phi") | |
| `Lock.Hub.Hardware.Address` | hex (SmartIntego gateway e.g. 0x100) | |
| `Lock.Protocol` | `AADP`, `SmartIntego` (example also shows `None`) | |
| `Lock.TCPIP.Address` | dotted decimal | |
| `Lock.TCPIP.Port` | decimal (2010 for SmartIntego) | |
| `DoubleLock.Type` | `None`, `Standard`, `Relay` | `None` |
| `DoubleLock.ValueWhenLocked` | `Gnd`, `Float`, `12V` | `Gnd` |
| `DoubleLock.ValueWhenUnlocked` | `Gnd`, `Float`, `12V` | `12V` |
| `DoubleLock.RelayStateWhenLocked` | `Open`, `Closed` | `Open` |
| `DoubleLock.BoltOutTime` / `DoubleLock.BoltInTime` | ms | 700 |
| `DoubleLock.LockMonitor.ValueWhenLocked` / `...ValueWhenUnlocked` | `None`, `Input Open`, `Input 12V`, `Input Ground` | `None` |
| `Door.Type` | `ElevatorFloor`, `Regular` | `Regular` |
| `DoorMonitor.Hardware.Address` | hex | |
| `DoorMonitor.Protocol` | `None`, `AADP`, `SmartIntego` | `None` |
| `DoorMonitor.Type` | `None`, `Standard`, `RS485HD`, `TCPIP` | `None` |
| `DoorMonitor.ValueWhenOpen` | `None`, `Input Open`, `Input Ground`, `Supervised Open`, `Supervised Ground` | `None` |
| `DoorMonitor.ValueWhenClosed` | same | `None` |
| `DoorMonitor.SupervisedCut` / `SupervisedShort` / `SupervisedHigh` / `SupervisedLow` | mV | (example values 2755 / 0 / 1855 / 740) |

Additional keys that appear in the full Step-4 example (with example values): `DebounceTime` "0", `Lock.LockWhenDoorOpensDelay` "3000", `UserData` "0". Full key list in that example (order verbatim): DoorMonitor.ValueWhenClosed=Input Ground, Lock.LockWhenDoorOpens=true, DebounceTime=0, Lock.BoltOutTime=0, DoorMonitor.ValueWhenOpen=Input Open, Lock.RelayStateWhenLocked=Open, Lock.BoltInTime=0, Lock.Type=Relay, DoubleLock.Type=None, Lock.LockWhenDoorOpensDelay=3000, Lock.Protocol=None, Lock.Hardware.Address=0, Lock.Hardware.Id=0, Lock.ValueWhenLocked=Gnd, Lock.ValueWhenUnlocked=12V, Lock.LockMonitor.ValueWhenLocked=None, Lock.LockMonitor.ValueWhenUnlocked=None, DoubleLock.ValueWhenLocked=Gnd, DoubleLock.ValueWhenUnlocked=12V, DoubleLock.RelayStateWhenLocked=Open, DoubleLock.BoltOutTime=700, DoubleLock.BoltInTime=700, DoubleLock.LockMonitor.ValueWhenLocked=None, DoubleLock.LockMonitor.ValueWhenUnlocked=None, DoorMonitor.SupervisedHigh=1855, DoorMonitor.SupervisedLow=740, DoorMonitor.SupervisedShort=0, DoorMonitor.SupervisedCut=2755, DoorMonitor.Type=None, DoorMonitor.Protocol=None, DoorMonitor.Hardware.Address=0, UserData=0, Lock.TCPIP.Port=0, Lock.TCPIP.Address="", Lock.Hub.Hardware.Address="", Door.Type=Regular.

Get responses include defaults for keys never set. Unspecified keys on Set get defaults.

### 2.7 Priorities - `axtdc:SetPriorityConfiguration`, `GetPriorityConfigurationList`, `GetPriorityConfiguration`, `RemovePriorityConfiguration`, `GetDoorPriorityState`
`PriorityConfiguration`: `token`, `Name`, `DefaultPriority`, `DoorPriorityAction` (ordered list, highest priority first) of `{PriorityLevel, DoorAction}`. `PriorityLevel` is just a name. Default config token `Standard` (one level).
`DoorActionType` enum: `NoAction`, `Release`, `LockDownRelease`, `LockOpenRelease`, `Lock`, `Unlock`, `Access`, `Block`, `LockDown`, `LockOpen`, `DoubleLock`.
Resolution: list processed highest first; first action != `Release` wins. If all released -> door falls back to `Locked`. A door action command with a PriorityLevel replaces that level's action; without one uses Door.DefaultPriority, else PriorityConfiguration.DefaultPriority.
Example level set in spec: Emergency=Release, Override=Release, Logic=Release, Schedule=Release, Normal=Release, Default=Lock.
`GetDoorPriorityState` request `Token` [1] -> `DoorPriorityAction` [0..n]; items also carry `Reason` (seen values `""`, `"Schedule"`, `"API"`).

Verbatim:
```
{
    "PriorityConfiguration": [
        {
            "DefaultPriority": "Medium",
            "DoorPriorityAction": [
                { "DoorAction": "Release", "PriorityLevel": "Highest" },
                { "DoorAction": "Release", "PriorityLevel": "High" },
                { "DoorAction": "Release", "PriorityLevel": "Medium" },
                { "DoorAction": "Release", "PriorityLevel": "Low" },
                { "DoorAction": "Lock", "PriorityLevel": "Lowest" }
            ],
            "Name": "Prio Configuration Name",
            "token": "Axis-00408c184bdb:1352207054.721964001"
        }
    ]
}
```
```
{
    "axtdc:GetDoorPriorityState": {
        "Token": "myDoor"
    }
}
```
Response:
```
{
    "DoorPriorityAction": [
        {
            "PriorityLevel": "High",
            "Reason": "API",
            "DoorAction": "Unlock"
        },
        {
            "PriorityLevel": "Normal",
            "Reason": "Schedule",
            "DoorAction": "Lock"
        }
    ]
}
```
(After ReleaseDoor High, the High item becomes `{"PriorityLevel":"High","Reason":"API","DoorAction":"Release"}`.)

### 2.8 Door schedules - `axtdc:SetDoorScheduleConfiguration`, `GetDoorScheduleConfigurationList`, `GetDoorScheduleConfiguration`, `RemoveDoorScheduleConfiguration`
`DoorScheduleConfiguration`: `token`, `Name`?, `Description`?, `DoorSchedule` list of `{PriorityLevel?, ScheduledState: [{ScheduleToken: [tokens], EnterAction: DoorActionType}]}`. ScheduledState list evaluated in order; first active schedule's EnterAction is applied at that PriorityLevel. If PriorityLevel empty, DoorSchedule must have exactly one element. No exit action - use overlapping schedules (e.g. `standard_always` + Lock as fallback). Enter action is also generated when the config is set and at controller restart. Linked to a door through `DoorConfiguration.DoorScheduleConfiguration`.
Verbatim:
```
{
    "axtdc:SetDoorScheduleConfiguration": {
        "DoorScheduleConfiguration": [
            {
                "DoorSchedule": [
                    {
                        "PriorityLevel": "Normal",
                        "ScheduledState": [
                            {
                                "ScheduleToken": ["standard_office_hours"],
                                "EnterAction": "Unlock"
                            },
                            {
                                "ScheduleToken": ["standard_always"],
                                "EnterAction": "Lock"
                            }
                        ]
                    }
                ],
                "token": "myDoorScheduleConfiguration",
                "Name": "My Door Schedule Configuration",
                "Description": "My door schedule configuration description"
            }
        ]
    }
}
```
Faults: Set `env:Sender/ter:InvalidArgVal/ter:InvalidDoorScheduleFault`; Remove NotFound.

### 2.9 Door events (from this page; topic list in section 8)
Door state event as returned by `axlog:FetchEvents` (verbatim):
```
{
    "rowid": 133,
    "token": "Axis-00408c184bdb:1383216924.148152000",
    "UUID": "5581ad80-95b0-11e0-b883-00408c184bdb",
    "UtcTime": "2013-10-31T10:55:24.067163Z",
    "KeyValues": [
        {
            "Key": "State",
            "Value": "Accessed",
            "Tags": ["property-state", "wstype:tdc:DoorMode", "onvif-data"]
        },
        {
            "Key": "DoorToken",
            "Value": "Axis-00408c184bdb:1352121495.979065000",
            "Tags": ["wstype:pt:ReferenceToken", "onvif-source"]
        },
        { "Key": "topic2", "Value": "DoorMode", "Tags": [] },
        { "Key": "topic1", "Value": "State" },
        { "Key": "topic0", "Value": "Door", "Tags": [] }
    ],
    "Tags": []
}
```
```
{
    "rowid": 372,
    "token": "Axis-00408c184c74:1383299532.611446000",
    "UUID": "5581ad80-95b0-11e0-b883-00408c184c74",
    "UtcTime": "2013-11-01T09:52:12.412969Z",
    "KeyValues": [
        {
            "Key": "State",
            "Value": "Open",
            "Tags": ["property-state", "wstype:tdc:DoorPhysicalState", "onvif-data"]
        },
        {
            "Key": "DoorToken",
            "Value": "Axis-00408c184bdb:1352121495.979065000",
            "Tags": ["wstype:pt:ReferenceToken", "onvif-source"]
        },
        { "Key": "topic2", "Value": "DoorPhysicalState", "Tags": [] },
        { "Key": "topic1", "Value": "State", "Tags": [] },
        { "Key": "topic0", "Value": "Door", "Tags": [] }
    ],
    "Tags": []
}
```
DoorMode event is stateful; initial state dispatched at start-up. Same for door monitor / lock monitor states.

## 3-5. Access control service (`tac` + `pacsaxis`), JSON endpoint `/vapix/pacs`

Source: https://developer.axis.com/vapix/physical-access-control/access-control-service/

IMPORTANT for the brief: on the A1210/A1610, credentials, access profiles, authentication profiles, access points, areas and the access controller ALL live in this one service at `/vapix/pacs`. There is no separate `axcred` / `/vapix/credential` or `/vapix/accesspolicy` endpoint in Axis's documentation. The ONVIF Credential service (`tcr`), Access Rules service (`tar`) and Schedule service (`tsc`) with `GetCredentials`/`CreateCredential`/`ModifyCredential` etc. are NOT documented for these controllers; the Axis equivalents are `pacsaxis:SetCredential` etc. and `axsch:` (see section 6). "Extended" credential variants (ONVIF `tcr:...WithExtension`) do not appear anywhere in the Axis docs.

Namespaces:
- `tac` = `http://www.onvif.org/ver10/accesscontrol/wsdl`
- `pacsaxis` = `http://www.axis.com/vapix/ws/pacs`
- `axudb` = `http://www.axis.com/vapix/ws/user` (users, also on `/vapix/pacs`, section 4)

Prefix per method (as written in docs; the guide table lists everything under `pacsaxis:`, the API sections specify):
- `tac:` GetServiceCapabilities, GetAccessPointInfoList, GetAccessPointInfo, GetAreaInfoList, GetAreaInfo, GetAccessPointState, EnableAccessPoint, DisableAccessPoint, ExternalAuthorization, GetAuthenticationProfileInfoList, GetAuthenticationProfileInfo, GetAuthenticationProfileList, GetAuthenticationProfile, SetAuthenticationProfile, RemoveAuthenticationProfile. (Guide examples use `"tac:DisableAccessPoint"`. But the guide also uses `"pacsaxis:SetAuthenticationProfile"` and `pacsaxis:GetAuthenticationProfileList` - so authentication-profile methods are callable under both prefixes. INFERRED: a simulator should accept both `tac:` and `pacsaxis:` for the AuthenticationProfile methods.)
- `pacsaxis:` AccessPoint (Get/GetList/Set/Remove), Area (GetList/Get/Set/Remove), AccessController(+Info)(+Configuration) (Get/GetList/Set/Remove), Credential*, AccessProfile*, GetStandardAttributeList, GetVendorAttributeList, VerifyRequest, RequestAccess, GetIdMatchOperators, GetRuleOperators, GetCredentialStatistics, GetMasterDBState, ReOpenMasterDB, ResetAntipassbackViolation, ResetAllAntipassbackViolations, GetAntipassbackDataList, SetAntipassbackData, EnableCredential, DisableCredential.

### 3.0 Common Get/Set/Remove patterns (all services)
- `Get<X>List` request: `Limit` xs:int [0..1] ("If not specified, less than one or higher than what the device supports, the number of items is determined by the device"), `StartReference` xs:string [0..1]. Response: `NextStartReference` xs:string [0..1] (absent = no more), `<X>` [0..n]. Fault `env:Sender/ter:InvalidArgVal/ter:InvalidStartReference`.
- `Get<X>` request: `Token` [1..n] (array). Unknown tokens ignored, no fault. "If left empty, no elements will be returned" (overview page) - but the guide table says "If the token list is empty, all data items are retrieved" (conflict; overview page statement is the more general rule). Response `<X>` [0..n]. >MaxLimit -> `env:Sender/ter:InvalidArgs/ter:TooManyItems`.
- `Set<X>` request: `<X>` [1..n]. Create if token empty or unknown, else replace whole item. Response: `Token` [0..n] (list of tokens) - EXCEPT SetCredential, whose response is documented as `Credential` [0..n] (list of Credential items) - INFERRED that the real device returns `{"Token":[...]}` like the others; doc may be wrong.
- `Remove<X>` request: `Token` [1..n]. Response empty. Fault `env:Sender/ter:InvalidArgVal/ter:NotFound`.
- Pseudo-code from docs:
```
StartRef = null
do {
  Response = GetAccessPointInfoList(StartReference = StartRef)
  if (Response.AccessPointInfo != null) {
    AllAccessPoints.Append(Response.AccessPointInfo)
  }
  StartRef = Response.NextStartReference
} while (StartRef != null)
```
- Field limits: `Name` up to 64 chars, `Description` up to 1024 chars (stated for DoorInfo, AccessPointInfo, AreaInfo, Area, AccessPoint).

### 3.1 tac:GetServiceCapabilities
`Capabilities` fields: `MaxLimit`, `DisableCredential`, `GetAccessPoint`, `SetAccessPoint`, `RemoveAccessPoint`, `GetArea`, `SetArea`, `RemoveArea`, `GetCredential`, `SetCredential`, `RemoveCredential`, `StandardAttributesSupported`, `VendorAttributesSupported` (booleans except MaxLimit). (Text also references `GetCredentialListSupported` and `RemoteService` capabilities in passing.)

### 3.2 AccessController (pacsaxis)
`AccessController` / `AccessControllerInfo`: `token`, `Name`, `Description`?, `AccessPoint` (list of AccessPoint tokens). Default token on a fresh device: `"Axis-<mac> AccessController"` (with a space).
`AccessControllerConfiguration`: `token` (same as controller), `DeviceUUID`, `Configuration` (Name/Value list).
Methods: GetAccessControllerInfoList, GetAccessControllerInfo, GetAccessControllerList, GetAccessController, SetAccessController, RemoveAccessController, GetAccessControllerConfigurationList, GetAccessControllerConfiguration, SetAccessControllerConfiguration, RemoveAccessControllerConfiguration.
After creating an AccessPoint you MUST add its token to the AccessController's `AccessPoint` list (SetAccessController).

Verbatim:
```
{
    "pacsaxis:GetAccessControllerList": {}
}
```
Response:
```
{
    "AccessController": [
        {
            "token": "Axis-00408c184bdb AccessController",
            "Name": "Axis-00408c184bdb AccessController",
            "Description": "",
            "AccessPoint": []
        }
    ]
}
```
```
{
    "AccessControllerConfiguration": [
        {
            "token": "Axis-00408c184bdb AccessController",
            "DeviceUUID": "5581ad80-95b0-11e0-b883-00408c184bdb",
            "Configuration": []
        }
    ]
}
```
```
{
    "pacsaxis:SetAccessController": {
        "AccessController": [
            {
                "token": "Axis-00408c184bdb AccessController",
                "Name": "Axis-00408c184bdb AccessController",
                "Description": "",
                "AccessPoint": ["Axis-00408c184bdb:1351589192.102223000"]
            }
        ]
    }
}
```

### 3.3 AccessPoint
`AccessPointInfo` (tac): `token`, `Name`, `Entity`, `Capabilities`, optional `Description`, `AreaFrom`, `AreaTo`, `EntityType` (default `tdc:Door`; examples also use `axtdc:Door`).
`AccessPointCapabilities`: `DisableAccessPoint`, `Duress`, `AnonymousAccess`, `AccessTaken`, `ExternalAuthorization` (booleans).
`AccessPoint` (pacsaxis, full config): `token`, `Name`, `Entity` (door token), `Enabled`, `IdPointDevice` (list of `{IdPoint, DeviceUUID?}`), `AuthenticationProfile` (list of tokens), `Attribute` (list of `{type?, Name, Value?}`), `ActionArgument` (list of `{Name, Value, type?}`), `Action` (string; typical `Access`, `AccessDoor`, `AccessDoorWithoutUnlock`; default `Access`; spec text says typically "AccessDoor"), optional `Description`, `AreaFrom`, `AreaTo`, `EntityType`, `DoorDeviceUUID` (empty = this device).
`AccessPointState` (tac:GetAccessPointState, `Token` [1]): `{Enabled}`. Fault NotFound.
`tac:EnableAccessPoint` / `tac:DisableAccessPoint`: `Token` [1], empty response. Faults NotFound, `env:Receiver/ter:ActionNotSupported/ter:NotSupported`.
`tac:ExternalAuthorization`: `AccessPointToken` [1], `CredentialToken` [0..1], `Reason` [0..1], `Decision` (`Granted` | `Denied`). Empty response.
Disabled AccessPoint -> access request returns `Unauthorized`.

AccessPoint Attribute names used by Axis: `Direction` (`in`/`out`), `Duress` (empty value; enables duress at this AP), `AntiPassbackMode` (`Logical`|`TimedLogical`, mandatory to enable APB), `AntiPassbackTimeout` (int seconds, default 0, only TimedLogical), `AntiPassbackEnforcementMode` (`Soft`|`Hard`, default `Hard`).

Verbatim:
```
{
    "pacsaxis:SetAccessPoint": {
        "AccessPoint": [
            {
                "token": "Axis-00408c184bdb:1351589192.102223000",
                "Name": "Entry 1",
                "Description": "Entry 1 main door",
                "AreaFrom": "",
                "AreaTo": "",
                "EntityType": "axtdc:Door",
                "Entity": "Door0",
                "DoorDeviceUUID": "",
                "Enabled": true,
                "IdPointDevice": [{ "IdPoint": "idpoint_token", "DeviceUUID": "" }],
                "AuthenticationProfile": ["CardOnly"],
                "Attribute": [],
                "ActionArgument": [],
                "Action": "Access"
            }
        ]
    }
}
```
AccessPointInfo example (overview page):
```
{
    "AccessPointInfo": [
        {
            "token": "Axis-00408c184bdb:1353665591.412364000",
            "Name": "Door",
            "Description": "",
            "AreaFrom": "",
            "AreaTo": "",
            "EntityType": "axtdc:Door",
            "Entity": "Axis-00408c184bdb:1353665586.846691000",
            "Capabilities": {
                "DisableAccessPoint": true,
                "AccessTaken": true
            }
        }
    ]
}
```
```
{
    "AccessPoint": [
        {
            "token": "Axis-00408c184bdb:1353665591.412364000",
            "Name": "Door",
            "Description": "",
            "AreaFrom": "",
            "AreaTo": "",
            "EntityType": "axtdc:Door",
            "Entity": "Axis-00408c184bdb:1353665586.846691000",
            "Enabled": true,
            "DoorDeviceUUID": "5581ad80-95b0-11e0-b883-00408c184bdb",
            "IdPointDevice": [
                {
                    "IdPoint": "Axis-00408c184bdb:1353665586.923475000",
                    "DeviceUUID": ""
                }
            ],
            "AuthenticationProfile": ["Axis-00408c184bdb:1353665638.159357000"],
            "Attribute": [
                {
                    "type": "",
                    "Name": "Direction",
                    "Value": "in"
                }
            ],
            "ActionArgument": [],
            "Action": "Access"
        }
    ]
}
```
```
{
    "tac:DisableAccessPoint": {
        "Token": "Axis-00408c184bdb:1351589192.102223000"
    }
}
```
Anti-passback AccessPoint example (verbatim):
```
{
    "pacsaxis:SetAccessPoint": {
        "AccessPoint": [
            {
                "token": "Main entrance in",
                "Name": "Main entrance in",
                "Description": "",
                "AreaFrom": "main building out",
                "AreaTo": "main building in",
                "EntityType": "tdc:Door",
                "Entity": "main entrance door",
                "Enabled": true,
                "DoorDeviceUUID": "5581ad80-95b0-11e0-b883-00408cffe4b3",
                "IdPointDevice": [
                    {
                        "IdPoint": "main entrance idpoint",
                        "DeviceUUID": ""
                    }
                ],
                "AuthenticationProfile": [],
                "Attribute": [
                    {
                        "type": "",
                        "Name": "Direction",
                        "Value": "in"
                    },
                    {
                        "type": "",
                        "Name": "AntiPassbackMode",
                        "Value": "TimedLogical"
                    },
                    {
                        "type": "",
                        "Name": "AntiPassbackTimeout",
                        "Value": "300"
                    },
                    {
                        "type": "",
                        "Name": "AntiPassbackEnforcementMode",
                        "Value": "Hard"
                    }
                ],
                "ActionArgument": [],
                "Action": "Access"
            }
        ]
    }
}
```
(Tokens with spaces and human names are accepted.)

### 3.4 Area
`AreaInfo` (tac): `token`, `Name`, `Description`?. `Area` (pacsaxis): `token`, `Name`, `Attribute`, `Description`?, `Extension`?. Methods `tac:GetAreaInfoList`, `tac:GetAreaInfo`, `pacsaxis:GetAreaList`, `GetArea`, `SetArea` (response `Token` list), `RemoveArea`. APB needs Areas created and referenced in AccessPoint `AreaFrom`/`AreaTo`.

### 3.5 Credential (pacsaxis) - section 3 of the brief
`Credential` fields:
- `token` (required)
- `UserToken` (optional; links to axudb User)
- `Description` (optional)
- `ValidFrom`, `ValidTo` (optional ISO 8601 `YYYY-MM-DDThh:mm:ssTZD`, empty string "" = no restriction)
- `Enabled` (bool)
- `Status` (string; normally a `CredentialStatusEnum`)
- `IdData` (list of `{Name, Value}`)
- `Attribute` (list of `{type?, Name, Value?}`)
- `AuthenticationProfile` (list of tokens; overrides AccessProfile and AccessPoint)
- `CredentialAccessProfile` (list of `{AccessProfile, ValidFrom?, ValidTo?}`)

NOTE: the Axis pacsaxis `CredentialAccessProfile` item uses key `AccessProfile` (NOT ONVIF's `AccessProfileToken`).

`CredentialInfo`: `token`, `Enabled`, `Status`, optional `UserToken`, `Description`, `ValidFrom`, `ValidTo`.

`CredentialStatusEnum`: `NotActivated`, `Enabled`, `Disabled`, `LockedOut`, `Lost`, `Stolen`, `Damaged`, `Destroyed`, `Inactive`, `MaxDays`, `MaxUses`, `Expired`. "Enabled ... is the only state in which access can be granted." Used as `Reason` in some events.

IdData names used in the docs: `Card` (raw card data, e.g. "00007352" in a not-found event), `CardNr` (card number; the ONLY IdData name checked for uniqueness across credentials on Set), `PIN`, `DuressPIN`, `REX` (value `Active`), `FacilityCode` (INFERRED from Wiegand formats in IdPoint section; check sec 7), `LPN` (license plate, remote activities). IdData Name is unique per credential (no two `PIN`).

Credential Attribute names used: `ExtendedAccessTime` (no value; use door's ExtendedAccessTime), `AccessTime`, `OpenTooLongTime`, `PreAlarmTime` (values `PTXS`), `AntiPassbackOverride` (`True`/`False`, default False). Standard attributes listed: `ExtendedTime`, `ExtendedTimeFlag`, `IdFactorOverride=string` (form `IdDataName=RuleOperatorName`, e.g. `IdFactorOverride=PIN=DontCare`), `EscortRequired`, `EscortNotRequired`, `Escort`.

Methods:
| Method | Request | Response | Access class |
|---|---|---|---|
| `pacsaxis:GetCredentialInfoList` | Limit, StartReference | NextStartReference, `CredentialInfo` [] | READ_SYSTEM |
| `pacsaxis:GetCredentialInfo` | `Token` [] | `CredentialInfo` [] | READ_SYSTEM |
| `pacsaxis:GetCredentialList` | Limit, StartReference | NextStartReference, documented as `CredentialInfo` [] (INFERRED real key is `Credential` []) | READ_SYSTEM_SECRET |
| `pacsaxis:GetCredential` | `Token` [] | `Credential` [] | READ_SYSTEM_SENSITIVE |
| `pacsaxis:SetCredential` | `Credential` [1..n] | documented `Credential` []; INFERRED `Token` [] | WRITE_SYSTEM; fault `env:Sender/ter:InvalidArgVal/ter:InvalidCredentialFault` |
| `pacsaxis:RemoveCredential` | `Token` [] | empty | WRITE_SYSTEM |
| `pacsaxis:EnableCredential` | `Token` [1] | empty | ACTUATE |
| `pacsaxis:DisableCredential` | `Token` [1], `Status` [0..1] (CredentialStatusEnum, default "Disabled") | empty | ACTUATE |
| `pacsaxis:GetCredentialStatistics` | empty | `CredentialStatistics` {`NumberOfCredentials`, `NumberOfDisabledCredentials`} | |
Disable/Enable flips `Enabled` and `Status` on the stored credential (`Enabled:false,Status:"Disabled"`; EnableCredential -> Status defaults "Enabled").

Verbatim:
```
{
    "pacsaxis:SetCredential": {
        "Credential": [
            {
                "token": "Axis-00408c184bdb:1351593020.016190000",
                "UserToken": "user_token1",
                "Description": "Credential description",
                "ValidFrom": "1997-01-01T00:00:00Z",
                "ValidTo": "2038-01-01T00:00:00Z",
                "Enabled": true,
                "Status": "Enabled",
                "IdData": [
                    {
                        "Name": "Card",
                        "Value": "12345678"
                    },
                    {
                        "Name": "PIN",
                        "Value": "1234"
                    }
                ],
                "Attribute": [],
                "AuthenticationProfile": [],
                "CredentialAccessProfile": [
                    {
                        "ValidFrom": "1997-01-01T00:00:00Z",
                        "ValidTo": "2038-01-01T00:00:00Z",
                        "AccessProfile": "Axis-00408c184bdb:1351591416.539133000"
                    }
                ]
            }
        ]
    }
}
```
```
{
    "pacsaxis:DisableCredential": {
        "Token": "Axis-00408c184bdb:1351593020.016190000",
        "Status": "Disabled"
    }
}
```
```
{
    "CredentialStatistics": {
        "NumberOfCredentials": 1000,
        "NumberOfDisabledCredentials": 5
    }
}
```
Attribute examples: `"Attribute": [ { "Name": "ExtendedAccessTime" } ]` and `"Attribute": [ { "type": "", "Name": "AntiPassbackOverride", "Value": "True" } ]`. Duress: add `{ "Name": "DuressPIN", "Value": "1235" }` to IdData.

### 3.6 AuthenticationProfile
`AuthenticationProfile`: `token`, `Name`, `Description`, `Schedule` (list of schedule tokens; when the profile applies), `IdFactor` (ordered list of `{IdDataName, IdMatchOperatorName, OperatorValue}`), `Extension`?. `AuthenticationProfileInfo`: token, Name, Description.
IdMatchOperators: mandated `IdDataEqual` (request[IdDataName] == credential IdData[IdDataName]), `OperatorValueEqual` (request[IdDataName] == OperatorValue; REX with "Active"), `RemoteValidationEvent` (sends `AccessControl/Request/ExternalConfirmation` event); Axis adds `IdDataEqualToField` (OperatorValue names the credential IdData field to compare against, e.g. `DuressPIN`). Recommended `RemoteValidationRequest`; reserved `MatchPhoto`, `MatchFingerprint`, `MatchIris`, `MatchVoice`, `VerifySignature`. `pacsaxis:GetIdMatchOperators` -> `IdMatchOperator` [] of `{Name, Description}`.
RuleOperators (`pacsaxis:GetRuleOperators` -> `RuleOperator` [] `{Name, Description}`): mandated `Authenticate`, `RequestEqual` (described as `RequestActionEqual`), `OperatorValueEqual`, `RemoteValidationEvent`; recommended `CredentialAttributeEqual`, `AccessProfileAttributeEqual`, `RemoteValidationRequest`.
Factory defaults (verbatim, from `pacsaxis:GetAuthenticationProfileList`; spec text calls the third one `CardPlusPIN` but the actual token is `CardPlusPin`):
```
{
    "AuthenticationProfile": [
        {
            "token": "CardOnly",
            "Name": "CardOnly",
            "Description": "Card only",
            "IdFactor": [
                {
                    "IdDataName": "Card",
                    "IdMatchOperatorName": "IdDataEqual",
                    "OperatorValue": ""
                }
            ],
            "Schedule": ["standard_always"]
        },
        {
            "token": "PINOnly",
            "Name": "PINOnly",
            "Description": "PIN only",
            "IdFactor": [
                {
                    "IdDataName": "PIN",
                    "IdMatchOperatorName": "IdDataEqual",
                    "OperatorValue": ""
                }
            ],
            "Schedule": ["standard_always"]
        },
        {
            "token": "CardPlusPin",
            "Name": "CardPlusPin",
            "Description": "Card + PIN",
            "IdFactor": [
                {
                    "IdDataName": "Card",
                    "IdMatchOperatorName": "IdDataEqual",
                    "OperatorValue": ""
                },
                {
                    "IdDataName": "PIN",
                    "IdMatchOperatorName": "IdDataEqual",
                    "OperatorValue": ""
                }
            ],
            "Schedule": ["standard_always"]
        },
        {
            "token": "REXOnly",
            "Name": "REXOnly",
            "Description": "REX only",
            "IdFactor": [
                {
                    "IdDataName": "REX",
                    "IdMatchOperatorName": "OperatorValueEqual",
                    "OperatorValue": "Active"
                }
            ],
            "Schedule": ["standard_always"]
        }
    ]
}
```
Duress profile:
```
            {
                "token": "CardPlusDuressPIN",
                "Name": "CardPlusDuressPIN",
                "Description": "Card + DuressPIN",
                "IdFactor": [
                    {
                        "IdDataName": "Card",
                        "IdMatchOperatorName": "IdDataEqual",
                        "OperatorValue": ""
                    },
                    {
                        "IdDataName": "PIN",
                        "IdMatchOperatorName": "IdDataEqualToField",
                        "OperatorValue": "DuressPIN"
                    }
                ],
                "Schedule": ["office_hours"]
            }
```
Semantics: multiple IdFactors must ALL be supplied, in the same order; if fewer supplied, the controller asks for more (reader LEDs) or denies if no credential matches the first factor. Changing AuthenticationProfiles triggers an internal rebuild during which access requests are not handled (can take minutes with many credentials). Precedence of AuthenticationProfile override, high to low: Credential > AccessProfile > AccessPoint. Mixed operators in a request: `IdDataEqual` chosen over `OperatorValueEqual`. `tac:RemoveAuthenticationProfile` `Token` is [0..n] (empty list removes nothing).

### 3.7 AccessProfile and AccessPolicy
`AccessProfile`: `token`, `Name`, `Description`, `Schedule` (list), `AuthenticationProfile` (list; overrides AccessPoint, typically empty), `Attribute` (list; e.g. `Duress`), `AccessPolicy` (list), `Enabled`, optional `ValidFrom`, `ValidTo`. `AccessProfileInfo`: token, Name, Description.
`AccessPolicy`: `AccessPoint` (single token string), `AuthorizationProfile` (list; placeholder), `Attribute` (list), `Schedule` (list of schedule tokens).
`AuthorizationProfile` (future placeholder): token, Name, Description, Schedule, Rule [] `{Name, OperatorValue, OperatorName}`, Extension.
Methods: `pacsaxis:GetAccessProfileInfoList`, `GetAccessProfileInfo`, `GetAccessProfileList`, `GetAccessProfile`, `SetAccessProfile` (-> `Token` []; fault `ter:InvalidAccessProfileFault`), `RemoveAccessProfile`. No Enable/Disable methods for AccessProfile: set `Enabled:false`.
Disabled or out-of-ValidFrom/To AccessProfile -> access request Reason `InvalidAccessProfile`.
Schedule list evaluation (for AuthenticationProfile and AccessProfile Schedule lists): exception schedules take precedence (one active exception -> list inactive); otherwise at least one regular schedule must be active.
Verbatim:
```
{
    "pacsaxis:SetAccessProfile": {
        "AccessProfile": [
            {
                "token": "Axis-00408c184bdb:1351591416.539133000",
                "Name": "AccessProfile1",
                "Description": "AccessProfile description",
                "Enabled": true,
                "Schedule": ["standard_always"],
                "ValidFrom": "1997-01-01T00:00:00Z",
                "ValidTo": "2038-01-01T00:00:00Z",
                "AuthenticationProfile": [],
                "AccessPolicy": [
                    {
                        "AccessPoint": "Axis-00408c184bdb:1351589192.102223000",
                        "AuthorizationProfile": [],
                        "Attribute": [],
                        "Schedule": ["standard_always"]
                    }
                ]
            }
        ]
    }
}
```
Per-door schedule example:
```
            "Schedule": ["standard_always", "not_public_holidays"],
            "AuthenticationProfile": [],
            "Attribute": [],
            "AccessPolicy": [
                {
                    "AccessPoint": "main-door",
                    "AuthorizationProfile": [],
                    "Attribute": [],
                    "Schedule": ["office_hours"]
                },
                {
                    "AccessPoint": "employee-door",
                    "AuthorizationProfile": [],
                    "Attribute": [],
                    "Schedule": ["standard_always"]
                }
            ]
```

### 3.8 RequestAccess / VerifyRequest (pacsaxis)
Request: `Token` [1] (AccessController token), `IdData` [] (`{Name, Value}`), `SourceToken` [0..1] (IdPoint token), `TargetToken` [0..1] (door token; may be empty -> door of the AccessPoint where the IdPoint resides), `Action` [0..1] (default `Access`; must match AccessPoint.Action), `Environment` [] (`{Name, Value}`). Response: `AccessGranted` xs:boolean, `Reason` xs:string. Fault NotFound (AccessController). VerifyRequest = same decision, no door/IdPoint side effects (and INFERRED: no events).
Verbatim:
```
{
    "pacsaxis:RequestAccess": {
        "Action": "Access",
        "IdData": [
            {
                "Name": "Card",
                "Value": "12345678"
            }
        ],
        "SourceToken": "idp_token",
        "TargetToken": "door_token",
        "Token": "Axis-00408c184bdb AccessController"
    }
}
```
```
{
    "AccessGranted": true,
    "Reason": "Granted"
}
```
```
{
    "AccessGranted": false,
    "Reason": "InvalidCredential"
}
```
Reason values seen in docs: `Granted`, `InvalidCredential` (unknown card/PIN), `CredentialNotEnabled` (disabled credential), `Unauthorized` (disabled access point), `InvalidAccessProfile` (disabled/expired profile), `CredentialNotActive` (before ValidFrom), `CredentialExpired` (after ValidTo), `AntiPassbackViolation`. INFERRED additional ONVIF reasons a simulator may use: `CredentialNotFound`, `NotPermittedAtThisTime` (schedule inactive) - not documented by Axis.

Event sequence for a request (see section 8): granted -> `AccessControl/AccessGranted/Credential` (or `/Anonymous`), then `AccessControl/AccessTaken/Credential` or `AccessControl/AccessNotTaken/Credential`. Denied -> `AccessControl/Denied/Credential` (with Reason) or `AccessControl/Denied/CredentialNotFound/Card` (unknown card; carries `Card` and `CardNr`, no CredentialToken). If multiple credentials match (shared PIN), `CredentialToken` and `CredentialHolderName` are empty.

### 3.9 Anti-passback (pacsaxis)
- `ResetAntipassbackViolation`: `CredentialToken` [1]; empty response.
- `ResetAllAntipassbackViolations`: empty / empty.
- `GetAntipassbackDataList`: (Limit/StartReference INFERRED) -> `AntipassbackData` [].
- `SetAntipassbackData`: `AntipassbackData` [1..n]; empty response.
- `AntipassbackData`: `CredentialToken`, `PassOkThreshold` (xs:long; "in microseconds" in guide vs "in seconds" in API - doc conflict), `CurrentArea`, `ByTime` (false=Logical, true=TimedLogical), `Violation`.
```
{
    "pacsaxis:SetAntipassbackData": {
        "AntipassbackData": [
            {
                "CredentialToken": "credential token",
                "CurrentArea": "main building in",
                "ByTime": false,
                "PassOkThreshold": 0,
                "Violation": ""
            }
        ]
    }
}
```
APB requires a door monitor. Violation -> `AccessControl/Denied/Credential` Reason `AntiPassbackViolation` + `Credential/State/ApbViolation` event (keys CredentialToken (source), CredentialHolderName, Device Source, Reason, ApbViolation '1'/'0', ClientUpdated '0'/'1'). Cleanup timer every 10 minutes for TimedLogical.

### 3.10 Misc pacsaxis
- `GetStandardAttributeList` / `GetVendorAttributeList`: empty request -> `Attribute` [].
- `GetMasterDBState` / `ReOpenMasterDB`: -> `NbrTotalPages`, `NbrFreePages`, `SizeOnDisk` (xs:int).
- `MatchOperator` enum: `Equal`, `NotEqual`, `Subset`, `Intersection`; `MatchRule` {`Field`, `Operator`} (no documented method uses it).

## 4. User service (`axudb`), JSON endpoint `/vapix/pacs`

Source: https://developer.axis.com/vapix/physical-access-control/user-service/
Namespace `axudb` = `http://www.axis.com/vapix/ws/user`. "No events are available from this service." Users are NOT used by the door controller for decisions; pure storage for client display (e.g. credential holder name). Link: `Credential.UserToken` = `User.token`.

Data:
- `User`: `token`, `Name`, `Attribute` (list `{type?, Name, Value?}`), optional `Description`, `Extension`.
- `UserInfo`: `token`, `Name`, optional `Description`.
- `ServiceCapabilities`: `MaxLimit`.

Methods (`axudb:` prefix):
| Method | Request | Response | Access class |
|---|---|---|---|
| `GetServiceCapabilities` | empty | `Capabilities` {MaxLimit} | PRE_AUTH |
| `GetUserInfoList` | `Limit`, `StartReference` | `NextStartReference`, `UserInfo` [] | READ_SYSTEM |
| `GetUserInfo` | `Token` [1..n] | (doc says "shall be empty"; INFERRED `UserInfo` []) | READ_SYSTEM |
| `GetUserList` | `Limit`, `StartReference` | (doc says "shall be empty"; INFERRED `NextStartReference`, `User` []) | READ_SYSTEM_SENSITIVE |
| `GetUser` | `Token` [0..n] | `User` [] | READ_SYSTEM_SENSITIVE |
| `SetUser` | `User` [1..n] | `Token` [] | WRITE_SYSTEM; faults `env:Sender/ter:InvalidArgs`, `env:Receiver/ter:ActionNotSupported/ter:NotAllowed` |
| `RemoveUser` | `Token` [1..n] | empty | WRITE_SYSTEM; `env:Sender/ter:InvalidArgVal/ter:NotFound` |
| `GetUserInfoByCredentialToken` | `CredentialToken` [1] | `UserInfo` [] | READ_SYSTEM_SENSITIVE; NotFound |

Verbatim:
```
{
    "axudb:SetUser": {
        "User": [
            {
                "token": "user_token1",
                "Name": "Name, User",
                "Description": "User description",
                "Attribute": [
                    { "type": "string", "Name": "First name", "Value": "User" },
                    { "type": "string", "Name": "Last name", "Value": "Name" }
                ]
            }
        ]
    }
}
```
```
{
    "axudb:GetUserInfoByCredentialToken": {
        "CredentialToken": "Axis-00408c184bdb:1351593020.016190000"
    }
}
```
```
{
    "UserInfo": [
        {
            "token": "user_token1",
            "Name": "Name, User",
            "Description": "User description"
        }
    ]
}
```
(Entry Manager user/credential conventions: see section 10.)

## 6. Schedule service (`axsch`), JSON endpoint `/vapix/schedule`

Source: https://developer.axis.com/vapix/physical-access-control/schedule-service/
Namespace `axsch` = `http://www.axis.com/vapix/ws/schedule`. NOT ONVIF `tsc`: there is no `SpecialDays` / `SpecialDayGroup` and no `GetScheduleState`. Holidays/exceptions are expressed with `ExceptionScheduleDefinition` (a second iCalendar text on the same Schedule) or by a separate exceptions-only schedule.

Data:
- `Schedule`: `token`, `Name`, `Description`, `ScheduleDefinition` (iCalendar text), `Attribute` (list), `ExceptionScheduleDefinition` (iCalendar text; may be `null` or `""`).
- `ScheduleInfo`: `token`, `Name`, `Description`.
- `ScheduleStatus`: `Token`, `Active`, `Exception` (note capital-T `Token` here).
- `ServiceCapabilities`: `Component` (list of iCalendar components supported, VEVENT required), `SetSchedule`, `GetSchedule`, `RemoveSchedule`, `ScheduleActive`, `EventSupport`.
- `InitializationDone`: `token` (device UUID) - "a schedule service has finished initializing" (INFERRED: emitted as an event at boot).

Methods (`axsch:`):
| Method | Request | Response | Access |
|---|---|---|---|
| `GetServiceCapabilities` | empty | `Capabilities` | PRE_AUTH |
| `GetScheduleInfoList` | `Limit`, `StartReference` | `NextStartReference`, `ScheduleInfo` [] | READ_SYSTEM |
| `GetScheduleInfo` | `Token` [1..n] | `ScheduleInfo` [] | READ_SYSTEM |
| `GetScheduleList` | `Limit`, `StartReference` | `NextStartReference`, `Schedule` [] | READ_SYSTEM_SENSITIVE |
| `GetSchedule` | `Token` [1..n] | `Schedule` [] | READ_SYSTEM_SENSITIVE |
| `SetSchedule` | `Schedule` [1..n] (empty token -> generated) | `Token` [] | WRITE_SYSTEM; `env:Sender/ter:InvalidArgVal/ter:InvalidScheduleFault` |
| `RemoveSchedule` | `Token` [1..n] | empty | WRITE_SYSTEM; NotFound. Removing an active interval schedule should emit Schedule/Interval with Active=false, Exception=false |
| `ScheduleActive` | `Token` [1..n], `LocalTime` xs:dateTime [0..1], `UtcTime` xs:dateTime [0..1] | `Active` bool, `Exception` bool | ACTUATE; NotFound |
| `ScheduleStatusReport` | `Token` [1..n] (example sends `{}` -> all schedules) | `Status` [] of ScheduleStatus | ACTUATE |

Aggregation rule: `IF (Any schedule is active) AND NOT (Any exception schedule is active)`. Truth table: Def active & Exc inactive -> active; any exception active -> inactive (Active=false, Exception=true).

Default schedules on device: `standard_always` (always active; Entry Manager depends on it - do not modify), `standard_office_hours`, `standard_weekends` (seen in ScheduleStatusReport example). INFERRED: their definitions resemble the "Office hours" and "Weekends" examples below.

Interval vs pulse: `DTEND` present in VEVENT -> interval schedule (events on active/inactive change, topic `tns1:Schedule/tnsaxis:Interval`); no DTEND -> pulse schedule (event when it fires, `tns1:Schedule/tnsaxis:Pulse`). (API section writes `tns1:Schedule/Interval` and `tns1:Schedule/Pulse`; topic table writes with `tnsaxis:`.)

iCalendar subset ("RFC5545 syntax flavor"): Only local time; no UTC; no VTIMEZONE; no VALARM; `DTSTART;VALUE=DATE` -> 24h interval; overlapping RDATE/RRULE instances in one VEVENT undefined. Supported RRULE: `HOURLY`, `MINUTELY`, `SECONDLY`, `DAILY`, `WEEKLY`, `WEEKLY;BYDAY`, `MONTHLY`, `MONTHLY;BYMONTHDAY`, `YEARLY`, `YEARLY;BYMONTH`, plus `INTERVAL`, `COUNT`, `UNTIL`. RDATE with DATE, DATE-TIME, PERIOD. UID/VERSION/DTSTAMP/SUMMARY/DESCRIPTION accepted, not interpreted. Both `\n` and `\r\n` line endings used in examples. Entry Manager uses minute granularity, weekly/yearly intervals <=24h, UNTIL as last second of a day (e.g. `UNTIL=20121031T225959`).

Verbatim:
```
{
    "axsch:SetSchedule": {
        "Schedule": [
            {
                "ExceptionScheduleDefinition": null,
                "Attribute": [],
                "ScheduleDefinition": "BEGIN:VCALENDAR\nBEGIN:VEVENT\nDTSTART:20120312T080000\nDTEND:20120312T170000\nRRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR\nEND:VEVENT\nEND:VCALENDAR\n",
                "token": "",
                "Description": "Desc1",
                "Name": "Name1"
            }
        ]
    }
}
```
```
{
    "axsch:SetSchedule": {
        "Schedule": [
            {
                "Name": "Lunch",
                "Description": "",
                "ScheduleDefinition": "BEGIN:VCALENDAR\r\nPRODID:\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nSUMMARY:Lunch\r\nDTSTART:20000103T110000\r\nDTEND:20000103T120000\r\nRRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR\r\nDTSTAMP:20121019T123359\r\nUID:c5d62887d9a269ab\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n",
                "ExceptionScheduleDefinition": "",
                "Attribute": []
            }
        ]
    }
}
```
Empty ("Never") schedule: `"ScheduleDefinition": "BEGIN:VCALENDAR\r\nPRODID:\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n"`.
Yearly: `...SUMMARY:December 24\r\nDTSTART:20001224T000000\r\nDTEND:20001225T000000\r\nRRULE:FREQ=YEARLY\r\n...`.
End date: `RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR,SA,SU;UNTIL=20121031T225959`.
```
{
    "axsch:ScheduleActive": {
        "Token": ["standard_office_hours", "standard_weekends"],
        "UtcTime": null,
        "LocalTime": null
    }
}
```
```
{
    "Active": true,
    "Exception": false
}
```
```
{
    "axsch:ScheduleStatusReport": {}
}
```
```
{
    "Status": [
        {
            "Token": "standard_weekends",
            "Active": false,
            "Exception": false
        },
        {
            "Token": "standard_office_hours",
            "Active": true,
            "Exception": false
        },
        {
            "Token": "standard_always",
            "Active": true,
            "Exception": false
        }
    ]
}
```
Example definitions (verbatim):
```
BEGIN:VCALENDAR
BEGIN:VEVENT
SUMMARY:Office Hours
DTSTART:19700101T090000
DTEND:19700101T170000
RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR
END:VEVENT
END:VCALENDAR
```
```
BEGIN:VCALENDAR
BEGIN:VEVENT
DTSTART:19700104T000000
DTEND:19700105T000000
RRULE:FREQ=WEEKLY;BYDAY=SA,SU
END:VEVENT
BEGIN:VEVENT
DTSTART:19700102T170000
DTEND:19700103T000000
RRULE:FREQ=WEEKLY;BYDAY=FR
END:VEVENT
END:VCALENDAR
```
Others in docs: one-shot interval (DTSTART+DTEND, no RRULE); one-shot pulse (DTSTART only); `RDATE;VALUE=DATE:20120508,20120604,...`; `RDATE;VALUE=DATE-TIME: 20120131T153000,...` mixed with RRULE; `RRULE:FREQ=DAILY;INTERVAL=4;COUNT=3`; `RRULE:FREQ=SECONDLY;INTERVAL=15;UNTIL=20000101T120045`. (Several examples end with `END:VCALENDAR;` - doc typo.)

## 7. IdPoint service (`axtid`), JSON endpoint `/vapix/idpoint`

Source: https://developer.axis.com/vapix/physical-access-control/idpoint-service/ and .../peripherals/ (remote readers, Aperio, SmartIntego)
Namespace `axtid` = `http://www.axis.com/vapix/ws/IdPoint`. (Text once writes `tid:SetIdPoint`; examples use `axtid:`.)

Concept: an IdPoint = reader/keypad/biometric/REX. Two structures share one token: `IdPoint` (abstract) and `IdPointConfiguration` (hardware). Service does nothing until both exist. Defaults: card data as IdData `Card` (lowercase hex string), keypad as `PIN` (string, may be alphanumeric), REX as `REX` = `Active`.

### 7.1 Data structures
- `IdPointInfo`: `token`, `Name`, `Location`, `Area`, `Capabilities`, `Description`?.
- `IdPointCapabilities`: `Configurable`, `SupportCard`, `SupportPIN`, `SupportREX`, `SupportBiometric` (bool), `SupportedMessageTypes` (list of mime types, e.g. text/plain), `SupportedGraphicsTypes` (e.g. image/jpeg, image/png), `SupportedAudioTypes` (e.g. audio/basic, audio/mp3), `AdditionalCapabilities` (list).
- `IdPoint`: `token`, `Name`, `Location`, `Area`, `Timeout` (duration between user interactions, e.g. "PT3S"), `HeartbeatInterval` (duration, 0 = none, e.g. "PT10M"), optional `Description`, `Action` (default "Access"), `MinPINSize` (int), `MaxPINSize` (int), `EndOfPIN` (string, e.g. "#").
- `IdPointConfiguration`: `token`, `DeviceUUID` (empty -> filled with receiving device's UUID), `IdDataConfiguration` (list of IdDataConfiguration tokens; examples send `[""]` or `[]`), `Configuration` (Name/Value list). Partial Set on existing token replaces only supplied params; on new token missing params get defaults (first value in each list).
- `IdDataConfiguration`: `token`, `Name`, `Description`, `InputBitlength` (int), `IdDataFieldMap` (list of `{Name, Map, Encoding}`).
- `IdDataEncoding` enum (API): `Other`, `BinLE2hex`, `BinBE2hex`, `Bin2Base64`, `Bin2String`, `BinLEBCD2String`, `BinBEBCD2String`, `BinLE2Int`, `BinBE2Int`, `BinLEIBO2hex`, `BinBEIBO2hex`, `BinIBO2Base64`, `BinIBO2String`, `BinLEIBO2Int`, `BinBEIBO2Int`. Length limit 64 bit for *2Int.
- Map syntax: comma-separated chunks; `N` (bit N; first bit = bit 1 = first received on Wiegand), `M-N` (bit range), `bBBB`/`0bBBB` constant binary, `xHHH`/`0xHHH` constant hex (MSB first), `sSSSS` constant string (`,0x2c,` for comma). Chunks concatenated.
- `IdPointFeedback` enum: `Other`, `Idle`, `DoorLocked`, `DoorUnlocked`, `DoorOpenTooLong`, `DoorPreAlarmWarning`, `RequirePIN`, `RequireCard`, `Processing`, `InvalidCredential`, `AccessGranted`, `AccessDenied`, `Ok`, `Fault`, `Warning`, `Alarm`, `Custom`.
- `SecureChannel` enum: `Unknown`, `ConnectionLost`, `ConnectionEstablished`, `NotSupported`, `NoKey`. `SecureChannelStatus` {`Active` bool, `Reason`}.
- Whitelist entry states: `Active`, `Invalid`, `PendingAdd`, `PendingRemove` (IdPointWhiteList structure fields not documented).
- `Activity`: `Type` (`REX` | `Card` | `PIN`), `Params` (list of `{Name, Value}`; mandatory for Card and PIN, NOT allowed for REX; PIN type needs a param named `PIN`).
- `ServiceCapabilities`: `SetIdPoint` (bool).

### 7.2 Methods (`axtid:`)
| Method | Request | Response | Notes |
|---|---|---|---|
| GetServiceCapabilities | empty | `Capabilities` | PRE_AUTH |
| GetIdPointInfoList | Limit, StartReference | NextStartReference, `IdPointInfo` [] | |
| GetIdPointInfo | `Token` [] | `IdPointInfo` [] | |
| GetIdPointList | Limit, StartReference | documented as `IdPointInfo` []; INFERRED real key `IdPoint` [] | |
| GetIdPoint | `Token` [] | `IdPoint` [] | |
| SetIdPoint | `IdPoint` [] | `Token` [] | faults `env:Receiver/ter:ActionNotSupported/ter:NotSupported`, `env:Sender/ter:InvalidArgs` |
| RemoveIdPoint | `Token` [] | empty | NotFound / NotSupported |
| GetIdPointCapabilities | `Token` [1] | `IdPointCapabilities` [1] | |
| FeedbackMessage | `Token`, `Profile` (IdPointFeedback), `OtherProfile`?, `Message`?, `Graphics`? (tt:BinaryData), `Audio`? | empty | ACTUATE |
| GetFeedbackMessage | `Token` | `Profile` | |
| GetIdPointConfigurationList | Limit, StartReference | NextStartReference, `IdPointConfiguration` [] | |
| GetIdPointConfiguration | `Token` [] | `IdPointConfiguration` [] | |
| SetIdPointConfiguration | `IdPointConfiguration` [] | `Token` [] | fault `ter:InvalidIdPointConfigurationFault` |
| RemoveIdPointConfiguration | `Token` [] | empty | |
| GetIdPointConfigurationInfo | `Token` [1] | `ConfigurationInfo` [] (axconf) | |
| GetLastCredential | `Token` [1] | `IdData` [] | fault `env:Sender/ter:InvalidArgVal/ter:ConfigurationNotFound` |
| GetIdDataConfigurationList | Limit, StartReference | documented as `IdPointConfiguration` []; INFERRED `IdDataConfiguration` [] | |
| GetIdDataConfiguration | `Token` [] | `IdDataConfiguration` [] | |
| SetIdDataConfiguration | `IdDataConfiguration` [] | `Token` [] | fault `ter:InvalidConfigurationFault` |
| RemoveIdDataConfiguration | `Token` [] | empty | |
| GetSecureChannelStatus | `Token` [1] | `SecureChannelStatus` | |
| GetIdPointWhiteList | `Token` [] | `IdPointWhiteList` [] | |
| GetIdPointWhiteListList | Limit, StartReference | `IdPointWhiteList` [] | |
| IndicateRemoteActivities | `Token` [1], `Description` [0..1], `Activities` [1..n], `Attributes` [] (unused) | empty -> JSON `{}` (documented verbatim) | ACTUATE; NotFound |

### 7.3 Configuration Name/Value keys (IdPointConfiguration)
| Name | Valid values |
|---|---|
| `IdPoint.Reader.Type` | `None`, `Wiegand`, `RS-485FD`, `RS-485HD`, `TCPIP` |
| `IdPoint.RS-485HD.Protocol` | `None`, `AADP`, `OSDP`, `HADP` |
| `IdPoint.TCPIP.Protocol` | `SmartIntego` |
| `IdPoint.TCPIP.Address` / `IdPoint.TCPIP.Port` | dotted decimal / decimal (2010 SmartIntego) |
| `IdPoint.LED.Type` | `None`, `SingleLED`, `DualLED` |
| `IdPoint.LED.ActiveLevel` | `ActiveLow`, `ActiveHigh` |
| `IdPoint.Beeper.Type` | `None`, `ActiveLow`, `ActiveHigh` |
| `IdPoint.Tampering.Type` | `None`, `ActiveLow`, `ActiveHigh`, `SupervisedActiveLow`, `SupervisedActiveHigh` |
| `IdPoint.Tampering.SupervisedCut/Short/High/Low` | mV |
| `IdPoint.REX.Type` | `None`, `ActiveLow`, `ActiveHigh`, `SupervisedActiveLow`, `SupervisedActiveHigh`, `RS-485HD` |
| `IdPoint.REX.SupervisedCut/Short/Low/High` | mV |
| `IdPoint.Keypress.Types` (Entry Manager section spells it `IdPoint.Keypress.Type`) | `Auto`, `4bit`, `6bitEData`, `8bit`, `8bitInvLow`, `8bitInvHigh`, `8bitDF750` |
| `IdPoint.Hardware.Address` | hex (Aperio 6 hex digits; SmartIntego e.g. 0x200; OSDP/HADP manual address 0..7E) |
| `IdPoint.Hardware.DetectionMode` | `Auto` (default), `Manual` (required for OSDP multidrop; A1210/A1610 support up to two OSDP readers per port) |
| `IdPoint.Hardware.Id` | SmartIntego "phi" string |
| `IdPoint.Hub.Hardware.Address` | hex |
| `IdPoint.SecureChannel.KeyToken` | axkey token |
| `IdPoint.SecureChannel.KeyType` | `KeyBase`, `KeyMaster`, `None` |
| `IdPoint.Status.BatteryAlarm` / `.RadioDisturbance` / `.SecureChannel` / `.Device` | status (IsProperty) |
| `IdPoint.Whitelist.IdData.Name` (also written `IdPoint.Whitelist.IdDataName`) | default `Card` (SmartIntego) |

Wiegand reader example (verbatim):
```
{
    "IdPointConfiguration": [
        {
            "token": "",
            "DeviceUUID": "",
            "IdDataConfiguration": [""],
            "Configuration": [
                { "Name": "IdPoint.Reader.Type", "Value": "Wiegand" },
                { "Name": "IdPoint.LED.Type", "Value": "SingleLED" },
                { "Name": "IdPoint.LED.ActiveLevel", "Value": "ActiveLow" },
                { "Name": "IdPoint.Beeper.Type", "Value": "ActiveLow" },
                { "Name": "IdPoint.Tampering.Type", "Value": "ActiveLow" }
            ]
        }
    ]
}
```
OSDP: `IdPoint.Reader.Type`=`RS-485HD` + `IdPoint.RS-485HD.Protocol`=`OSDP` (+ `IdPoint.Hardware.Address`="0", `IdPoint.Hardware.DetectionMode`="Manual" for multidrop). REX-only: `IdPoint.Reader.Type`=`None`, `IdPoint.REX.Type`=`ActiveLow`.

SetIdPoint (verbatim):
```
{
    "axtid:SetIdPoint": {
        "IdPoint": [
            {
                "token": "idpoint1",
                "Name": "Name1",
                "Area": "Area1",
                "MinPINSize": 4,
                "MaxPINSize": 4,
                "EndOfPIN": "#",
                "HeartbeatInterval": "PT10M",
                "Location": "Loc1",
                "Timeout": "PT3S",
                "Action": "Action1",
                "Description": "Desc1"
            }
        ]
    }
}
```

### 7.4 Card formats (IdDataConfiguration)
Default formats exist (e.g. Wiegand 26-bit H10301); list with `axtid:GetIdDataConfigurationList`. If no assigned IdDataConfiguration matches the bit length, the event/IdData only contains `Card` (raw lowercase hex of all bits) and `BitCount`. `Card` and `BitCount` are ALWAYS included.
H10301 doc table: EvenParity 1 BinLE2Int; FacilityCode 2-9 BinLE2Int; CardNr 10-25 BinLE2Int; CardNrHex 10-25 BinLE2hex; OddParity 26 BinLE2Int. Input bits `1 0000 0000 0010 0111 1110 0101 1` -> Card `02004fcb`, EvenParity 1, FacilityCode 0, CardNr 10213, CardNrHex 27e5, OddParity 1, BitCount 26. (Note: Card hex = the 26 bits left-padded to 32 bits: 0b00_1000_0000_0010_0111_1110_0101_1 -> 0x02004fcb.)
```
{
    "axtid:SetIdDataConfiguration": {
        "IdDataConfiguration": [
            {
                "token": "",
                "InputBitlength": 26,
                "Name": "IdDataConfig example",
                "IdDataFieldMap": [
                    {
                        "Map": "1-26",
                        "Name": "FullCard",
                        "Encoding": "BinLE2hex"
                    },
                    {
                        "Map": "1",
                        "Name": "ParityEven",
                        "Encoding": "BinLE2Int"
                    },
                    {
                        "Map": "2-9",
                        "Name": "FacilityCode",
                        "Encoding": "BinLE2Int"
                    },
                    {
                        "Map": "10-25",
                        "Name": "CardNr",
                        "Encoding": "BinLE2Int"
                    },
                    {
                        "Map": "10-25",
                        "Name": "CardNrHex",
                        "Encoding": "BinLE2hex"
                    },
                    {
                        "Map": "26",
                        "Name": "ParityOdd",
                        "Encoding": "BinLE2Int"
                    }
                ],
                "Description": "Test Description"
            }
        ]
    }
}
```
```
{
    "axtid:GetLastCredential": {
        "Token": "idpoint1"
    }
}
```
```
{
    "IdData": [
        { "Name": "FullCard", "Value": "02004fcb" },
        { "Name": "ParityEven", "Value": "1" },
        { "Name": "FacilityCode", "Value": "0" },
        { "Name": "CardNr", "Value": "10213" },
        { "Name": "CardNrHex", "Value": "27e5" },
        { "Name": "ParityOdd", "Value": "1" },
        { "Name": "Card", "Value": "02004fcb" },
        { "Name": "BitCount", "Value": "26" }
    ]
}
```
Guide table of encodings (with "Length limit"): BinLE2hex, BinLEIBO2hex, BinBE2hex, BinBEIBO2hex, Bin2Base64, BinIBO2Base64 (no limit); BinLE2Int, BinLEIBO2Int, BinBE2Int, BinBEIBO2Int (64bit).

### 7.5 IndicateRemoteActivities (IP readers, LPR cameras, remote REX) - verbatim
```
{
    "axtid:IndicateRemoteActivities": {
        "Token": "MyToken",
        "Description": "MyDescr",
        "Activities": [
            {
                "Type": "REX"
            }
        ]
    }
}
```
```
{
    "axtid:IndicateRemoteActivities": {
        "Token": "MyToken",
        "Description": "MyDescr",
        "Activities": [
            {
                "Type": "Card",
                "Params": [
                    {
                        "Name": "Card",
                        "Value": "02004fcb"
                    },
                    {
                        "Name": "PIN",
                        "Value": "1111"
                    }
                ]
            }
        ]
    }
}
```
LPN: `{"Type":"Card","Params":[{"Name":"LPN","Value":"MyLPN"}]}` (needs an AuthenticationProfile IdFactor with IdDataName `LPN`). PIN: `{"Type":"PIN","Params":[{"Name":"PIN","Value":"1111"}]}`. Response for all: `{}`.
Per activity two events: (1) `tns1:IdPoint/tnsaxis:Activity` with Reason `CardPresented` (Card) / `REX` (REX) / `CodeEntered` (PIN); (2) `tns1:IdPoint/tnsaxis:Request/tnsaxis:IdData` (Card) / `.../tnsaxis:REX` / `.../tnsaxis:PIN`. The AccessController reacts to the Request event and runs the access decision. Params Name/Value pairs must match credential IdData pairs, in the same order. Card+PIN profile: Card then PIN (separate calls), Card+PIN or PIN+Card in one call all grant; PIN then Card as separate calls can be denied.

## 8. Events

Three ways to read events on these controllers:
1. Stored log: Event Logger service (`axlog` / `axloc`, JSON at `/vapix/eventlogger`). This is the documented PACS way and the format all PACS doc examples use.
2. Real-time ONVIF events (pull-point subscription, WS-notification) via SOAP `/vapix/services`. The doc says "By creating pull-point subscriptions, it is possible to listen to events in real time. Refer to the ONVIF documentation for details." (A1001 explicitly ONVIF Profile C conformant.)
3. Real-time VAPIX "Event streaming over WebSocket" `ws(s)://<device>/vapix/ws-data-stream?sources=events` (generic AXIS OS API; not mentioned in PACS pages - availability on A1210/A1610 firmware is INFERRED, AXIS OS based).

### 8.1 Topic list (verbatim from Event logger "Notification topics" table; availability depends on product configuration and firmware)
Schedule service:
- `tns1:Schedule/tnsaxis:Interval` - interval schedule state changes
- `tns1:Schedule/tnsaxis:Pulse` - pulse schedule becomes active
Door control service:
- `tns1:Door/State/DoorMode` - DoorMode changes (e.g. accessed)
- `tns1:Door/State/DoorPhysicalState` - e.g. door opened
- `tns1:Door/State/LockPhysicalState` - e.g. door unlocked
- `tns1:Door/State/DoubleLockPhysicalState`
- `tns1:Door/State/DoorAlarm` - DoorAlarm state changes, "that is, when the OpenTooLongTime time expires" (also forced open per ONVIF enum)
- `tns1:Door/State/DoorFault`
- `tns1:Door/State/DoorTamper`
- `tns1:Door/State/DoorWarning` - "when the PreAlarmTime expires" (Axis addition; values from DoorWarningState: `Normal`, `DoorOpenTooLongWarn` - INFERRED data key `State`)
- `tns1:Door/tnsaxis:Status/BatteryAlarm` (Aperio; `ID` field = hardware address)
- `tns1:Door/tnsaxis:Status/LockJammed` (Aperio)
- `tns1:Door/tnsaxis:Status/RadioDisturbance` (Aperio; `ID` field)
- `tns1:Configuration/Door/Changed`, `tns1:Configuration/Door/Removed`
IdPoint service:
- `tns1:IdPoint/tnsaxis:Activity` - initial activity at an IdPoint (no sensitive data); Reason `CardPresented` / `REX` / `CodeEntered`
- `tns1:IdPoint/tnsaxis:Request/PIN` - PIN entered without card
- `tns1:IdPoint/tnsaxis:Request/REX`
- `tns1:IdPoint/tnsaxis:Request/IdData` - card (and maybe PIN) presented; contains `Card` (raw hex) and `BitCount`, plus fields from the IdDataConfiguration map (e.g. `CardNr`, `FacilityCode`); "Depending on the timeout configuration, card data and PIN can be sent in the same event". (IdPoint page writes these as `tns1:IdPoint/tnsaxis:Request/tnsaxis:IdData` etc.)
- `tns1:IdPoint/tnsaxis:Status/BatteryAlarm`, `tns1:IdPoint/tnsaxis:Status/RadioDisturbance` (Aperio, `ID`)
- `tns1:IdPoint/tnsaxis:Timeout` - IdPoint timeout expired
- `tns1:IdPoint/tnsaxis:Tampering` - reader tamper
- `tns1:Configuration/tnsaxis:IdPoint/Changed`, `tns1:Configuration/tnsaxis:IdPoint/Removed`
- `tns1:IdPoint/tnsaxis:Status/SecureChannel`
- `tns1:IdPoint/tnsaxis:Status/Device` - OSDP reader online/offline
- `tns1:IdPoint/tnsaxis:PreAuthorization/tnsaxis:IdData` - whitelist access
- `tns1:IdPoint/tnsaxis:Status/tnsaxis:WhitelistSync/tnsaxis:Error`, `.../tnsaxis:Ongoing`
Access control service:
- `tns1:AccessControl/AccessGranted/Anonymous`, `tns1:AccessControl/AccessGranted/Credential`
- `tns1:AccessControl/AccessTaken/Anonymous`, `tns1:AccessControl/AccessTaken/Credential`
- `tns1:AccessControl/AccessNotTaken/Anonymous`, `tns1:AccessControl/AccessNotTaken/Credential`
- `tns1:AccessControl/Denied/Anonymous`
- `tns1:AccessControl/Denied/Authentication/InvalidPIN`
- `tns1:AccessControl/Denied/Credential`
- `tns1:AccessControl/Denied/CredentialNotFound/Card`
- `tns1:AccessControl/Denied/CredentialNotFound/PIN`
- `tns1:AccessControl/Duress`
- `tns1:AccessPoint/State/Enabled`
- `tns1:Configuration/AccessPoint/Changed`, `.../Removed`
- `tns1:Configuration/Area/Changed`, `.../Removed`
- `tns1:Configuration/Credential/Changed`, `.../Removed`
- `tns1:Credential/State/ApbViolation`
- (ONVIF also defines `tns1:AccessControl/Request/Anonymous|Credential|Timeout` for external authorization, and Axis's `RemoteValidationEvent` operator mentions `AccessControl/Request/ExternalConfirmation` / `AccessControl/Request/Authorization/Credential` - not in Axis's topic table.)
Connection service: `tns1:Device/tnsaxis:PeerConnection` (keys `Peer` (MAC), `Status`).
Event logger: `tnsaxis:EventLogger/Alarm`, `tnsaxis:EventLogger/DroppedAlarms`, `tnsaxis:EventLogger/DroppedEvents`.
Other: `tns1:Device/tnsaxis:Casing/Open` (controller tamper), `tns1:Device/tnsaxis:IO/Port`, `tns1:Device/tnsaxis:IO/Virtualinput`, `tns1:Device/tnsaxis:IO/Virtualport`, `tns1:Device/tnsaxis:Network/Lost`, `tns1:Device/tnsaxis:Status/Systemready` (key `ready`; FetchEvents2 example filters `topic2`=`SystemReady`), `tns1:Device/tnsaxis:SystemMessage/Actionfailed`.
Remote I/O: `tnsaxis:RemoteDevice/Connection/Status`.
Third-party credential (A1001): `tns1:Configuration/Credential/tnsaxis:ThirdPartyCredentialCreated|CreatedFailed|Removed|RemovedFailed|Enabled`, `tnsaxis:ThirdPartyCredential/Status/ProviderConnection`.
Not in the list (so do not invent unless needed): a door "tamper" for the controller is `Device/Casing/Open`; there is no `tns1:Device/Trigger/...` in the PACS list.

### 8.2 Message fields (Source / Data) per topic
From ONVIF specs (IsProperty in parentheses) + Axis examples:
| Topic | Source | Data |
|---|---|---|
| Door/State/DoorMode (property) | `DoorToken` | `State` (DoorMode enum) |
| Door/State/DoorPhysicalState (property) | `DoorToken` | `State` (`Unknown`/`Open`/`Closed`/`Fault`) |
| Door/State/LockPhysicalState (property) | `DoorToken` | `State` (`Unknown`/`Locked`/`Unlocked`/`Fault`) |
| Door/State/DoubleLockPhysicalState (property) | `DoorToken` | `State` (LockPhysicalState) |
| Door/State/DoorAlarm (property) | `DoorToken` | `State` (`Normal`/`DoorForcedOpen`/`DoorOpenTooLong`) |
| Door/State/DoorTamper (property) | `DoorToken` | `State` (`Unknown`/`NotInTamper`/`TamperDetected`) |
| Door/State/DoorFault (property) | `DoorToken` | `State` (`Unknown`/`NotInFault`/`FaultDetected`), `Reason` (may be empty/absent) |
| Door/State/DoorWarning (property, Axis) | `DoorToken` (INFERRED) | `State` (`Normal`/`DoorOpenTooLongWarn`) (INFERRED) |
| Configuration/Door/Changed, Removed | `DoorToken` | - |
| AccessControl/AccessGranted/Anonymous | `AccessPointToken` | `External` (bool, optional) |
| AccessControl/AccessGranted/Credential | `AccessPointToken` | `CredentialToken`, `CredentialHolderName` (opt), `External` (opt), `SecurityLevelToken` (opt), `ExemptedAccess` (opt) |
| AccessControl/AccessTaken/Anonymous, AccessNotTaken/Anonymous | `AccessPointToken` | - |
| AccessControl/AccessTaken/Credential, AccessNotTaken/Credential | `AccessPointToken` | `CredentialToken`, `CredentialHolderName` (opt) |
| AccessControl/Denied/Anonymous | `AccessPointToken` | `External` (opt), `Reason` |
| AccessControl/Denied/Credential | `AccessPointToken` | `CredentialToken`, `CredentialHolderName` (opt), `Reason`, `External` (opt), `SecurityLevelToken` (opt) |
| AccessControl/Denied/CredentialNotFound/Card | `AccessPointToken` | `Card` (vendor-specific string); Axis example ALSO carries the request IdData such as `CardNr` |
| AccessControl/Denied/CredentialNotFound/PIN (Axis) | `AccessPointToken` | INFERRED `PIN` |
| AccessControl/Denied/Authentication/InvalidPIN (Axis) | `AccessPointToken` | INFERRED `CredentialToken`, `CredentialHolderName` |
| AccessControl/Duress | `AccessPointToken` | `CredentialToken` (opt), `CredentialHolderName` (opt), `Reason` |
| AccessControl/Request/Anonymous, Request/Timeout | `AccessPointToken` | - |
| AccessControl/Request/Credential | `AccessPointToken` | `CredentialToken`, `CredentialHolderName` |
| AccessPoint/State/Enabled (property) | `AccessPointToken` | `State` (xs:boolean) |
| Configuration/AccessPoint/Changed, Removed | `AccessPointToken` | - |
| Configuration/Area/Changed, Removed | `AreaToken` | - |
| Configuration/Credential/Changed, Removed | INFERRED `CredentialToken` | - |
| Credential/State/ApbViolation | `CredentialToken` (onvif-source), `CredentialHolderName`, `Device Source` | `Reason`=`AntiPassbackViolation`, `ApbViolation` '1'/'0', `ClientUpdated` '0'/'1' |
| IdPoint/tnsaxis:Request/IdData | INFERRED `IdPointToken` | `Card`, `BitCount`, mapped IdData names |
| IdPoint/tnsaxis:Request/PIN | INFERRED `IdPointToken` | INFERRED `PIN` |
| IdPoint/tnsaxis:Request/REX | INFERRED `IdPointToken` | INFERRED `REX`=`Active` |
| IdPoint/tnsaxis:Activity | INFERRED `IdPointToken` | `Reason` (`CardPresented`/`REX`/`CodeEntered`); IndicateRemoteActivities adds its `Description` |
| Device/tnsaxis:PeerConnection | - | `Peer` (MAC), `Status` |
| Schedule/tnsaxis:Interval (property) | INFERRED `ScheduleToken` | `Active`, `Exception` (booleans) |
| Schedule/tnsaxis:Pulse | INFERRED `ScheduleToken` | - |
CredentialHolderName in Axis examples is often the credential's `UserToken` (e.g. `"user_token1"` or `Axis-...` tokens), not a human name. If more than one credential matched (shared PIN), `CredentialToken` and `CredentialHolderName` are empty.
Denied `Reason` values: ONVIF `CredentialNotEnabled`, `CredentialNotActive`, `CredentialExpired`, `InvalidPIN`, `NotPermittedAtThisTime`, `Unauthorized`, `Other`, `pt:InvalidIdentifierValue`; Axis additionally uses `InvalidAccessProfile`, `AntiPassbackViolation` (and `InvalidCredential` in RequestAccess responses). Unknown values must be treated as `Other`.

Event sequences (Axis):
- Card granted: `IdPoint/Activity` -> `IdPoint/Request/IdData` -> `AccessControl/AccessGranted/Credential` -> `Door/State/DoorMode` State=`Accessed` -> (door opens) `Door/State/DoorPhysicalState` Open -> `AccessControl/AccessTaken/Credential` -> door closes/relock -> DoorMode back (e.g. `Locked`). If not opened within AccessTime -> `AccessControl/AccessNotTaken/Credential`. (Order of the door events relative to AccessTaken is INFERRED.)
- REX: AccessGranted/Anonymous then AccessTaken/Anonymous or AccessNotTaken/Anonymous.
- Unknown card: `AccessControl/Denied/CredentialNotFound/Card`. Known but blocked: `AccessControl/Denied/Credential` + Reason.
- Duress PIN used: access granted + `AccessControl/Duress`.
- Door held open: `Door/State/DoorWarning` (PreAlarmTime before) then `Door/State/DoorAlarm` State=`DoorOpenTooLong`; opened while Locked (no grant) -> DoorAlarm `DoorForcedOpen`. Unlocked/Accessed modes mask these.
- Stateful (property) events are re-sent with the current value at startup / on new subscription.

### 8.3 Event Logger service (`axlog` = http://www.axis.com/vapix/ws/EventLogger; `axloc` = http://www.axis.com/vapix/ws/EventLoggerConfig; both JSON on `/vapix/eventlogger`)
Capacity: event log max 30,000 events; max 1000 per FetchEvents call (default Limit 1000). Alarm list max 200 alarms. Alarms are also kept in the event log; acknowledging (removing) an alarm removes it only from the alarm list.

`axlog:FetchEvents` / `axlog:FetchAlarms` request (all optional): `Start` xs:dateTime (ISO 8601; omitted = year 0), `Stop` xs:dateTime (omitted = no upper limit), `Filters` [] of `{Key, Value?}` (AND; Value may be omitted to match key presence), `Limit` xs:int, `RowID` xs:long (continue after this rowid), `Descending` xs:boolean (default false = ascending). Response: `Event` [] (FetchAlarms: `Alarm` []) of FetchedEvent, `More` xs:boolean [1][1]. Faults `ter:InvalidStartTime`, `ter:InvalidStopTime`. Access class ACTUATE.
`axlog:FetchEvents2` / `axlog:FetchAlarms2`: same plus `FilterSets` [] of `{Filters: [...]}` - sets ORed, filters within a set ANDed. (Not in API tables, only in guide.)
Paging: "If the number of events matching a fetch request is larger than the set limit, the reply will have the More flag set to true. To fetch the rest ... call axlog:FetchEvents again but this time with the RowID parameter set to the row id of the last event in the previous response." (INFERRED: with Descending=true, RowID continues downward.)
`axlog:RemoveLoggedAlarm`: `Token` [] (alarm tokens) -> empty. Fault NotFound.

FetchedEvent record: `rowid` (int, monotonically increasing log row), `token` (event token, same format as other tokens), `UUID` (producing device), `UtcTime` (ISO 8601 with microseconds and Z, e.g. `2013-10-31T10:55:24.067163Z`), `KeyValues` [] of `{Key, Value, Tags}`, `Tags` []. The topic is split into `topic0`, `topic1`, `topic2`, `topic3` keys WITHOUT namespaces ("The namespaces in the topic are not stored in the event logger database and cannot be recreated in the FetchEvents call"). Source items carry tag `onvif-source`, data items `onvif-data`, typed items `wstype:<type>` (e.g. `wstype:pt:ReferenceToken`, `wstype:tdc:DoorMode`), property state items `property-state`. Topic keys have `"Tags": []` (sometimes Tags omitted). With global distribution an extra key (`Device Source` = UUID, tag onvif-source) is added. Stored structures also have (LoggedEvent/LoggedAlarm) `Property`, `DeclarationID`; KeyValue has `Namespace`, `Key`, `Value`, `Type`, `Tags`.

Verbatim requests:
```
{
    "axlog:FetchEvents": {
        "Start": "2012-11-27T00:00:00",
        "Stop": "2012-11-27T14:00:00"
    }
}
```
```
{
    "axlog:FetchEvents": {
        "Limit": 2,
        "RowID": 2
    }
}
```
```
{
    "axlog:FetchEvents": {
        "Filters": [
            { "Key": "topic0", "Value": "Door" },
            { "Key": "topic1", "Value": "State" },
            { "Key": "topic2", "Value": "DoorMode" },
            { "Key": "State", "Value": "Locked" }
        ]
    }
}
```
```
{
    "axlog:FetchEvents2": {
        "FilterSets": [
            {
                "Filters": [
                    { "Key": "topic2", "Value": "SystemReady" },
                    { "Key": "ready", "Value": "0" }
                ]
            },
            {
                "Filters": [
                    { "Key": "topic2", "Value": "DoorPhysicalState" },
                    { "Key": "State", "Value": "Closed" }
                ]
            }
        ]
    }
}
```
(One doc example writes `"Filters": [{ "topic0": "AccessControl" }]` - a doc slip; the schema is `{Key, Value}`.)
Verbatim response:
```
{
    "Event": [
        {
            "rowid": 76,
            "token": "Axis-00408c184c74:1382951603.616761001",
            "UUID": "5581ad80-95b0-11e0-b883-00408c184c74",
            "UtcTime": "2013-10-28T09:13:23.018766Z",
            "KeyValues": [
                {
                    "Key": "CredentialHolderName",
                    "Value": "Axis-00408c184c74:1382951566.633213000",
                    "Tags": ["onvif-data"]
                },
                {
                    "Key": "AccessPointToken",
                    "Value": "Axis-00408c184c74:1382951520.315392000",
                    "Tags": ["wstype:pt:ReferenceToken", "onvif-source"]
                },
                {
                    "Key": "topic2",
                    "Value": "Credential",
                    "Tags": []
                },
                {
                    "Key": "topic1",
                    "Value": "AccessGranted",
                    "Tags": []
                },
                {
                    "Key": "topic0",
                    "Value": "AccessControl",
                    "Tags": []
                },
                {
                    "Key": "CredentialToken",
                    "Value": "Axis-00408c184c74:1382951567.312696000",
                    "Tags": ["wstype:pt:ReferenceToken", "onvif-data"]
                }
            ],
            "Tags": []
        }
    ],
    "More": false
}
```
Same event as received by ONVIF pull-point (verbatim XML fragment):
```
<wsnt:Topic>tns1:AccessControl/AccessGranted/Credential</wsnt:Topic>
<wsnt:Message>
  <tt:Message UtcTime="2013-10-28T09:13:23Z">
    <tt:Source>
      <tt:SimpleItem Name="AccessPointToken"
        Value="Axis-00408c184c74:1382951520.315392000" />
    </tt:Source>
    <tt:Data>
      <tt:SimpleItem Name="CredentialHolderName"
        Value="Axis-00408c184c74:1382951566.633213000" />
      <tt:SimpleItem Name="CredentialToken"
        Value="Axis-00408c184c74:1382951567.312696000" />
    </tt:Data>
  </tt:Message>
</wsnt:Message>
```
Denied unknown card (verbatim; note topic3):
```
{
    "rowid": 330,
    "token": "Axis-00408c185451:1383232007.384795000",
    "UUID": "5581ad80-95b0-11e0-b883-00408c185451",
    "UtcTime": "2013-10-31T15:06:46.680154Z",
    "KeyValues": [
        {
            "Key": "Card",
            "Value": "00007352",
            "Tags": ["onvif-data"]
        },
        {
            "Key": "CardNr",
            "Value": "87654321",
            "Tags": ["onvif-data"]
        },
        {
            "Key": "AccessPointToken",
            "Value": "Axis-00408c185451:1383040794.997528000",
            "Tags": ["wstype:pt:ReferenceToken", "onvif-source"]
        },
        {
            "Key": "topic2",
            "Value": "CredentialNotFound",
            "Tags": []
        },
        {
            "Key": "topic1",
            "Value": "Denied",
            "Tags": []
        },
        {
            "Key": "topic0",
            "Value": "AccessControl",
            "Tags": []
        },
        {
            "Key": "topic3",
            "Value": "Card",
            "Tags": []
        }
    ],
    "Tags": []
}
```
Denied credential with reason (verbatim, KeyValues only): `CredentialHolderName`=`user_token1` [onvif-data], `Reason`=`CredentialNotEnabled` [onvif-data], `AccessPointToken` [wstype:pt:ReferenceToken, onvif-source], topic2 `Credential`, topic1 `Denied`, topic0 `AccessControl`, `CredentialToken` [wstype:pt:ReferenceToken, onvif-data]. Same shape for `CredentialNotActive`, `CredentialExpired`, `InvalidAccessProfile`.
A different (older/"decoded") event rendering also appears once in the docs (verbatim):
```
{
    "Data": {
        "CredentialHolderName": "user_token1",
        "CredentialToken": "Axis-00408c184bdb:1351593020.016190000",
        "Reason": "Unauthorized"
    },
    "Source": { "AccessPointToken": "Axis-00408c184bdb:1351589192.102223000" },
    "Topic": "tns1:AccessControl/Denied/Credential",
    "UtcTime": "2012-10-31T08:25:32Z"
}
```
(INFERRED: this is a human-friendly rendering, not a FetchEvents response; use the KeyValues form for FetchEvents.)

EventLoggerConfig (`axloc:`):
- `SetIgnoreFilter` / `SetAlarmFilter`: `Filter` [] of `{token?, KeyValues: [{Key, Value?}], UUIDs: [..]?}` -> `Token` []. Empty/omitted UUIDs = all controllers.
- `GetIgnoreFilterList` / `GetAlarmFilterList`: `{}` -> `Filter` [].
- `RemoveIgnoreFilter` / `RemoveAlarmFilter`: `Token` [] -> empty.
- If an event matches both ignore and alarm filters it becomes an alarm (and is logged). Alarm emission sends `tnsaxis:EventLogger/Alarm` (which can't itself become an alarm).
- `GetServiceCapabilities` -> `Capabilities` {`EnableGlobalEvents`}.
- `EnableGlobalDistribution` / `DisableGlobalDistribution`: empty/empty. `GetEventDistributionConfig` -> verbatim `{"EventDistributionConfig": [{ "GlobalDistributionEnabled": true }]}`. Global distribution (firmware >= 1.20) is enabled by default; replicates events to all peers.
Verbatim filter examples:
```
{
    "axloc:SetIgnoreFilter": {
        "Filter": [{ "KeyValues": [{ "Key": "a", "Value": "1" }], "UUIDs": ["abc"] }]
    }
}
```
```
{
    "Filter": [
        {
            "token": "Axis-00408c184bfa:1381327465.144879000",
            "KeyValues": [{ "Key": "a", "Value": "1" }],
            "UUIDs": ["abc"]
        }
    ]
}
```
```
{
    "axlog:RemoveLoggedAlarm": {
        "Token": ["Axis-00408c184bd0:1382625301.169265000", "Axis-00408c184bd0:1382625330.594026000"]
    }
}
```

### 8.4 ONVIF pull-point notes (from the event logger page)
Use content filter on SimpleItem `Device Source` to get events from all peers when global distribution is on: `boolean(//tt:SimpleItem[@Name="Device Source"])OR NOT( boolean(//tt:SimpleItem[@Name="Device Source"]))`. Without it, only local events. With global distribution disabled, events have no Device Source.

### 8.5 VAPIX Event streaming over WebSocket (generic AXIS OS API)
- Endpoint `ws(s)://<device>/vapix/ws-data-stream?sources=events`; auth Digest during the HTTP upgrade, or session token: `GET http(s)://<device>/axis-cgi/wssession.cgi` (digest) returns a token valid 15 s, used as `?wssession=<token>&sources=events`. API Discovery id `event-streaming-over-websocket`.
- Client -> server (verbatim):
```
{
    "apiVersion": "1.0",
    "context": "Client defined request ID",
    "method": "events:configure",
    "params": {
        "eventFilterList": [
            {
                "topicFilter": "tns1:PTZController/tnsaxis:PTZReady"
            },
            {
                "contentFilter": "boolean(//SimpleItem[@Name=\"ready\" and @Value=\"1\"])"
            },
            {
                "topicFilter": "tns1:Device/tnsaxis:IO/VirtualPort",
                "contentFilter": "boolean(//SimpleItem[@Name=\"port\" and @Value=\"1\"]) and boolean(//SimpleItem[@Name=\"state\" and @Value=\"0\"])"
            }
        ]
    }
}
```
Success reply `{"apiVersion":"1.0","context":"...","method":"events:configure","data":{}}`; failure `..."error":{"code":1100,"message":"Internal Error"}`. Each filter is a separate subscription (an event matching two filters is sent twice); only the latest configure applies. topicFilter uses ONVIF ConcreteSet dialect (`tns1:Device/tnsaxis:IO//`, `a | b`).
- Server -> client notification (verbatim):
```
{
    "apiVersion": "1.0",
    "method": "events:notify",
    "params": {
        "notification": {
            "timestamp": 1639385866198,
            "topic": "tns1:Device/tnsaxis:IO/VirtualPort",
            "message": {
                "source": {
                    "port": "1"
                },
                "key": {},
                "data": {
                    "state": "0"
                }
            }
        }
    }
}
```
`timestamp` = epoch milliseconds. Error codes: 1100 internal, 2100 API version not supported, 2101 invalid JSON, 2102 method not supported, 2103 required parameter missing, 2104 invalid parameter value, 2105 authorization failed, 2106 authentication failed, 2107 request too large.
INFERRED PACS mapping: `{"topic":"tns1:Door/State/DoorMode","message":{"source":{"DoorToken":"..."},"key":{},"data":{"State":"Accessed"}}}`; `{"topic":"tns1:AccessControl/AccessGranted/Credential","message":{"source":{"AccessPointToken":"..."},"key":{},"data":{"CredentialToken":"...","CredentialHolderName":"..."}}}`.

## 9. ACAP apps calling these APIs on the device (loopback 127.0.0.12)

Source: https://developer.axis.com/acap/how-to-guides/VAPIX-access-for-ACAP-applications/ (ACAP version 12 docs). Nothing on the PACS pages is ACAP-specific; this is the generic AXIS OS mechanism, so it applies only to A1210/A1610 firmware that is AXIS OS >= 11.6 (INFERRED that these controllers' current AXIS OS supports it).
- From AXIS OS 11.6 an ACAP app can get VAPIX service-account credentials with "admin" access level at runtime.
- Manifest: add `"resources": {"dbus": {"requiredMethods": ["com.axis.HTTPConf1.VAPIXServiceAccounts1.GetCredentials"]}}` and remove the `user` section (app must run as a dynamic/generated user).
- D-Bus (system bus): destination `com.axis.HTTPConf1`, object `/com/axis/HTTPConf1/VAPIXServiceAccounts1`, interface `com.axis.HTTPConf1.VAPIXServiceAccounts1`, method `GetCredentials`, argument `(s)` username (e.g. "testuser"). Returns one string `"<id>:<password>"`, verbatim example `('a0-testuser:MH757eGZdsyBuAbhAQ3j2ZtRNg9xchEg',)` (the returned id is prefixed, e.g. `a0-`).
- (Older ACAP SDK 3 docs used interface `com.axis.HTTPConf1.Auth1` method `GetVapixServiceAccountCredentials`; renamed - taken from a search summary of the old page, not re-read.)
- Call VAPIX at `http://127.0.0.12/<path>` with Basic auth using those credentials (example uses CURLAUTH_ANY; doc text: "checks the given credentials (using basic access authentication)"). Example: `curl -s -u <id>:<pass> http://127.0.0.12/axis-cgi/applications/list.cgi`. For PACS: `POST http://127.0.0.12/vapix/pacs` (and /vapix/doorcontrol etc.) with the same JSON bodies (INFERRED but follows directly).
- If a global device proxy is set, 127.0.0.12 must be in the "No proxy" list.
- Limits: max 200 service accounts per device; all are removed on reboot; re-fetch on every app start; keep only in memory.
Simulator implication: listen on a loopback-style address, accept Basic auth for a generated account (and Digest/Basic for normal users), same JSON API.

## 10. Other PACS services (summary, for completeness)

### 10.1 I/O assignment (`axisio`, `/vapix/pin`) - no events
Methods: `GetIoAssignmentList`, `GetIoUserInfoList`, `GetIoInfoList`, `SetIoAssignment`.
- `IoUserInfo`: `Name` (e.g. "Door3", "Reader In"), `IoUser` {`Type` (`doorcontrol` | `idpoint`), `token` (Door/IdPoint token), `Usage` (e.g. `Lock_Standard`, `LedSingle`, `Wiegand`, `DoorOpenMonitor`), `MultiIo` bool}, `IoMode` [] (e.g. `inout:12V/gnd`, `out:float/gnd`, `out:pu/gnd`, `inout:float/gnd`, `inout:pu/gnd`, `in:pu/gnd`, `wiegand`, `rs485fd`, `h_bridge`, `supervised`).
- `IoInfo`: `IoName` (e.g. `IO1`, `H-bridge1`, `Ser0fd`, `H1`, `IN1`), `IoMode` [], `PinInfo` [] {`Name` e.g. "Aux I/O:3", "Lock:2", "Reader Data 1:1", `Description`}.
- `IoAssignment`: `IoName`, `IoMode`, `IoUser` []. Setting a Door/IdPoint config creates IoUsers that must be assigned before hardware works (a simulator can ignore electrical detail but should accept these calls).
```
{
    "axisio:SetIoAssignment": {
        "IoAssignment": [
            {
                "IoName": "H1",
                "IoMode": "inout:12V/gnd",
                "IoUser": [
                    {
                        "MultiIo": false,
                        "Type": "doorcontrol",
                        "Usage": "Lock_Standard",
                        "token": "Axis-0408c184bcc:1353672968.091740000"
                    }
                ]
            }
        ]
    }
}
```

### 10.2 Connection service (`aconn`, `/vapix/aconn`) - multi-controller network
`GetPeerList` -> `Self` (Peer), `Peer` []. Peer: `ID` (MAC `000000000000` or `00:00:00:00:00:00`), `ExpectedAddress`, `LastKnownAddress`, `DeviceUUID`, `TrustState` (`NotInPeerNetwork`, `AddingToPeerNetwork`, `InitialSyncWithPeerNetwork`, `InPeerNetwork`, `RemovingFromPeerNetwork`), `ConnectionState` (`Disconnected`, `PairingFailed`, `Connected`). `AddPeers` {Peer [] of {ID, ExpectedAddress}} -> empty; `RemovePeers` {Peer [] PeerInfo}; `SetStandAloneMode` {StandAlone bool}; `GetStandAloneMode` -> {StandAlone}; `LeaveNetwork`. Event `tns1:Device/tnsaxis:PeerConnection`.

### 10.3 Keystore (`axkey`, `/vapix/axkey`)
`GetEncryptionKeyList`, `SetEncryptionKey`, `GetEncryptionKey`, `RemoveEncryptionKey`. EncryptionKey: `token`, `Name`, `Description`, `Key` (hex, e.g. `00010203040506070809101112131415`). Used by OSDP secure channel (`IdPoint.SecureChannel.KeyToken`).

### 10.4 AXIS Entry Manager conventions (what a real client built-in UI writes; useful for realistic simulator data)
- User: `axudb:User` with `Name` = "LastName, FirstName", Attributes `FirstName`, `LastName` (type "string"); exactly one Credential per User with `UserToken`, `Enabled: true`, `Status: "Enabled"`; IdData `PIN` (4 digits) and/or `CardNr`; groups = `CredentialAccessProfile` entries (no ValidFrom/ValidTo); no AuthenticationProfile on credential.
- Group = AccessProfile: `Schedule` list (when group active), `AccessPolicy` per AccessPoint with `Schedule: ["standard_always"]`, Enabled true, AuthenticationProfile [] ; both in/out AccessPoints of a door always included together.
- Door: Door + DoorConfiguration (+ DoorScheduleConfiguration) share token; Door timings AccessTime PT7S, OpenTooLongTime PT30S, PreAlarmTime PT10S, ExtendedAccessTime PT30S, ExtendedOpenTooLongTime PT60S, HeartbeatInterval PT600S, DefaultPriority "", no PriorityConfiguration; DoorConfiguration `DebounceTime`=0, DoorMonitor.ValueWhenOpen=`Input Open`, ValueWhenClosed=`Input Ground`. Up to two doors per device.
- AccessPoint: one per direction with a reader/REX; `Attribute` `Direction` = `in`/`out`; `Action` = `AccessDoor`; `EntityType`/Type `tdc:Door`; `Entity` = door token; `DoorDeviceUUID` = controller UUID; added to the AccessController's `AccessPoint` list.
- AuthenticationProfiles per AccessPoint, at most one per IdData type: PIN -> IdFactor {PIN, IdDataEqual, ""}; card -> {CardNr, IdDataEqual, ""}; card+PIN -> both; REX -> {REX, OperatorValueEqual, "Active"}.
- DoorScheduleConfiguration: no PriorityLevel; ScheduledStates sorted Unlock, Lock, DoubleLock; last one is the max lock level with `standard_always`.
- IdPoint: same token as IdPointConfiguration; Action "Access"; Area ""; MinPINSize 4; MaxPINSize 4; EndOfPIN "#"; Timeout "PT10S"; IdDataConfiguration = all configured on the unit. Wiegand: Reader.Type Wiegand, LED SingleLED/ActiveLow, Beeper ActiveLow, Tampering ActiveLow, REX None, `IdPoint.Keypress.Type` Auto. OSDP: Reader.Type RS-485HD, `IdPoint.RS-485FD.Protocol` OSDP (sic). REX: Reader.Type None + REX.Type ActiveLow/ActiveHigh.
- Priorities: default PriorityConfiguration (`Standard`, single level) so manual actions, schedules and access all override each other (a manual unlock lasts until the next schedule transition).
- `standard_always` must exist and stay "always".

### 10.5 Not covered by Axis docs (relevant to the brief)
- ONVIF Credential service (`tcr`: GetCredentials, CreateCredential, ModifyCredential, SetCredential, CredentialIdentifier, `*WithExtension`), ONVIF Access Rules (`tar`: AccessProfile with AccessPolicy {ScheduleToken, Entity, EntityType}), ONVIF Schedule service (`tsc`: SpecialDayGroup, SpecialDays, GetScheduleState) are NOT documented for A1210/A1610 in Axis's PACS docs. The Axis model differs: credential fields `IdData` (Name/Value) instead of ONVIF `CredentialIdentifier` (Type/ExemptedFromAuthentication/Value); `CredentialAccessProfile.AccessProfile` instead of `AccessProfileToken`; Axis schedules use `ExceptionScheduleDefinition` instead of SpecialDays. Whether the controllers additionally expose ONVIF Profile A/C `tcr`/`tar`/`tsc` services over SOAP is not stated (INFERRED: possibly on newer firmware; out of scope here).
- No documented user-facing "door" GetDoorList pagination limit / MaxLimit value. INFERRED sensible MaxLimit: 1000 (matches FetchEvents).
- No documented HTTP status codes for JSON faults.
- No documented JSON examples for: GetServiceCapabilities responses, GetDoorState response, GetDoorInfoList response, GetIdPointInfoList response, GetCredentialList/Info responses (shapes derived from the field tables above).

## 11. Simulator checklist (derived; mostly INFERRED design guidance)
1. Endpoints `/vapix/pacs` (tac, pacsaxis, axudb), `/vapix/doorcontrol` (tdc, axtdc), `/vapix/idpoint` (axtid), `/vapix/schedule` (axsch), `/vapix/eventlogger` (axlog, axloc), optionally `/vapix/pin` (axisio), `/vapix/aconn`, `/vapix/axkey`. POST, single-key JSON body `{"prefix:Method":{...}}`. Accept either prefix where the docs mix them (authentication profiles under `tac:` and `pacsaxis:`).
2. Responses: bare message fields; `{}` for empty; `{"Token":[...]}` for Set*; faults as `{"Fault","FaultCode","FaultSubCode","FaultReason","FaultMsg"}`.
3. Factory state: AccessController `Axis-<mac> AccessController` (UUID `5581ad80-95b0-11e0-b883-<mac>`), AccessControllerConfiguration, AuthenticationProfiles `CardOnly`, `PINOnly`, `CardPlusPin`, `REXOnly`, schedules `standard_always`, `standard_office_hours`, `standard_weekends`, PriorityConfiguration `Standard`, default IdDataConfigurations incl. H10301 26-bit.
4. Token generation `Axis-<mac>:<epoch>.<9 digits>`; client tokens honoured.
5. Pagination via Limit/StartReference/NextStartReference (opaque string; single use); Get by `Token` list ignores unknown tokens.
6. Door state machine per section 2.3 + priority stack per 2.7 + schedule-driven EnterAction per 2.8; timers AccessTime/OpenTooLongTime/PreAlarmTime/Extended*; emit Door events and log them.
7. Access decision per sections 3.5-3.8 (credential Enabled/Status/ValidFrom/ValidTo -> CredentialAccessProfile window -> AccessProfile Enabled/ValidFrom/ValidTo/Schedule -> AccessPolicy for the AccessPoint + its Schedule -> AuthenticationProfile precedence Credential > AccessProfile > AccessPoint, active per its Schedule list, IdFactors in order) -> Reasons/events per section 8.
8. CardNr uniqueness check on SetCredential (fault `env:Sender / ter:InvalidArgVal / ter:InvalidCredentialFault`, INFERRED triple; the doc's one JSON example of this fault class uses `ter:InvalidArgs` as FaultCode).
9. Event log: rowid counter, 30,000 cap (drop oldest - INFERRED), FetchEvents filters/RowID/Limit/More/Descending, alarm filters, 200-alarm list.

# Axis door controllers: lockdown, exemptions ("responders") and a panic input

Compiled 2026-11-14 from **public** Axis documents only (no account, no contact). Nothing tried on a controller: the conclusions below are
**to be confirmed on the bench (GATE H)**. UNVERIFIED marks what no source states.

## Sources

| Key | Where |
|---|---|
| DC | VAPIX door control service: https://developer.axis.com/vapix/physical-access-control/door-control-service/ |
| AC | VAPIX access control service: https://developer.axis.com/vapix/physical-access-control/access-control-service/ |
| EL | VAPIX event logger: https://developer.axis.com/vapix/physical-access-control/event-logger-service/ |
| PAC | VAPIX physical access control (services table): https://developer.axis.com/vapix/physical-access-control/ |
| SIE | VAPIX system integration examples: https://developer.axis.com/vapix/physical-access-control/system-integration-examples/ |
| EAS | VAPIX event and action services: https://developer.axis.com/vapix/network-video/event-and-action-services/ |
| WSDL | https://www.axis.com/vapix/ws/action1/ActionService.wsdl |
| IOPM, SUPIO | VAPIX I/O port management; supervised I/O |
| ACS, ACSR, SEX | AXIS Camera Station Pro Secure Entry manual; its "action rules for access control" how-to; AXIS Secure Entry for XProtect manual |
| UM1610, UM1210, UM1601 | the controllers' user manuals (help.axis.com) |
| RN1610 | A1610 12.6.102.1 release notes |
| INT | https://www.axis.com/for-developers/access-control-integration |
| DCE | AXIS Door Controller Extension release notes |
| RCP | Axis how-to: door controller as a recipient (A1001) |

## 0. Firmware tracks (affects buying the bench kit)

- A1610/A1210 firmware comes in **tracks**: Secure Entry, VAPIX, Genetec. 12.6.102.1 is "Firmware track: Secure Entry" [RN1610]. Switching
  tracks needs a factory default (UNVERIFIED in the full text; seen in a summary of the same page).
- Axis's integrator guidance: **"always use VAPIX firmware track"**; Axis-specific features are "only supported via VAPIX" [INT].
- **For PhotonEntry: order (or reflash to) the VAPIX track**, and check the track first thing on the bench.

## 1. Lockdown and responders

**Confirmed:**
- `tdc:LockDownDoor(Token, PriorityLevel?)`: other door commands are ignored until `tdc:LockDownReleaseDoor` [DC]. In `LockedDown`,
  "AccessDoor, LockDoor, UnlockDoor, BlockDoor and LockOpenDoor requests are ignored"; the same page's state table says they "generate an
  error to the caller" (it contradicts itself) [DC]. Release "shall only succeed if the current DoorMode is LockedDown"; next state
  "typically Locked" [DC].
- `tdc:AccessDoor` (what a granted card does) has **no PriorityLevel** [DC]; card, PIN and REX act at the default priority [SIE].
- Priorities exist (`axtdc:SetPriorityConfiguration`, `GetDoorPriorityState`, `ReleaseDoor(Token, PriorityLevel)`; highest level's
  non-Release action wins) [DC].
- Denial reasons (Granted, InvalidCredential, CredentialNotEnabled, Unauthorized, InvalidAccessProfile, CredentialNotActive,
  CredentialExpired, CredentialNotFound, AntiPassbackViolation): **none for lockdown** [AC]. Credential attributes: no lockdown exemption [AC].
- **No threat-level service** in VAPIX [PAC].
- Axis's own software has **"Exempt from lockdown"** per cardholder [ACS, SEX]; how it reaches the controller is **not public** (it may need
  the Secure Entry track).

**UNVERIFIED:** what a valid card at a LockedDown door logs (granted then ignored, or denied, and with which reason); whether a higher-priority
Unlock or Access overrides a LockDown; whether an AccessPoint's `ActionArgument` can carry a priority (which would let exempt credentials act
at a higher level through their own access profile, like the Duress pattern).

**So for PhotonEntry:** lockdown = `tdc:LockDownDoor` per door (built, Step 6). **Responders are not built**: bench probes 1–3 below decide
between a priority-level design and no responders on the VAPIX track.

## 2. A wired panic input that locks down without the cloud

**Confirmed:**
- A1610/A1210 aux inputs can be digital or supervised [UM1610, UM1210]; supervised states short, close, open, cut [SUPIO].
- Input events: `tns1:Device/tnsaxis:IO/tnsaxis:Port` (items `port`, `state`), `tns1:Device/Trigger/DigitalInput` [EAS, IOPM].
- The action service (`aa:` at `/vapix/services`, SOAP 1.2): Add/Remove ActionConfiguration and ActionRule, a rule = start event and/or
  conditions + a primary action [WSDL, EAS]. **No door-control action template is documented**; the HTTP notification template
  (`com.axis.action.fixed.notification.http`, recipient `com.axis.recipient.http`) is [EAS].
- Axis's own Secure Entry "Emergency input" can only **lock or unlock** (no lockdown) [ACS]; its lockdown-from-input is an action rule in
  Axis's VMS, not on the controller [ACSR].
- No door-configuration key for an emergency or lockdown input [DC].

**Two candidate designs, both UNVERIFIED:**
- **A. The controller's own rule:** an action rule on the input's edge sends the HTTP notification to the controller itself
  (`http://127.0.0.1/vapix/doorcontrol?format=simple&action=tdc:LockDownDoor&Token=<door>`; the simple GET form is documented for the A1001
  [RCP]); a second rule on the other edge releases it. Works with entry-link stopped. Unverified: the simple form on A1610/A1210, loopback,
  the stored login.
- **B. entry-link watches the input** and calls `tdc:LockDownDoor`. Works with the cloud away, not with entry-link stopped.
- Either way, entry-link would set it up from the settings (`pe-` named rules), and the cloud would record the lockdown with `source: input`.

## 3. Bench probes (read-only first)

1. `tdc:GetDoorInfoList` (LockDown and PriorityLevels capabilities), `tdc:GetServiceCapabilities` (PriorityConfigurationSupported),
   `axtdc:GetDoorPriorityState`.
2. Lock a door down; present a valid card: which events, which reason.
3. With a priority configuration: does a higher-level Access or Unlock open a LockedDown door? Can an access point act at that level?
4. `aa:GetActionTemplates`, `aa:GetRecipientTemplates`, `aev:GetEventInstances` (the input topics, the supervised port's fields).
5. Design A end to end on an aux input; then the same with entry-link stopped.

"""A simulated Axis A1210/A1610 network door controller: its access-control data, its doors and its decisions.

Built from Axis's public VAPIX documentation (developer.axis.com/vapix/physical-access-control: the door control, access control, user,
schedule, IdPoint and event logger services). `docs/SIMULATOR.md` lists what is simulated, what is simplified and every behavior Axis does not
document that we had to choose (marked INFERRED there and in comments here). When the bench (BUILD-GUIDE GATE H) shows a difference, this file
is fixed first.

The object stores hold the services' JSON objects as Axis returns them (`token` lowercase, other fields capitalized). Runtime door state is
kept apart from configuration. Time: `now_utc()` and the controller's local time zone (Axis schedules are in local time only).
"""
from __future__ import annotations

import itertools
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from axis_sim import ical

ALWAYS_DEF = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nDTSTART:19700101T000000\r\nDTEND:19700102T000000\r\nRRULE:FREQ=DAILY\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
OFFICE_DEF = ("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nSUMMARY:Office Hours\r\nDTSTART:19700101T090000\r\nDTEND:19700101T170000\r\n"
              "RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
WEEKENDS_DEF = ("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nDTSTART:19700103T000000\r\nDTEND:19700105T000000\r\nRRULE:FREQ=WEEKLY;BYDAY=SA\r\n"
                "END:VEVENT\r\nEND:VCALENDAR\r\n")
EVENT_LOG_CAPACITY = 30_000
FETCH_LIMIT = 1000


class Fault(Exception):
    """A VAPIX fault, sent as {"Fault", "FaultCode", "FaultSubCode", "FaultReason", "FaultMsg"}."""

    def __init__(self, env: str, code: str, sub: str, msg: str, reason: str = "Invalid argument") -> None:
        super().__init__(msg)
        self.body = {"Fault": env, "FaultCode": code, "FaultSubCode": sub, "FaultReason": reason, "FaultMsg": msg}


def not_found(token: str) -> Fault:
    return Fault("env:Sender", "ter:InvalidArgVal", "ter:NotFound", f"Token '{token}' not found")


def _parse_time(v: str) -> Optional[datetime]:
    if not v:
        return None
    return datetime.fromisoformat(v.replace("Z", "+00:00"))


def _seconds(duration: str) -> float:
    """xs:duration as Axis uses it (PT<n>S, PT<n>M, PT<n>H, combinations)."""
    if not duration.startswith("PT"):
        raise Fault("env:Sender", "ter:InvalidArgs", "", f"bad duration {duration!r}")
    total, num = 0.0, ""
    for ch in duration[2:]:
        if ch.isdigit() or ch == ".":
            num += ch
        elif ch in "HMS" and num:
            total += float(num) * {"H": 3600, "M": 60, "S": 1}[ch]
            num = ""
        else:
            raise Fault("env:Sender", "ter:InvalidArgs", "", f"bad duration {duration!r}")
    if num:
        raise Fault("env:Sender", "ter:InvalidArgs", "", f"bad duration {duration!r}")
    return total


@dataclass
class DoorRuntime:
    base: str = "Locked"              # the mode set by the last door action or door-schedule enter action (one priority level)
    sticky: Optional[str] = None      # LockedDown or LockedOpen until released
    accessed_until: Optional[datetime] = None
    accessed_by: Optional[Tuple[str, str, str]] = None   # (access point, credential, holder) waiting for AccessTaken
    physical: str = "Closed"
    alarm: str = "Normal"
    warning: str = "Normal"
    opened_at: Optional[datetime] = None
    schedule_state: Optional[str] = None                 # the enter action last applied by the door schedule

    @property
    def mode(self) -> str:
        if self.sticky:
            return self.sticky
        if self.accessed_until is not None:
            return "Accessed"
        return self.base


@dataclass
class Device:
    mac: str = "00408c184bdb"
    doors: int = 2                                       # A1610: 2, A1210: 1
    tz: str = "America/New_York"
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    lock: threading.RLock = field(default_factory=threading.RLock)
    log_capacity: int = EVENT_LOG_CAPACITY               # the demo keeps fewer (memory); a real controller holds 30,000

    def __post_init__(self) -> None:
        self.uuid = f"5581ad80-95b0-11e0-b883-{self.mac}"
        self._seq = itertools.count(1)
        self.store: Dict[str, Dict[str, Dict[str, Any]]] = {k: {} for k in (
            "Door", "DoorConfiguration", "DoorScheduleConfiguration", "AccessPoint", "AccessController", "AuthenticationProfile",
            "AccessProfile", "Credential", "User", "Schedule", "IdPoint", "IdPointConfiguration")}
        self.runtime: Dict[str, DoorRuntime] = {}
        self.log: List[Dict[str, Any]] = []
        self._rowid = itertools.count(1)
        self.calls: List[str] = []
        self.offline = False                             # the test harness can make the device refuse every request
        self.read_to = 0                                 # the highest RowID a reader has asked for rows after (the demo waits on it)
        self._factory()

    # -- tokens, time --------------------------------------------------------------------------------------------------------------------------

    def new_token(self) -> str:
        t = self.clock().timestamp()
        return f"Axis-{self.mac}:{int(t)}.{next(self._seq):09d}"

    def now_utc(self) -> datetime:
        return self.clock()

    def now_local(self) -> datetime:
        return self.clock().astimezone(ZoneInfo(self.tz)).replace(tzinfo=None)

    # -- the factory state: a commissioned controller --------------------------------------------------------------------------------------------

    def _factory(self) -> None:
        """What an installer leaves after commissioning: doors with a lock and a door monitor, a reader per door (two on door 1 of an A1610:
        in and out), the access points, Axis's default schedules and authentication profiles. INFERRED: a factory-new device has no doors;
        commissioning is done in Axis's web pages, so the simulator starts from the commissioned state."""
        put = lambda kind, obj: self.store[kind].__setitem__(obj["token"], obj)  # noqa: E731
        for token, definition, name in (("standard_always", ALWAYS_DEF, "Always"), ("standard_office_hours", OFFICE_DEF, "Office hours"),
                                        ("standard_weekends", WEEKENDS_DEF, "Weekends")):
            put("Schedule", {"token": token, "Name": name, "Description": "", "Attribute": [], "ScheduleDefinition": definition,
                             "ExceptionScheduleDefinition": ""})
        for token, factors in (("CardOnly", [("Card", "IdDataEqual", "")]), ("PINOnly", [("PIN", "IdDataEqual", "")]),
                               ("CardPlusPin", [("Card", "IdDataEqual", ""), ("PIN", "IdDataEqual", "")]),
                               ("REXOnly", [("REX", "OperatorValueEqual", "Active")])):
            put("AuthenticationProfile", {"token": token, "Name": token, "Description": token, "Schedule": ["standard_always"],
                                          "IdFactor": [{"IdDataName": n, "IdMatchOperatorName": o, "OperatorValue": v} for n, o, v in factors]})
        controller = f"Axis-{self.mac} AccessController"
        aps: List[str] = []
        for n in range(1, self.doors + 1):
            door = f"Axis-{self.mac}:door{n}"
            put("Door", {"token": door, "Name": f"Door {n}", "Description": "", "AccessTime": "PT7S", "OpenTooLongTime": "PT15S",
                         "PreAlarmTime": "PT5S", "ExtendedAccessTime": "PT30S", "ExtendedOpenTooLongTime": "PT60S", "HeartbeatInterval": "PT0S",
                         "PriorityConfiguration": "Standard", "DefaultPriority": ""})
            put("DoorConfiguration", {"token": door, "DeviceUUID": "", "DoorScheduleConfiguration": "", "Configuration": [
                {"Name": "Lock.Type", "Value": "Relay"}, {"Name": "DoorMonitor.Type", "Value": "Standard"},
                {"Name": "DoorMonitor.ValueWhenOpen", "Value": "Input Open"}, {"Name": "DoorMonitor.ValueWhenClosed", "Value": "Input Ground"}]})
            self.runtime[door] = DoorRuntime()
            sides = ["in", "out"] if (n == 1 and self.doors > 1) else ["in"]
            for side in sides:
                idp = f"Axis-{self.mac}:reader{n}{side}"
                put("IdPoint", {"token": idp, "Name": f"Reader {n} {side}", "Location": "", "Area": "", "Timeout": "PT3S",
                                "HeartbeatInterval": "PT0S", "Description": "", "Action": "Access", "MinPINSize": 4, "MaxPINSize": 8, "EndOfPIN": "#"})
                put("IdPointConfiguration", {"token": idp, "DeviceUUID": "", "IdDataConfiguration": [], "Configuration": [
                    {"Name": "IdPoint.Reader.Type", "Value": "RS-485HD"}, {"Name": "IdPoint.RS-485HD.Protocol", "Value": "OSDP"}]})
                ap = f"Axis-{self.mac}:ap{n}{side}"
                put("AccessPoint", {"token": ap, "Name": f"Door {n} {side}", "Description": "", "AreaFrom": "", "AreaTo": "",
                                    "EntityType": "axtdc:Door", "Entity": door, "DoorDeviceUUID": "", "Enabled": True,
                                    "IdPointDevice": [{"IdPoint": idp, "DeviceUUID": ""}],
                                    "AuthenticationProfile": ["CardOnly", "PINOnly"],     # INFERRED: an installer's "card or PIN" setup
                                    "Attribute": [{"type": "", "Name": "Direction", "Value": side}], "ActionArgument": [], "Action": "Access"})
                aps.append(ap)
        put("AccessController", {"token": controller, "Name": controller, "Description": "", "AccessPoint": aps})
        for door in self.store["Door"]:
            self._emit(["Door", "State", "DoorMode"], {"DoorToken": door}, {"State": "Locked"}, wstype="tdc:DoorMode")
            self._emit(["Door", "State", "DoorPhysicalState"], {"DoorToken": door}, {"State": "Closed"}, wstype="tdc:DoorPhysicalState")

    # -- the event log --------------------------------------------------------------------------------------------------------------------------

    def _emit(self, topic: List[str], source: Dict[str, str], data: Dict[str, str], wstype: Optional[str] = None) -> None:
        kv: List[Dict[str, Any]] = []
        for k, v in data.items():
            tags = ["onvif-data"]
            if k == "State" and wstype:
                tags = ["property-state", f"wstype:{wstype}", "onvif-data"]
            elif k == "CredentialToken":
                tags = ["wstype:pt:ReferenceToken", "onvif-data"]
            kv.append({"Key": k, "Value": v, "Tags": tags})
        for k, v in source.items():
            kv.append({"Key": k, "Value": v, "Tags": ["wstype:pt:ReferenceToken", "onvif-source"]})
        for n, part in reversed(list(enumerate(topic))):
            kv.append({"Key": f"topic{n}", "Value": part, "Tags": []})
        self.log.append({"rowid": next(self._rowid), "token": self.new_token(), "UUID": self.uuid,
                         "UtcTime": self.now_utc().strftime("%Y-%m-%dT%H:%M:%S.%fZ"), "KeyValues": kv, "Tags": []})
        if len(self.log) > self.log_capacity:
            del self.log[: len(self.log) - self.log_capacity]    # oldest dropped first, as a full log does

    def record(self, topic: List[str], source: Dict[str, str], data: Dict[str, str]) -> None:
        """Write an event into the log that the controller's own logic did not make. Only the demo's back-filled history uses it (docs/DEMO.md
        §2): the intercoms' events of the past, which entry-link would have recorded itself. A real controller has no such call."""
        self._emit(topic, source, data)

    # -- persistence (the demo's simulators survive a restart; a real controller keeps all of this in flash) ------------------------------------

    def snapshot(self) -> Dict[str, Any]:
        """Everything a restart must keep: the stores, the doors' runtime state and the event log. JSON-safe."""
        def t(v: Optional[datetime]) -> Optional[str]:
            return v.isoformat() if v else None
        return {"mac": self.mac, "doors": self.doors, "tz": self.tz, "store": self.store, "log": self.log[-self.log_capacity:],
                "next_rowid": (self.log[-1]["rowid"] + 1) if self.log else 1,
                "runtime": {d: {"base": r.base, "sticky": r.sticky, "accessed_until": t(r.accessed_until),
                                "accessed_by": list(r.accessed_by) if r.accessed_by else None, "physical": r.physical, "alarm": r.alarm,
                                "warning": r.warning, "opened_at": t(r.opened_at), "schedule_state": r.schedule_state}
                            for d, r in self.runtime.items()}}

    def restore(self, snap: Dict[str, Any]) -> None:
        """Back to a snapshot of this same controller (refused for another one)."""
        if snap["mac"] != self.mac or snap["doors"] != self.doors:
            raise ValueError("a snapshot of another controller")
        self.store, self.log = snap["store"], snap["log"][-self.log_capacity:]
        self._rowid = itertools.count(snap["next_rowid"])
        self.runtime = {d: DoorRuntime(base=r["base"], sticky=r["sticky"], accessed_until=_parse_time(r["accessed_until"] or ""),
                                       accessed_by=tuple(r["accessed_by"]) if r["accessed_by"] else None, physical=r["physical"],
                                       alarm=r["alarm"], warning=r["warning"], opened_at=_parse_time(r["opened_at"] or ""),
                                       schedule_state=r["schedule_state"])
                        for d, r in snap["runtime"].items()}

    def fetch_events(self, row_id: int = 0, limit: int = FETCH_LIMIT, filters: Optional[List[Dict[str, str]]] = None,
                     descending: bool = False) -> Tuple[List[Dict[str, Any]], bool]:
        limit = FETCH_LIMIT if limit is None or limit < 1 or limit > FETCH_LIMIT else limit
        if not descending:
            self.read_to = max(self.read_to, row_id)
        rows = list(reversed(self.log)) if descending else self.log
        if row_id:
            rows = [r for r in rows if (r["rowid"] < row_id if descending else r["rowid"] > row_id)]
        for f in filters or []:
            rows = [r for r in rows if any(kv["Key"] == f["Key"] and ("Value" not in f or kv["Value"] == f["Value"]) for kv in r["KeyValues"])]
        return rows[:limit], len(rows) > limit

    # -- doors ------------------------------------------------------------------------------------------------------------------------------------

    def _door(self, token: str) -> DoorRuntime:
        if token not in self.runtime:
            raise not_found(token)
        return self.runtime[token]

    def _set_mode(self, door: str, change: Callable[[DoorRuntime], None]) -> None:
        rt = self._door(door)
        before = rt.mode
        change(rt)
        if rt.mode != before:
            self._emit(["Door", "State", "DoorMode"], {"DoorToken": door}, {"State": rt.mode}, wstype="tdc:DoorMode")
            if rt.mode in ("Unlocked", "LockedOpen", "Accessed") and rt.alarm == "DoorOpenTooLong":
                self._alarm(door, rt, "Normal")       # unlocked modes mask the held-open alarm

    def door_action(self, door: str, action: str) -> None:
        """tdc door actions. INFERRED (Axis: "an error to the caller"): while LockedDown or LockedOpen, any other action is a Failure fault."""
        rt = self._door(door)
        if action == "LockDownRelease":
            if rt.sticky != "LockedDown":
                raise Fault("env:Receiver", "ter:Action", "ter:Failure", "Door is not locked down", "Failure")
            self._set_mode(door, lambda r: setattr(r, "sticky", None))
            return
        if action == "LockOpenRelease":
            if rt.sticky != "LockedOpen":
                raise Fault("env:Receiver", "ter:Action", "ter:Failure", "Door is not locked open", "Failure")
            self._set_mode(door, lambda r: setattr(r, "sticky", None))
            return
        if rt.sticky and not (rt.sticky == "LockedOpen" and action == "LockDown"):
            raise Fault("env:Receiver", "ter:Action", "ter:Failure", f"Door is {rt.sticky}", "Failure")

        def change(r: DoorRuntime) -> None:
            if action == "LockDown":
                r.sticky, r.accessed_until, r.accessed_by = "LockedDown", None, None
            elif action == "LockOpen":
                r.sticky, r.accessed_until = "LockedOpen", None
            else:
                r.base = {"Lock": "Locked", "Unlock": "Unlocked", "Block": "Blocked", "DoubleLock": "DoubleLocked"}[action]
                if action != "Unlock":
                    r.accessed_until = None
        self._set_mode(door, change)

    def access_door(self, door: str, seconds: Optional[float] = None, by: Optional[Tuple[str, str, str]] = None) -> bool:
        """tdc:AccessDoor: unlock for the door's AccessTime. Ignored when the door is blocked, locked down or locked open (Axis: AccessDoor
        requests are ignored in those modes), and when it is unlocked already (nothing to do)."""
        rt = self._door(door)
        if rt.mode in ("Blocked", "LockedDown", "LockedOpen", "Unlocked"):
            return rt.mode == "Unlocked"
        until = self.now_utc() + timedelta(seconds=seconds if seconds is not None else _seconds(self.store["Door"][door]["AccessTime"]))
        self._set_mode(door, lambda r: (setattr(r, "accessed_until", until), setattr(r, "accessed_by", by)))
        return True

    def _alarm(self, door: str, rt: DoorRuntime, state: str) -> None:
        if rt.alarm != state:
            rt.alarm = state
            self._emit(["Door", "State", "DoorAlarm"], {"DoorToken": door}, {"State": state}, wstype="tdc:DoorAlarmState")

    def set_physical(self, door: str, state: str) -> None:
        """The door contact (the test harness opens and closes doors). Opening while the lock is locked raises DoorForcedOpen."""
        rt = self._door(door)
        if state == rt.physical:
            return
        rt.physical = state
        self._emit(["Door", "State", "DoorPhysicalState"], {"DoorToken": door}, {"State": state}, wstype="tdc:DoorPhysicalState")
        if state == "Open":
            rt.opened_at = self.now_utc()
            if rt.accessed_by is not None:
                ap, cred, holder = rt.accessed_by
                self._access_event("AccessTaken", ap, cred, holder)
                rt.accessed_by = None
            elif rt.mode in ("Locked", "Blocked", "LockedDown", "DoubleLocked"):
                self._alarm(door, rt, "DoorForcedOpen")
        else:
            rt.opened_at = None
            if rt.warning != "Normal":
                rt.warning = "Normal"
                self._emit(["Door", "State", "DoorWarning"], {"DoorToken": door}, {"State": "Normal"}, wstype="tdc:DoorWarningState")
            self._alarm(door, rt, "Normal")
            if rt.accessed_until is not None:
                # Axis: the door locks again when it is closed after an access, or when AccessTime runs out if it was never opened.
                self._set_mode(door, lambda r: setattr(r, "accessed_until", None))

    def tick(self) -> None:
        """Run the timers: access time, held-open warning and alarm, door schedules. The server calls it before every request and the
        harness every 100 ms, so timers fire within that resolution."""
        now = self.now_utc()
        for door, rt in self.runtime.items():
            d = self.store["Door"][door]
            if rt.accessed_until is not None and now >= rt.accessed_until:
                if rt.accessed_by is not None:
                    ap, cred, holder = rt.accessed_by
                    self._access_event("AccessNotTaken", ap, cred, holder)
                    rt.accessed_by = None
                self._set_mode(door, lambda r: setattr(r, "accessed_until", None))
            if rt.physical == "Open" and rt.opened_at is not None and rt.mode not in ("Unlocked", "LockedOpen", "Accessed"):
                open_for = (now - rt.opened_at).total_seconds()
                limit = _seconds(d["OpenTooLongTime"])
                if open_for >= limit - _seconds(d["PreAlarmTime"]) and rt.warning == "Normal" and rt.alarm == "Normal":
                    rt.warning = "DoorOpenTooLongWarn"
                    self._emit(["Door", "State", "DoorWarning"], {"DoorToken": door}, {"State": rt.warning}, wstype="tdc:DoorWarningState")
                if open_for >= limit and rt.alarm == "Normal":
                    self._alarm(door, rt, "DoorOpenTooLong")
            self._door_schedule(door, rt)

    def _door_schedule(self, door: str, rt: DoorRuntime) -> None:
        """The door's DoorScheduleConfiguration: the first active ScheduledState's EnterAction is applied when it changes (Axis: also when
        the configuration is set and at restart). One priority level, so an API action and a schedule action replace each other."""
        link = self.store["DoorConfiguration"][door].get("DoorScheduleConfiguration") or ""
        config = self.store["DoorScheduleConfiguration"].get(link)
        if not config:
            rt.schedule_state = None
            return
        wanted = None
        for state in config["DoorSchedule"][0]["ScheduledState"]:
            if self.schedules_active(state["ScheduleToken"]):
                wanted = state["EnterAction"]
                break
        if wanted and wanted != rt.schedule_state:
            rt.schedule_state = wanted
            if not rt.sticky and wanted in ("Lock", "Unlock", "Block", "DoubleLock"):
                self.door_action(door, wanted)

    # -- schedules ----------------------------------------------------------------------------------------------------------------------------

    def schedule_active(self, token: str) -> Tuple[bool, bool]:
        """(Active, Exception) for one schedule at the controller's local time."""
        s = self.store["Schedule"].get(token)
        if s is None:
            raise not_found(token)
        at = self.now_local()
        exception = ical.active(ical.parse(s.get("ExceptionScheduleDefinition") or ""), at)
        return (not exception) and ical.active(ical.parse(s["ScheduleDefinition"]), at), exception

    def schedules_active(self, tokens: List[str]) -> bool:
        """Axis: any schedule in the list active, and no exception active."""
        states = [self.schedule_active(t) for t in tokens if t in self.store["Schedule"]]
        return any(a for a, _ in states) and not any(e for _, e in states)

    # -- the access decision ------------------------------------------------------------------------------------------------------------------

    def _access_event(self, kind: str, ap: str, cred: str, holder: str, reason: Optional[str] = None) -> None:
        if cred:
            data = {"CredentialToken": cred, "CredentialHolderName": holder}
            if reason:
                data["Reason"] = reason
            self._emit(["AccessControl", kind, "Credential"], {"AccessPointToken": ap}, data)
        else:
            self._emit(["AccessControl", kind, "Anonymous"], {"AccessPointToken": ap}, {"Reason": reason} if reason else {})

    def present(self, idpoint: str, id_data: List[Dict[str, str]]) -> Tuple[bool, str]:
        """A credential at a reader (card, PIN or REX), as the IdPoint's Request event drives the access controller."""
        ap = next((a for a in self.store["AccessPoint"].values() if any(i["IdPoint"] == idpoint for i in a["IdPointDevice"])), None)
        if ap is None:
            raise not_found(idpoint)
        reason = "CodeEntered" if any(d["Name"] == "PIN" for d in id_data) and not any(d["Name"] == "Card" for d in id_data) else (
            "REX" if any(d["Name"] == "REX" for d in id_data) else "CardPresented")
        self._emit(["IdPoint", "Activity"], {"IdPointToken": idpoint}, {"Reason": reason})
        granted, why, cred, holder = self.decide(ap, id_data)
        if granted:
            self._access_event("AccessGranted", ap["token"], cred, holder)
            self.access_door(ap["Entity"], by=(ap["token"], cred, holder))
        elif why == "InvalidCredential":
            card = next((d["Value"] for d in id_data if d["Name"] == "Card"), None)
            if card is not None:
                self._emit(["AccessControl", "Denied", "CredentialNotFound", "Card"], {"AccessPointToken": ap["token"]}, {"Card": card})
            else:
                self._emit(["AccessControl", "Denied", "CredentialNotFound", "PIN"], {"AccessPointToken": ap["token"]}, {})
        else:
            self._access_event("Denied", ap["token"], cred, holder, why)
        return granted, why

    def decide(self, ap: Dict[str, Any], id_data: List[Dict[str, str]]) -> Tuple[bool, str, str, str]:
        """(granted, Reason, credential token, holder name). Reasons are Axis's (RequestAccess) and ONVIF's (Denied events)."""
        if not ap.get("Enabled", True):
            return False, "Unauthorized", "", ""
        given = {d["Name"]: d["Value"] for d in id_data}
        profiles = [self.store["AuthenticationProfile"][t] for t in ap.get("AuthenticationProfile", [])
                    if t in self.store["AuthenticationProfile"]]
        profiles = [p for p in profiles if self.schedules_active(p.get("Schedule") or ["standard_always"])]
        # REX: a profile matched by operator value alone grants anonymously (no credential).
        for p in profiles:
            factors = p["IdFactor"]
            if factors and all(f["IdMatchOperatorName"] == "OperatorValueEqual" and given.get(f["IdDataName"]) == f["OperatorValue"]
                               for f in factors):
                return True, "Granted", "", ""
        matches: List[Dict[str, Any]] = []
        for p in profiles:
            factors = [f for f in p["IdFactor"] if f["IdMatchOperatorName"] == "IdDataEqual"]
            if not factors or any(f["IdDataName"] not in given for f in factors):
                continue
            for c in self.store["Credential"].values():
                have = {d["Name"]: d["Value"] for d in c.get("IdData", [])}
                if all(have.get(f["IdDataName"]) == given[f["IdDataName"]] for f in factors) and c not in matches:
                    matches.append(c)
        if not matches:
            return False, "InvalidCredential", "", ""
        cred = matches[0]
        token = cred["token"] if len(matches) == 1 else ""          # Axis: several matches leave token and holder empty
        holder = cred.get("UserToken", "") if len(matches) == 1 else ""
        if not cred.get("Enabled", True) or cred.get("Status", "Enabled") != "Enabled":
            return False, "CredentialNotEnabled", token, holder
        now = self.now_utc()
        vf, vt = _parse_time(cred.get("ValidFrom", "")), _parse_time(cred.get("ValidTo", ""))
        if vf and now < vf:
            return False, "CredentialNotActive", token, holder
        if vt and now > vt:
            return False, "CredentialExpired", token, holder
        saw_profile, saw_policy = False, False
        for cap in cred.get("CredentialAccessProfile", []):
            prof = self.store["AccessProfile"].get(cap["AccessProfile"])
            cvf, cvt = _parse_time(cap.get("ValidFrom", "")), _parse_time(cap.get("ValidTo", ""))
            if prof is None or (cvf and now < cvf) or (cvt and now > cvt):
                continue
            pvf, pvt = _parse_time(prof.get("ValidFrom", "")), _parse_time(prof.get("ValidTo", ""))
            if not prof.get("Enabled", True) or (pvf and now < pvf) or (pvt and now > pvt):
                continue
            saw_profile = True
            if not self.schedules_active(prof.get("Schedule") or ["standard_always"]):
                continue
            for pol in prof.get("AccessPolicy", []):
                if pol["AccessPoint"] != ap["token"]:
                    continue
                saw_policy = True
                if self.schedules_active(pol.get("Schedule") or ["standard_always"]):
                    return True, "Granted", token, holder
        if not saw_profile:
            return False, "InvalidAccessProfile", token, holder
        # INFERRED (Axis does not document the reason when a valid profile has no active policy here): ONVIF's names.
        return False, ("NotPermittedAtThisTime" if saw_policy else "Unauthorized"), token, holder

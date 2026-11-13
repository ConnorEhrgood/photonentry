"""The compiler (CRITICAL): a site document and one controller's inventory → that controller's settings, in the shapes of Axis's access-control
services (contract/settings/axis-settings.schema.json; the services as `sim/axis_sim` and Axis's documentation describe them).

What each part of the document becomes on the controller:

| Document | Controller (service, object) |
|---|---|
| schedule | `axsch` Schedule `pe-s-<id>`: the weekly windows as `ScheduleDefinition`; the site's holidays as `ExceptionScheduleDefinition` when the schedule is off on holidays |
| access group | `pacsaxis` AccessProfile `pe-g-<id>`: one AccessPolicy per access point of each of its doors on this controller, with the rule's schedule |
| cardholder | `axudb` User `pe-u-<id>` (a name for events; users take no part in decisions) |
| credential | `pacsaxis` Credential `pe-c-<id>`: `Card` (the reader's raw hex) or `PIN`; validity from both the cardholder and the credential; the cardholder's groups as CredentialAccessProfiles |
| door timings | `axtdc` Door fields AccessTime, OpenTooLongTime, PreAlarmTime of the controller's door |
| door unlock schedule | `axtdc` DoorScheduleConfiguration `pe-d-<id>` (Unlock during the schedule, Lock otherwise), linked from the door's configuration |

**Only objects whose token starts with `pe-` belong to PhotonEntry.** `entry-link` creates, replaces and removes those, and never touches others
(Axis's own defaults such as `standard_always`, the controller's doors, access points, readers and authentication profiles, which are set up when
the door is commissioned).

Each controller gets only what concerns its own doors: the groups with a rule on one of them, the cardholders in those groups, the schedules
those rules and doors use. A cardholder with no access there is not sent at all.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.compiler import ical
from app.compiler.wiegand import card_data
from app.document import Cardholder, Credential, SiteDocument
from app.link.protocol import Inventory

FORMAT = "axis-pacs-1"
PREFIX = "pe-"
ALWAYS = "standard_always"           # Axis's built-in always-active schedule
MAX_CREDENTIALS = 250_000            # A1210/A1610 (datasheet)


class CompileError(Exception):
    def __init__(self, problems: List[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def _iso(t: Optional[datetime]) -> str:
    """Axis validity times: ISO 8601 in UTC with a Z; empty means no limit."""
    if t is None:
        return ""
    if t.tzinfo is None:
        raise CompileError([f"time {t.isoformat()} has no time zone"])
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _later(a: Optional[datetime], b: Optional[datetime]) -> Optional[datetime]:
    return max((x for x in (a, b) if x is not None), default=None)


def _earlier(a: Optional[datetime], b: Optional[datetime]) -> Optional[datetime]:
    return min((x for x in (a, b) if x is not None), default=None)


def _duration(seconds: int) -> str:
    return f"PT{seconds}S"


def compile_controller(doc: SiteDocument, controller_id: str, inventory: Optional[Inventory]) -> Dict[str, Any]:
    problems = doc.problems()
    if problems:
        raise CompileError(problems)
    if inventory is None:
        raise CompileError([f"controller {controller_id} has not reported its doors yet"])

    access_points = {d.token: d.access_points for d in inventory.doors}
    doors = [d for d in doc.doors if d.controller_id == controller_id]
    for d in doors:
        if d.controller_door not in access_points:
            problems.append(f"door {d.id}: the controller has no door {d.controller_door}")
        elif not access_points[d.controller_door]:
            problems.append(f"door {d.id}: the controller's door {d.controller_door} has no access points (readers)")
    if problems:
        raise CompileError(problems)
    door_points = {d.id: access_points[d.controller_door] for d in doors}

    schedules_used: set = set()
    profiles: List[Dict[str, Any]] = []
    for g in sorted(doc.access_groups, key=lambda g: g.id):
        policies = []
        for rule in g.rules:
            schedule = f"{PREFIX}s-{rule.schedule_id}" if rule.schedule_id else ALWAYS
            for door_id in rule.doors:
                for ap in door_points.get(door_id, []):
                    policies.append({"AccessPoint": ap, "AuthorizationProfile": [], "Attribute": [], "Schedule": [schedule]})
                    if rule.schedule_id and door_id in door_points:
                        schedules_used.add(rule.schedule_id)
        if policies:
            profiles.append({"token": f"{PREFIX}g-{g.id}", "Name": g.name, "Description": "", "Enabled": True, "Schedule": [ALWAYS],
                             "AuthenticationProfile": [], "Attribute": [],
                             "AccessPolicy": sorted(policies, key=lambda p: (p["AccessPoint"], p["Schedule"][0]))})
    profile_tokens = {p["token"] for p in profiles}

    users: List[Dict[str, Any]] = []
    credentials: List[Dict[str, Any]] = []
    for ch in sorted(doc.cardholders, key=lambda c: c.id):
        groups = sorted(t for t in (f"{PREFIX}g-{g}" for g in ch.groups) if t in profile_tokens)
        if not groups:
            continue
        users.append({"token": f"{PREFIX}u-{ch.id}", "Name": ch.name, "Description": "", "Attribute": []})
        credentials.extend(_credential(ch, k, groups) for k in sorted(ch.credentials, key=lambda k: k.id))
    if len(credentials) > MAX_CREDENTIALS:
        raise CompileError([f"controller {controller_id}: {len(credentials)} credentials, more than the {MAX_CREDENTIALS} it holds"])

    door_settings: List[Dict[str, Any]] = []
    door_schedules: List[Dict[str, Any]] = []
    for d in sorted(doors, key=lambda d: d.controller_door):
        link = ""
        if d.unlock_schedule_id:
            link = f"{PREFIX}d-{d.id}"
            schedules_used.add(d.unlock_schedule_id)
            # One DoorSchedule with no PriorityLevel (Axis: then it must be the only one). The first active schedule's action applies, so
            # "always: Lock" after the unlock schedule locks the door whenever the unlock schedule is not active.
            door_schedules.append({"token": link, "Name": f"{d.name} unlock schedule", "Description": "", "DoorSchedule": [
                {"ScheduledState": [{"ScheduleToken": [f"{PREFIX}s-{d.unlock_schedule_id}"], "EnterAction": "Unlock"},
                                    {"ScheduleToken": [ALWAYS], "EnterAction": "Lock"}]}]})
        door_settings.append({"token": d.controller_door, "Name": d.name, "AccessTime": _duration(d.access_time_s),
                              "OpenTooLongTime": _duration(d.open_too_long_s), "PreAlarmTime": _duration(d.pre_alarm_s),
                              "DoorScheduleConfiguration": link})

    holidays = []
    if doc.holiday_calendar_id:
        holidays = next(c for c in doc.holiday_calendars if c.id == doc.holiday_calendar_id).days
    schedules = []
    for s in sorted(doc.schedules, key=lambda s: s.id):
        if s.id not in schedules_used:
            continue
        exception = ical.whole_days(h.day for h in holidays) if s.on_holidays == "off" else ""
        schedules.append({"token": f"{PREFIX}s-{s.id}", "Name": s.name, "Description": "", "Attribute": [],
                          "ScheduleDefinition": ical.weekly(s.windows), "ExceptionScheduleDefinition": exception})

    return {"format": FORMAT, "controller_id": controller_id, "site_id": doc.site_id, "timezone": doc.timezone,
            "schedules": schedules, "users": users, "access_profiles": profiles, "credentials": credentials,
            "doors": door_settings, "door_schedules": door_schedules}


def _credential(ch: Cardholder, k: Credential, groups: List[str]) -> Dict[str, Any]:
    enabled = k.enabled and not ch.suspended
    id_data = [{"Name": "Card", "Value": card_data(k.card)}] if k.card is not None else [{"Name": "PIN", "Value": k.pin}]
    return {"token": f"{PREFIX}c-{k.id}", "UserToken": f"{PREFIX}u-{ch.id}", "Description": "", "Enabled": enabled,
            "Status": "Enabled" if enabled else "Disabled",
            "ValidFrom": _iso(_later(ch.valid_from, k.valid_from)), "ValidTo": _iso(_earlier(ch.valid_to, k.valid_to)),
            "IdData": id_data, "Attribute": [], "AuthenticationProfile": [],
            "CredentialAccessProfile": [{"AccessProfile": g, "ValidFrom": "", "ValidTo": ""} for g in groups]}

"""Site templates: a site's starting setup in one step (BUILD-GUIDE §3, ARCHITECTURE §10.1).

A template names **door slots** (the doors a site of that kind usually has: "Main entrance", "Server room"), the **schedules** it needs, the
**access groups** that combine them, and a **holiday calendar**. The integrator maps each slot to one of a claimed controller's doors (or leaves
an optional one out) and picks the options; applying the template then creates the doors, schedules and groups at the site and adds the
holidays to the site's calendar. Nothing is published: the integrator reviews, adds people and publishes.

Groups are meant to combine: an office's IT people are in "Staff" and in "IT" (the server room); a resident is in "Residents" only. A rule whose
doors were all left out is dropped, and a group with no rule left is not created.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

WEEKDAYS = ["mo", "tu", "we", "th", "fr"]
EVERY_DAY = ["mo", "tu", "we", "th", "fr", "sa", "su"]


@dataclass(frozen=True)
class Slot:
    key: str
    name: str
    hint: str
    required: bool = False
    access_time_s: int = 7
    open_too_long_s: int = 30
    pre_alarm_s: int = 5
    unlock: Optional[Tuple[str, str]] = None          # (option key, schedule key): unlocked during that schedule when the option is on


@dataclass(frozen=True)
class ScheduleT:
    key: str
    name: str
    windows: List[Dict]
    on_holidays: str = "off"


@dataclass(frozen=True)
class GroupT:
    key: str
    name: str
    description: str
    rules: List[Tuple[List[str], Optional[str]]]       # ([slot keys], schedule key or None for "at all times")


@dataclass(frozen=True)
class Option:
    key: str
    label: str
    default: bool = False


@dataclass(frozen=True)
class Template:
    key: str
    name: str
    description: str
    slots: List[Slot]
    schedules: List[ScheduleT]
    groups: List[GroupT]
    holidays: Optional[str]                            # "us-business" | "us-federal" | None
    options: List[Option] = field(default_factory=list)
    note: str = ""


def w(days: List[str], start: str, end: str) -> Dict:
    return {"days": days, "start": start, "end": end}


OFFICE = Template(
    key="office", name="Office",
    description="Staff in extended hours, managers at all times, IT in the server room, the cleaning crew in the evening.",
    slots=[
        Slot("main_entrance", "Main entrance", "The front door visitors use (often with the intercom)", required=True,
             unlock=("unlock_main", "business")),
        Slot("staff_entrance", "Staff entrance", "A side or back door for staff"),
        Slot("suite_door", "Suite door", "An inner door, if the office is a suite in a larger building"),
        Slot("server_room", "Server room", "The IT closet or server room", access_time_s=5, open_too_long_s=60),
    ],
    schedules=[
        ScheduleT("business", "Business hours", [w(WEEKDAYS, "08:00", "18:00")]),
        ScheduleT("extended", "Extended hours", [w(WEEKDAYS, "06:00", "22:00"), w(["sa"], "08:00", "14:00")]),
        ScheduleT("cleaning", "Cleaning crew hours", [w(WEEKDAYS, "18:00", "23:00")], on_holidays="normal"),
    ],
    groups=[
        GroupT("staff", "Staff", "Every employee: the entrances and the suite, in extended hours",
               [(["main_entrance", "staff_entrance", "suite_door"], "extended")]),
        GroupT("managers", "Managers", "The entrances and the suite at all times", [(["main_entrance", "staff_entrance", "suite_door"], None)]),
        GroupT("it", "IT", "The server room at all times (add IT staff to Staff as well)", [(["server_room"], None)]),
        GroupT("cleaning", "Cleaning crew", "The entrances and the suite in the evening", [(["main_entrance", "staff_entrance", "suite_door"], "cleaning")]),
    ],
    holidays="us-business",
    options=[Option("unlock_main", "Unlock the main entrance during business hours (otherwise visitors use the intercom)")],
)

TEMPLATES: Dict[str, Template] = {t.key: t for t in (OFFICE,)}


# ---- holidays ----

def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """The n-th weekday (0 = Monday) of a month; n = -1 for the last."""
    if n > 0:
        d = date(year, month, 1)
        d += timedelta(days=(weekday - d.weekday()) % 7)
        return d + timedelta(weeks=n - 1)
    d = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _observed(d: date) -> date:
    """A fixed-date holiday on a Saturday is observed the Friday before, on a Sunday the Monday after (US federal practice)."""
    return d - timedelta(days=1) if d.weekday() == 5 else d + timedelta(days=1) if d.weekday() == 6 else d


def holidays(kind: str, year: int) -> List[Tuple[date, str]]:
    thanksgiving = _nth_weekday(year, 11, 3, 4)
    business = [
        (_observed(date(year, 1, 1)), "New Year's Day"), (_nth_weekday(year, 5, 0, -1), "Memorial Day"),
        (_observed(date(year, 7, 4)), "Independence Day"), (_nth_weekday(year, 9, 0, 1), "Labor Day"),
        (thanksgiving, "Thanksgiving"), (thanksgiving + timedelta(days=1), "Day after Thanksgiving"), (_observed(date(year, 12, 25)), "Christmas Day"),
    ]
    if kind == "us-business":
        return sorted(business)
    federal = [d for d in business if d[1] != "Day after Thanksgiving"] + [
        (_nth_weekday(year, 1, 0, 3), "Martin Luther King Jr. Day"), (_nth_weekday(year, 2, 0, 3), "Presidents' Day"),
        (_observed(date(year, 6, 19)), "Juneteenth"), (_nth_weekday(year, 10, 0, 2), "Columbus Day"), (_observed(date(year, 11, 11)), "Veterans Day"),
    ]
    return sorted(federal)


# ---- the catalog, as the API shows it ----

def catalog() -> List[Dict]:
    return [{"key": t.key, "name": t.name, "description": t.description, "note": t.note, "holidays": t.holidays,
             "options": [{"key": o.key, "label": o.label, "default": o.default} for o in t.options],
             "slots": [{"key": s.key, "name": s.name, "hint": s.hint, "required": s.required} for s in t.slots],
             "schedules": [{"key": s.key, "name": s.name, "windows": s.windows, "on_holidays": s.on_holidays} for s in t.schedules],
             "groups": [{"key": g.key, "name": g.name, "description": g.description} for g in t.groups]}
            for t in TEMPLATES.values()]


@dataclass
class Plan:
    """What applying a template creates, worked out before anything is written."""
    schedules: List[ScheduleT]
    doors: List[Tuple[Slot, str, str, str, Optional[str]]]     # (slot, controller id, controller door, name, unlock schedule key)
    groups: List[Tuple[GroupT, List[Tuple[List[str], Optional[str]]]]]
    holidays: List[Tuple[date, str]]


class TemplateError(ValueError):
    pass


def plan(key: str, doors: Dict[str, Dict[str, str]], options: Dict[str, bool], years: List[int]) -> Plan:
    t = TEMPLATES.get(key)
    if t is None:
        raise TemplateError(f"no template {key}")
    known = {s.key for s in t.slots}
    unknown = sorted(set(doors) - known)
    if unknown:
        raise TemplateError(f"this template has no door {', '.join(unknown)}")
    missing = [s.name for s in t.slots if s.required and s.key not in doors]
    if missing:
        raise TemplateError(f"choose a door for: {', '.join(missing)}")
    bad = sorted(set(options) - {o.key for o in t.options})
    if bad:
        raise TemplateError(f"this template has no option {', '.join(bad)}")
    chosen = {o.key: options.get(o.key, o.default) for o in t.options}
    places = [(d["controller_id"], d["controller_door"]) for d in doors.values()]
    if len(set(places)) != len(places):
        raise TemplateError("one controller door is chosen for two slots")
    planned_doors = []
    for s in t.slots:
        if s.key in doors:
            d = doors[s.key]
            unlock = s.unlock[1] if s.unlock and chosen.get(s.unlock[0]) else None
            planned_doors.append((s, d["controller_id"], d["controller_door"], (d.get("name") or s.name)[:64], unlock))
    mapped = set(doors)
    groups = []
    for g in t.groups:
        rules = [([x for x in slots if x in mapped], sched) for slots, sched in g.rules]
        rules = [r for r in rules if r[0]]
        if rules:
            groups.append((g, rules))
    used = {sched for _, rules in groups for _, sched in rules if sched} | {u for *_, u in planned_doors if u}
    schedules = [s for s in t.schedules if s.key in used]
    days = sorted({d for y in years for d in (holidays(t.holidays, y) if t.holidays else [])})
    return Plan(schedules=schedules, doors=planned_doors, groups=groups, holidays=days)

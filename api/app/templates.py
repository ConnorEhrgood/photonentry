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

SCHOOL = Template(
    key="school", name="School",
    description="Staff in staff hours, administrators at all times, custodians early to late every day, after-school programs at the gym.",
    slots=[
        Slot("main_entrance", "Main entrance", "The front door, by the office", required=True, unlock=("unlock_arrival", "arrival")),
        Slot("staff_entrance", "Staff entrance", "The staff or parking-lot door"),
        Slot("side_door", "Side door", "Another exterior door staff use"),
        Slot("gym_entrance", "Gym entrance", "The door after-school programs and evening events use", unlock=("unlock_gym_events", "after_school")),
        Slot("office_door", "Office door", "The main office or records room", access_time_s=5),
    ],
    schedules=[
        ScheduleT("staff_hours", "Staff hours", [w(WEEKDAYS, "06:00", "18:00")]),
        ScheduleT("arrival", "Arrival and dismissal", [w(WEEKDAYS, "07:30", "08:15"), w(WEEKDAYS, "14:45", "15:30")]),
        ScheduleT("after_school", "After school", [w(WEEKDAYS, "15:00", "21:00"), w(["sa"], "08:00", "16:00")]),
        ScheduleT("custodial", "Custodial hours", [w(EVERY_DAY, "05:00", "23:00")], on_holidays="normal"),
    ],
    groups=[
        GroupT("staff", "Staff", "Teachers and staff: the exterior doors in staff hours",
               [(["main_entrance", "staff_entrance", "side_door", "gym_entrance"], "staff_hours")]),
        GroupT("administrators", "Administrators", "Every door at all times",
               [(["main_entrance", "staff_entrance", "side_door", "gym_entrance", "office_door"], None)]),
        GroupT("office", "Office staff", "The office door in staff hours (add them to Staff as well)", [(["office_door"], "staff_hours")]),
        GroupT("custodians", "Custodians", "Every door, early to late, every day",
               [(["main_entrance", "staff_entrance", "side_door", "gym_entrance", "office_door"], "custodial")]),
        GroupT("programs", "After-school programs", "The gym entrance after school", [(["gym_entrance"], "after_school")]),
    ],
    holidays="us-federal",
    options=[
        Option("unlock_arrival", "Unlock the main entrance at arrival and dismissal (otherwise it stays locked and visitors use the intercom)"),
        Option("unlock_gym_events", "Unlock the gym entrance after school"),
    ],
    note="Add the school's own breaks (winter, spring, teacher days) to the holidays after applying: the template adds only the federal holidays.",
)

MULTIFAMILY = Template(
    key="multifamily", name="Multifamily",
    description="Residents at the lobby and garage at all times and the amenities in their hours, staff and maintenance everywhere, vendors in the day.",
    slots=[
        Slot("lobby", "Lobby entrance", "The front door residents and visitors use (with the intercom)", required=True),
        Slot("garage", "Garage door", "The parking garage's pedestrian or vehicle door", access_time_s=15, open_too_long_s=120),
        Slot("package_room", "Package room", "Where deliveries are left"),
        Slot("amenity", "Amenity", "The gym, pool or clubroom"),
        Slot("leasing_office", "Leasing office", "The management office", unlock=("unlock_office", "office_hours")),
        Slot("mechanical", "Mechanical room", "Boiler, electrical or roof access", access_time_s=5, open_too_long_s=60),
    ],
    schedules=[
        ScheduleT("amenity_hours", "Amenity hours", [w(EVERY_DAY, "06:00", "23:00")], on_holidays="normal"),
        ScheduleT("package_hours", "Package room hours", [w(EVERY_DAY, "05:00", "24:00")], on_holidays="normal"),
        ScheduleT("office_hours", "Leasing office hours", [w(WEEKDAYS, "09:00", "18:00"), w(["sa"], "10:00", "16:00")]),
        ScheduleT("vendor_hours", "Vendor hours", [w(WEEKDAYS + ["sa"], "08:00", "18:00")]),
    ],
    groups=[
        GroupT("residents", "Residents", "The lobby and garage at all times, the package room and amenities in their hours",
               [(["lobby", "garage"], None), (["package_room"], "package_hours"), (["amenity"], "amenity_hours")]),
        GroupT("staff", "Property staff", "Every door but the mechanical room, at all times",
               [(["lobby", "garage", "package_room", "amenity", "leasing_office"], None)]),
        GroupT("maintenance", "Maintenance", "Every door at all times",
               [(["lobby", "garage", "package_room", "amenity", "leasing_office", "mechanical"], None)]),
        GroupT("vendors", "Vendors and couriers", "The lobby and the package room in the day", [(["lobby", "package_room"], "vendor_hours")]),
    ],
    holidays="us-business",
    options=[Option("unlock_office", "Unlock the leasing office during office hours")],
    note="Give each resident their unit number as their reference, so a move-out is one search away.",
)

GATE = Template(
    key="gate", name="Gate",
    description="A vehicle gate and a pedestrian gate: tenants and employees at all times, deliveries in the day.",
    slots=[
        Slot("vehicle_gate", "Vehicle gate", "The gate cars and trucks use", required=True, access_time_s=20, open_too_long_s=300, pre_alarm_s=30,
             unlock=("open_vehicle_gate", "business")),
        Slot("pedestrian_gate", "Pedestrian gate", "A walk-through gate beside it", access_time_s=7, open_too_long_s=60),
    ],
    schedules=[
        ScheduleT("business", "Business hours", [w(WEEKDAYS, "07:00", "18:00")]),
        ScheduleT("deliveries", "Delivery hours", [w(WEEKDAYS, "07:00", "15:00")]),
    ],
    groups=[
        GroupT("users", "Tenants and employees", "Both gates at all times", [(["vehicle_gate", "pedestrian_gate"], None)]),
        GroupT("deliveries", "Deliveries", "The vehicle gate in delivery hours", [(["vehicle_gate"], "deliveries")]),
    ],
    holidays="us-business",
    options=[Option("open_vehicle_gate", "Keep the vehicle gate open during business hours")],
    note="A vehicle gate's operator has its own safety devices (loops, photo eyes, reversing edges): PhotonEntry only tells it when to open.",
)

TEMPLATES: Dict[str, Template] = {t.key: t for t in (OFFICE, SCHOOL, MULTIFAMILY, GATE)}


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

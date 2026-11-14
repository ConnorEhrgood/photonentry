"""What happens at the demo's doors on a given day (docs/DEMO.md §1): the same plan for the back-filled history and for live, worked out from a
seed per site and day, so a day looks the same however often it is planned.

A plan is a list of actions in UTC. The simulated controllers decide every card and PIN themselves (with the settings the cloud sent them): the
plan only says who tries which reader when. Denials come from people trying outside their schedule, an expired card, a moved-out resident and
cards nobody knows.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Tuple
from zoneinfo import ZoneInfo

# Kinds: badge (a card or PIN at a reader; walk through if it opens), force (a door opened while locked), hold (badge, then the door is held
# open), vehicle (the gate opened and closed while it stands unlocked), call (an intercom call: answered and opened, or not).


@dataclass(frozen=True)
class Action:
    at: datetime
    kind: str
    controller: str
    door: int
    side: str = "in"
    id_data: Tuple[Tuple[str, str], ...] = ()
    seconds: float = 0.0              # force and hold: how long the door stays open; call: how long it rings
    answered: bool = False
    intercom: str = ""                # the intercom's id
    who: str = ""                     # for logs and tests only

    def credential(self) -> List[Dict[str, str]]:
        return [{"Name": n, "Value": v} for n, v in self.id_data]


@dataclass
class Site:
    """One site of the seed's roster (app/demo/seed.py)."""
    slug: str
    timezone: str
    holidays: List[str]
    doors: Dict[str, Dict[str, Any]]
    people: List[Dict[str, Any]]
    intercoms: List[Dict[str, Any]]
    tz: ZoneInfo = field(init=False)

    def __post_init__(self) -> None:
        self.tz = ZoneInfo(self.timezone)

    @classmethod
    def from_roster(cls, s: Dict[str, Any]) -> "Site":
        return cls(s["slug"], s["timezone"], s["holidays"], s["doors"], s["people"], s["intercoms"])

    def tagged(self, *tags: str) -> List[Dict[str, Any]]:
        return [p for p in self.people if p["tag"] in tags]


def _cred(p: Dict[str, Any], rnd: random.Random, pin_share: float = 0.0) -> Tuple[Tuple[str, str], ...]:
    if p.get("pin") and (not p.get("card") or rnd.random() < pin_share):
        return (("PIN", p["pin"]),)
    return (("Card", p["card"]),)


def _unknown_card(rnd: random.Random) -> Tuple[Tuple[str, str], ...]:
    return (("Card", f"{rnd.getrandbits(26):08x}"),)


class Day:
    """Builds one site's actions for one local day."""

    def __init__(self, site: Site, day: date) -> None:
        self.site, self.day = site, day
        self.rnd = random.Random(f"{site.slug}/{day.isoformat()}")
        self.actions: List[Action] = []
        holiday = day.isoformat() in site.holidays
        self.kind = "sunday" if holiday or day.weekday() == 6 else "saturday" if day.weekday() == 5 else "weekday"

    def at(self, hh: float, spread_min: float = 0.0) -> datetime:
        """A local time (hours, e.g. 8.5) plus up to `spread_min` minutes, in UTC."""
        minutes = hh * 60 + (self.rnd.uniform(0, spread_min) if spread_min else 0)
        local = datetime.combine(self.day, time(0), tzinfo=self.site.tz) + timedelta(minutes=minutes, seconds=self.rnd.randint(0, 59))
        return local.astimezone(timezone.utc)

    def between(self, start: float, end: float) -> datetime:
        return self.at(start, (end - start) * 60)

    def door(self, slot: str) -> Tuple[str, int]:
        d = self.site.doors[slot]
        return d["controller"], d["door"]

    def badge(self, when: datetime, slot: str, p: Dict[str, Any], side: str = "in", pin_share: float = 0.0) -> None:
        c, n = self.door(slot)
        self.actions.append(Action(when, "badge", c, n, side, _cred(p, self.rnd, pin_share), who=p["name"]))

    def stranger(self, when: datetime, slot: str) -> None:
        c, n = self.door(slot)
        self.actions.append(Action(when, "badge", c, n, "in", _unknown_card(self.rnd), who="unknown card"))

    def force(self, when: datetime, slot: str) -> None:
        c, n = self.door(slot)
        self.actions.append(Action(when, "force", c, n, seconds=self.rnd.uniform(5, 12), who="forced"))

    def hold(self, when: datetime, slot: str, p: Dict[str, Any]) -> None:
        c, n = self.door(slot)
        self.actions.append(Action(when, "hold", c, n, "in", _cred(p, self.rnd), seconds=self.rnd.uniform(80, 160), who=p["name"]))

    def vehicle(self, when: datetime, slot: str) -> None:
        c, n = self.door(slot)
        self.actions.append(Action(when, "vehicle", c, n, seconds=self.rnd.uniform(10, 20), who="vehicle"))

    def calls(self, start: float, end: float, every_min: Tuple[int, int], answered: float) -> None:
        for icom in self.site.intercoms:
            c, n = self.door(icom["door"])
            t = start * 60 + self.rnd.uniform(*every_min) / 2
            while t < end * 60:
                when = self.at(t / 60)
                self.actions.append(Action(when, "call", c, n, seconds=self.rnd.uniform(6, 25), answered=self.rnd.random() < answered,
                                           intercom=icom["id"], who=icom["name"]))
                t += self.rnd.uniform(*every_min)

    def chance(self, p: float) -> bool:
        return self.rnd.random() < p


def hq(d: Day) -> None:
    office = d.site.tagged("staff", "manager", "it")
    if d.kind == "weekday":
        for p in office:
            if d.chance(0.08):
                continue                                                      # out today
            arrive = d.between(7.5, 9.5)
            d.badge(arrive, "main_entrance" if d.chance(0.7) else "staff_entrance", p)
            if p["tag"] == "manager" or d.chance(0.5):
                d.badge(arrive + timedelta(minutes=d.rnd.uniform(3, 15)), "suite_door", p)
            if d.chance(0.3):
                out = d.between(11.75, 12.5)
                d.badge(out, "main_entrance", p, side="out")
                d.badge(out + timedelta(minutes=d.rnd.uniform(25, 60)), "main_entrance", p)
            if d.chance(0.4):
                d.badge(d.between(16.5, 18.5), "main_entrance", p, side="out")
            if p["tag"] == "it":
                for _ in range(d.rnd.randint(2, 4)):
                    d.badge(d.between(9, 17), "server_room", p)
        if office and d.chance(0.4):
            d.badge(d.between(10, 16), "server_room", d.rnd.choice(d.site.tagged("staff")))         # no access: denied
        for n, p in enumerate(d.site.tagged("cleaning")):
            if n == 0 and d.day.weekday() == 2:
                d.badge(d.between(17.6, 17.9), "staff_entrance", p, pin_share=0.3)                   # early: outside the cleaning hours
            d.badge(d.between(18.1, 18.6), "staff_entrance", p, pin_share=0.3)
        d.calls(9, 17, (45, 90), answered=0.85)
        if d.chance(0.8):
            d.force(d.between(10, 16), "staff_entrance")
    elif d.kind == "saturday":
        for p in d.rnd.sample(office, min(len(office), d.rnd.randint(5, 8))):
            d.badge(d.between(9, 13), "main_entrance", p)
    elif d.site.tagged("manager") and d.chance(0.5):
        d.badge(d.between(10, 15), "main_entrance", d.rnd.choice(d.site.tagged("manager")))
    for p in d.site.tagged("former"):                                         # works until the card expires, then tries now and then
        if d.kind == "weekday" and d.chance(0.35):
            d.badge(d.between(8, 9.5), "main_entrance", p)
    if d.chance(0.7):
        d.stranger(d.between(8, 20), "main_entrance")


def warehouse(d: Day) -> None:
    crew = d.site.tagged("employee", "manager")
    if d.kind in ("weekday", "saturday"):
        working = crew if d.kind == "weekday" else d.rnd.sample(crew, min(len(crew), d.rnd.randint(4, 6)))
        for p in working:
            if d.kind == "weekday" and d.chance(0.06):
                continue
            arrive = d.between(6.0, 7.25) if d.kind == "weekday" else d.between(7, 8)
            if arrive.astimezone(d.site.tz).hour < 7 and d.chance(0.5):
                d.badge(arrive - timedelta(minutes=2), "vehicle_gate", p)                            # before the gate opens for the day
            d.badge(arrive, "main_entrance" if d.chance(0.4) else "staff_entrance", p)
            if d.chance(0.4):
                d.badge(d.between(15, 16.5) if d.kind == "weekday" else d.between(11.5, 12.5), "main_entrance", p, side="out")
    if d.kind == "weekday":
        for _ in range(d.rnd.randint(14, 22)):
            d.vehicle(d.between(7, 17.8), "vehicle_gate")                   # the gate stands open in business hours
        drivers = d.site.tagged("driver")
        if drivers and d.chance(0.8):
            d.badge(d.between(6.5, 6.95), "vehicle_gate", d.rnd.choice(drivers))                    # early for the delivery hours: denied
        if crew and d.chance(0.6):
            d.hold(d.between(9, 15), "staff_entrance", d.rnd.choice(crew))  # the dock door propped open
    if d.chance(0.5):
        d.force(d.between(0, 23.9), "staff_entrance")
    if d.chance(0.3):
        d.stranger(d.between(6, 18), "main_entrance")


def apartments(d: Day) -> None:
    residents = d.site.tagged("resident")
    for p in residents:
        for _ in range(d.rnd.choices((0, 1, 2), weights=(4, 4, 2))[0]):
            slot = "lobby" if d.chance(0.65) else "garage"
            if d.chance(0.5):
                d.badge(d.between(7, 9), "lobby", p, side="out")
                d.badge(d.between(17, 20.5), slot, p)
            else:
                d.badge(d.between(9, 22), slot, p)
        if d.chance(0.25):
            d.badge(d.between(16, 22), "package_room", p)
        if d.chance(0.15):
            d.badge(d.between(6, 22), "amenity", p)
    if residents and d.chance(0.3):
        d.badge(d.between(23.1, 23.6), "amenity", d.rnd.choice(residents))   # after the gym closes: denied
    if d.kind != "sunday":
        for _ in range(d.rnd.randint(6, 10)):
            p = d.rnd.choice(d.site.tagged("courier"))
            t = d.between(9, 18)
            d.badge(t, "lobby", p)
            d.badge(t + timedelta(minutes=d.rnd.uniform(1, 3)), "package_room", p)
    if d.kind == "weekday":
        for p in d.site.tagged("property"):
            d.badge(d.between(8.75, 9.25), "lobby", p)
            for slot in ("package_room", "package_room", "amenity"):
                d.badge(d.between(9.5, 17), slot, p)
        for p in d.site.tagged("maintenance"):
            for slot in d.rnd.sample(["lobby", "garage", "package_room", "amenity"], 3):
                d.badge(d.between(8, 16), slot, p)
    for p in d.site.tagged("moved_out"):
        if d.chance(0.3):
            d.badge(d.between(18, 21), "lobby", p)                           # suspended: the controller no longer knows the card
    if d.chance(0.4):
        d.stranger(d.between(10, 23), "garage")
    d.calls(8, 21, (30, 60), answered=0.8)
    if d.chance(0.5):
        d.force(d.between(0, 23.9), "garage")


PLANS = {"demo-hq": hq, "demo-warehouse": warehouse, "demo-apartments": apartments}


def day(site: Site, local_day: date) -> List[Action]:
    d = Day(site, local_day)
    PLANS[site.slug](d)
    return sorted(d.actions, key=lambda a: (a.at, a.controller, a.door))


def between(site: Site, start: datetime, end: datetime) -> List[Action]:
    """Every action with start <= at < end, planned day by day in the site's time zone."""
    first = start.astimezone(site.tz).date() - timedelta(days=1)
    last = end.astimezone(site.tz).date()
    out: List[Action] = []
    d = first
    while d <= last:
        out.extend(a for a in day(site, d) if start <= a.at < end)
        d += timedelta(days=1)
    return out


def rows_per_controller(actions: List[Action]) -> Dict[str, int]:
    """About how many log rows the actions make on each controller (for the 30,000-row log): a badge that opens makes seven."""
    per = {"badge": 7, "hold": 10, "force": 4, "vehicle": 2, "call": 9}
    out: Dict[str, int] = {}
    for a in actions:
        out[a.controller] = out.get(a.controller, 0) + per[a.kind]
    return out

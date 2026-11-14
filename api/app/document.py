"""The site document: what an integrator edits for one site (ARCHITECTURE §6.1).

It holds outcomes, not controller objects: doors, weekly schedules, holiday calendars, access groups ("Staff: front and side doors, weekdays
6-20") and cardholders with their credentials. The compiler (app/compiler) turns it into each controller's own settings. Cardholders are
PhotonEntry's own records (decision 10); `person_id` links one to a PhotonID person when they will sign in to unlock from the app.

`problems()` checks everything the type checks cannot: references between parts, duplicate credentials, a door's controller. The compiler
refuses a document that has problems, so a controller never receives settings that half apply.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Day = Literal["mo", "tu", "we", "th", "fr", "sa", "su"]
DAYS: List[str] = ["mo", "tu", "we", "th", "fr", "sa", "su"]
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$|^24:00$")
# Ids are the cloud's own (UUIDs in the database); the document only needs them to be short, stable and safe inside a controller token.
_ID = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _check_id(v: str) -> str:
    if not _ID.match(v):
        raise ValueError("ids are 1 to 40 letters, digits, '-' or '_'")
    return v


class Window(_Strict):
    """Some days of the week, from `start` to `end` local time (site time zone). `end` may be 24:00."""
    days: List[Day] = Field(min_length=1)
    start: str
    end: str

    @field_validator("start", "end")
    @classmethod
    def _time(cls, v: str) -> str:
        if not _TIME.match(v):
            raise ValueError("times are HH:MM, 00:00 to 24:00")
        return v

    @model_validator(mode="after")
    def _order(self) -> "Window":
        if _minutes(self.end) <= _minutes(self.start):
            raise ValueError("a window ends after it starts (split a window that crosses midnight into two)")
        if len(set(self.days)) != len(self.days):
            raise ValueError("a day is listed twice")
        return self


class Schedule(_Strict):
    """When something applies. On the site's holidays it applies or not according to `on_holidays`."""
    id: str
    name: str = Field(min_length=1, max_length=64)
    windows: List[Window] = Field(min_length=1)
    on_holidays: Literal["off", "normal"] = "off"   # "off": not active on a holiday; "normal": holidays are ordinary days

    _id = field_validator("id")(_check_id)


class Holiday(_Strict):
    day: date
    name: str = Field(default="", max_length=64)


class HolidayCalendar(_Strict):
    id: str
    name: str = Field(min_length=1, max_length=64)
    days: List[Holiday] = Field(default_factory=list)

    _id = field_validator("id")(_check_id)


class Door(_Strict):
    """A door, on one controller, where it is the controller's door `controller_door` (its token, from the controller's inventory)."""
    id: str
    name: str = Field(min_length=1, max_length=64)
    controller_id: str
    controller_door: str = Field(min_length=1, max_length=64)
    access_time_s: int = Field(default=7, ge=1, le=600)        # unlocked after a valid credential
    open_too_long_s: int = Field(default=30, ge=1, le=3600)    # held open longer than this raises an alarm
    pre_alarm_s: int = Field(default=5, ge=0, le=600)          # warning before the held-open alarm
    unlock_schedule_id: Optional[str] = None                   # unlocked on its own during this schedule (front door 8-17)

    _id = field_validator("id")(_check_id)


class Intercom(_Strict):
    """An intercom at a door (ARCHITECTURE §3.4). It reads cards for the controller by Wiegand and takes calls; unlock from a call goes to
    `entry-link` on the door's controller, which knows the intercom by `id` and checks its relay password against `secret_sha256`."""
    id: str
    name: str = Field(min_length=1, max_length=64)
    door_id: str
    secret_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    _id = field_validator("id")(_check_id)


class Rule(_Strict):
    """These doors, during this schedule (none: at all times)."""
    doors: List[str] = Field(min_length=1)
    schedule_id: Optional[str] = None


class AccessGroup(_Strict):
    id: str
    name: str = Field(min_length=1, max_length=64)
    rules: List[Rule] = Field(min_length=1)
    installer_test: bool = False     # the installer's test setup: the only access a door not yet commissioned gets (decision 27)

    _id = field_validator("id")(_check_id)


class Card(_Strict):
    """A card number as a reader reports it. `facility` only for formats that carry one (26-bit H10301)."""
    format: Literal["h10301", "w34", "raw"] = "h10301"
    facility: Optional[int] = Field(default=None, ge=0, le=255)
    number: int = Field(ge=0)

    @model_validator(mode="after")
    def _fits(self) -> "Card":
        limits = {"h10301": 0xFFFF, "w34": 0xFFFFFFFF, "raw": (1 << 64) - 1}
        if self.number > limits[self.format]:
            raise ValueError(f"card number too large for {self.format}")
        if self.format == "h10301" and self.facility is None:
            raise ValueError("a 26-bit card has a facility code")
        if self.format != "h10301" and self.facility is not None:
            raise ValueError("only 26-bit cards have a facility code")
        return self


class Credential(_Strict):
    id: str
    kind: Literal["card", "pin"]
    card: Optional[Card] = None
    pin: Optional[str] = None
    enabled: bool = True
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None

    _id = field_validator("id")(_check_id)

    @model_validator(mode="after")
    def _shape(self) -> "Credential":
        if self.kind == "card" and (self.card is None or self.pin is not None):
            raise ValueError("a card credential has a card and no PIN")
        if self.kind == "pin":
            if self.pin is None or self.card is not None:
                raise ValueError("a PIN credential has a PIN and no card")
            if not re.fullmatch(r"\d{4,8}", self.pin):
                raise ValueError("a PIN is 4 to 8 digits")
        if self.valid_from and self.valid_to and self.valid_to <= self.valid_from:
            raise ValueError("valid_to is after valid_from")
        return self


class Cardholder(_Strict):
    id: str
    name: str = Field(min_length=1, max_length=128)
    person_id: Optional[UUID] = None          # a PhotonID person, when this cardholder signs in
    groups: List[str] = Field(default_factory=list)
    suspended: bool = False
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    credentials: List[Credential] = Field(default_factory=list)

    _id = field_validator("id")(_check_id)


class SiteDocument(_Strict):
    site_id: str
    timezone: str = "America/New_York"
    holiday_calendar_id: Optional[str] = None   # the site's calendar; schedules with on_holidays="off" are off on its days
    holiday_calendars: List[HolidayCalendar] = Field(default_factory=list)
    schedules: List[Schedule] = Field(default_factory=list)
    doors: List[Door] = Field(default_factory=list)
    access_groups: List[AccessGroup] = Field(default_factory=list)
    cardholders: List[Cardholder] = Field(default_factory=list)
    intercoms: List[Intercom] = Field(default_factory=list)
    # The doors that are in service (commissioned, ARCHITECTURE §7.2). None: no door is held back (documents made before decision 27, tests).
    # A door not in the list gets only installer-test groups' access and no unlock schedule.
    commissioned_doors: Optional[List[str]] = None

    def problems(self) -> List[str]:
        """Every reference and uniqueness problem, as plain sentences with a path. Empty: the document can be compiled."""
        out: List[str] = []

        def unique(kind: str, ids: List[str]) -> None:
            seen: Dict[str, int] = {}
            for i in ids:
                seen[i] = seen.get(i, 0) + 1
            out.extend(f"{kind} {i}: the id is used {n} times" for i, n in seen.items() if n > 1)

        unique("schedule", [s.id for s in self.schedules])
        unique("holiday calendar", [c.id for c in self.holiday_calendars])
        unique("door", [d.id for d in self.doors])
        unique("access group", [g.id for g in self.access_groups])
        unique("cardholder", [c.id for c in self.cardholders])
        unique("credential", [k.id for c in self.cardholders for k in c.credentials])
        unique("intercom", [i.id for i in self.intercoms])

        schedules = {s.id for s in self.schedules}
        doors = {d.id for d in self.doors}
        groups = {g.id for g in self.access_groups}
        if self.holiday_calendar_id and self.holiday_calendar_id not in {c.id for c in self.holiday_calendars}:
            out.append(f"site: holiday calendar {self.holiday_calendar_id} does not exist")
        places = [(d.controller_id, d.controller_door) for d in self.doors]
        for place in sorted({p for p in places if places.count(p) > 1}):
            out.append(f"controller {place[0]} door {place[1]}: mapped to more than one door")
        for d in self.doors:
            if d.unlock_schedule_id and d.unlock_schedule_id not in schedules:
                out.append(f"door {d.id}: unlock schedule {d.unlock_schedule_id} does not exist")
        out.extend(f"intercom {i.id}: door {i.door_id} does not exist" for i in self.intercoms if i.door_id not in doors)
        for g in self.access_groups:
            for n, r in enumerate(g.rules):
                out.extend(f"access group {g.id} rule {n + 1}: door {x} does not exist" for x in r.doors if x not in doors)
                if r.schedule_id and r.schedule_id not in schedules:
                    out.append(f"access group {g.id} rule {n + 1}: schedule {r.schedule_id} does not exist")
        cards: Dict[tuple, str] = {}
        pins: Dict[str, str] = {}
        for c in self.cardholders:
            out.extend(f"cardholder {c.id}: access group {x} does not exist" for x in c.groups if x not in groups)
            for k in c.credentials:
                if k.card is not None:
                    key = (k.card.format, k.card.facility, k.card.number)
                    if key in cards and cards[key] != c.id:
                        out.append(f"cardholder {c.id}: card {k.id} is also held by cardholder {cards[key]}")
                    cards.setdefault(key, c.id)
                if k.pin is not None:
                    # A PIN on its own identifies its holder at a keypad, so two people may not share one.
                    if k.pin in pins and pins[k.pin] != c.id:
                        out.append(f"cardholder {c.id}: PIN {k.id} is the same as a PIN of cardholder {pins[k.pin]}")
                    pins.setdefault(k.pin, c.id)
        return out

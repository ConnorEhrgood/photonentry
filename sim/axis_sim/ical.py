"""The iCalendar subset Axis schedules accept (axsch `ScheduleDefinition`, `ExceptionScheduleDefinition`), parsed and evaluated.

Axis documents: local time only (no UTC `Z`, no TZID, no VTIMEZONE); `DTEND` makes an interval; `DTSTART;VALUE=DATE` is a whole day; RRULE
frequencies `WEEKLY` (with `BYDAY`), `DAILY`, `MONTHLY` (`BYMONTHDAY`), `YEARLY` with `INTERVAL`, `COUNT`, `UNTIL`; `RDATE` with DATE values.
The simulator implements that much, refuses everything else with `InvalidSchedule` (the device's `ter:InvalidScheduleFault`), and supports
only interval schedules (with DTEND or whole days): pulse schedules (DTSTART only) are accepted and are never "active", as on the device.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

DAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]


class InvalidSchedule(Exception):
    pass


@dataclass
class Event:
    start: datetime
    duration: Optional[timedelta]          # None: a pulse
    freq: Optional[str] = None
    interval: int = 1
    byday: List[int] = field(default_factory=list)
    bymonthday: List[int] = field(default_factory=list)
    until: Optional[datetime] = None
    count: Optional[int] = None
    rdates: List[date] = field(default_factory=list)


def _local(value: str) -> datetime:
    if value.endswith("Z") or len(value) != 15 or value[8] != "T":
        raise InvalidSchedule(f"only local DATE-TIME values (YYYYMMDDTHHMMSS) are supported: {value!r}")
    try:
        return datetime.strptime(value, "%Y%m%dT%H%M%S")
    except ValueError as e:
        raise InvalidSchedule(str(e)) from e


def _date(value: str) -> date:
    try:
        return datetime.strptime(value.strip(), "%Y%m%d").date()
    except ValueError as e:
        raise InvalidSchedule(str(e)) from e


def _rrule(ev: Event, value: str) -> None:
    for part in value.split(";"):
        name, _, v = part.partition("=")
        if name == "FREQ":
            if v not in ("WEEKLY", "DAILY", "MONTHLY", "YEARLY"):
                raise InvalidSchedule(f"FREQ={v} is not supported by the simulator")
            ev.freq = v
        elif name == "INTERVAL":
            ev.interval = int(v)
            if ev.interval < 1:
                raise InvalidSchedule("INTERVAL must be at least 1")
        elif name == "BYDAY":
            try:
                ev.byday = sorted(DAYS.index(d) for d in v.split(","))
            except ValueError as e:
                raise InvalidSchedule(f"BYDAY={v}") from e
        elif name == "BYMONTHDAY":
            ev.bymonthday = [int(d) for d in v.split(",")]
        elif name == "UNTIL":
            ev.until = _local(v) if "T" in v else datetime.combine(_date(v), datetime.max.time())
        elif name == "COUNT":
            ev.count = int(v)
        else:
            raise InvalidSchedule(f"RRULE part {name} is not supported")
    if ev.freq is None:
        raise InvalidSchedule("RRULE without FREQ")


def parse(text: str) -> List[Event]:
    """The VEVENTs of a VCALENDAR. Empty text or None: no events."""
    if not text:
        return []
    lines = [ln.strip() for ln in text.replace("\r\n", "\n").split("\n") if ln.strip()]
    if not lines or lines[0] != "BEGIN:VCALENDAR" or lines[-1].rstrip(";") != "END:VCALENDAR":
        raise InvalidSchedule("not a VCALENDAR")
    events: List[Event] = []
    current: Optional[Dict[str, str]] = None
    for ln in lines[1:-1]:
        if ln == "BEGIN:VEVENT":
            current = {}
        elif ln == "END:VEVENT":
            if current is None:
                raise InvalidSchedule("END:VEVENT without BEGIN")
            events.append(_event(current))
            current = None
        elif current is not None:
            key, sep, value = ln.partition(":")
            if not sep:
                raise InvalidSchedule(f"bad line {ln!r}")
            current[key] = current[key] + "," + value if key == "RDATE;VALUE=DATE" and key in current else value
        elif ln.split(":")[0] not in ("PRODID", "VERSION", "CALSCALE"):
            raise InvalidSchedule(f"unsupported calendar line {ln!r}")
    if current is not None:
        raise InvalidSchedule("VEVENT not ended")
    return events


def _event(p: Dict[str, str]) -> Event:
    if "DTSTART;VALUE=DATE" in p:
        d = _date(p["DTSTART;VALUE=DATE"])
        ev = Event(start=datetime(d.year, d.month, d.day), duration=timedelta(days=1))
    elif "DTSTART" in p:
        start = _local(p["DTSTART"])
        if "DTEND" in p:
            end = _local(p["DTEND"])
            if end <= start:
                raise InvalidSchedule("DTEND before DTSTART")
            ev = Event(start=start, duration=end - start)
        else:
            ev = Event(start=start, duration=None)
    else:
        raise InvalidSchedule("VEVENT without DTSTART")
    for key, value in p.items():
        if key == "RRULE":
            _rrule(ev, value)
        elif key == "RDATE;VALUE=DATE":
            ev.rdates = [_date(v) for v in value.split(",")]
        elif key.split(";")[0] in ("DTSTART", "DTEND", "UID", "DTSTAMP", "SUMMARY", "DESCRIPTION"):
            continue
        else:
            raise InvalidSchedule(f"unsupported property {key}")
    return ev


def _occurs_on(ev: Event, day: date) -> bool:
    first = ev.start.date()
    if day < first:
        return False
    if day in ev.rdates:
        return True
    if ev.freq is None:
        return day == first
    if ev.freq == "DAILY":
        return (day - first).days % ev.interval == 0
    if ev.freq == "WEEKLY":
        days = ev.byday or [first.weekday()]
        weeks = ((day - timedelta(days=day.weekday())) - (first - timedelta(days=first.weekday()))).days // 7
        return day.weekday() in days and weeks % ev.interval == 0
    if ev.freq == "MONTHLY":
        months = (day.year - first.year) * 12 + day.month - first.month
        return months % ev.interval == 0 and day.day in (ev.bymonthday or [first.day])
    return (day.month, day.day) == (first.month, first.day) and (day.year - first.year) % ev.interval == 0   # YEARLY


def active(events: List[Event], at: datetime) -> bool:
    """Whether any interval event covers local time `at`. COUNT is not evaluated (treated as unlimited): see the module note."""
    for ev in events:
        if ev.duration is None:
            continue
        span = ev.duration.days + 1
        for back in range(span + 1):
            day = at.date() - timedelta(days=back)
            if not _occurs_on(ev, day):
                continue
            start = datetime.combine(day, ev.start.time())
            if ev.until is not None and start > ev.until:
                continue
            if start <= at < start + ev.duration:
                return True
    return False

"""Weekly windows and holidays as the iCalendar text Axis schedules take (axsch `ScheduleDefinition` and `ExceptionScheduleDefinition`).

Axis's subset: local time only (no UTC, no VTIMEZONE), so the controller's clock must be in the site's time zone; `DTEND` makes an interval
schedule; `DTSTART;VALUE=DATE` is a whole day. Each window becomes one weekly VEVENT whose DTSTART falls on its first listed day of a
reference week (Monday 2000-01-03), so DTSTART is always one of its own occurrences. Holidays become one whole-day VEVENT each.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable, List

from app.document import DAYS, Window

REFERENCE_MONDAY = date(2000, 1, 3)


def _calendar(events: List[str]) -> str:
    return "BEGIN:VCALENDAR\r\nPRODID:-//Photon//PhotonEntry//EN\r\nVERSION:2.0\r\n" + "".join(events) + "END:VCALENDAR\r\n"


def _stamp(day: date, hhmm: str) -> str:
    if hhmm == "24:00":
        return (day + timedelta(days=1)).strftime("%Y%m%d") + "T000000"
    return day.strftime("%Y%m%d") + "T" + hhmm.replace(":", "") + "00"


def weekly(windows: Iterable[Window]) -> str:
    events = []
    for w in windows:
        days = sorted(w.days, key=DAYS.index)
        first = REFERENCE_MONDAY + timedelta(days=DAYS.index(days[0]))
        events.append("BEGIN:VEVENT\r\n"
                      f"DTSTART:{_stamp(first, w.start)}\r\n"
                      f"DTEND:{_stamp(first, w.end)}\r\n"
                      f"RRULE:FREQ=WEEKLY;BYDAY={','.join(d.upper() for d in days)}\r\n"
                      "END:VEVENT\r\n")
    return _calendar(events)


def whole_days(days: Iterable[date]) -> str:
    """Each date as a 24-hour interval; empty: a calendar with no events (never active)."""
    unique = sorted(set(days))
    if not unique:
        return ""
    return _calendar([f"BEGIN:VEVENT\r\nDTSTART;VALUE=DATE:{d.strftime('%Y%m%d')}\r\nEND:VEVENT\r\n" for d in unique])

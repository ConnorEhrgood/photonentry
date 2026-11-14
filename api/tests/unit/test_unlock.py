"""When a weekly schedule is active (app/unlock.py), as the controller decides it: days, an end of 24:00, holidays."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.unlock import schedule_active

NY = ZoneInfo("America/New_York")
WEEK = [{"days": ["mo", "tu", "we", "th", "fr"], "start": "08:00", "end": "18:00"}, {"days": ["sa"], "start": "20:00", "end": "24:00"}]


def at(y, m, d, h, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=NY)


def test_windows_days_and_the_end_of_the_day():
    assert schedule_active(WEEK, "off", set(), at(2026, 11, 16, 8))            # Monday 08:00: starts
    assert not schedule_active(WEEK, "off", set(), at(2026, 11, 16, 18))       # 18:00: ended
    assert not schedule_active(WEEK, "off", set(), at(2026, 11, 15, 10))       # Sunday
    assert schedule_active(WEEK, "off", set(), at(2026, 11, 21, 23, 59))       # Saturday until 24:00
    assert not schedule_active(WEEK, "off", set(), at(2026, 11, 21, 19, 59))


def test_holidays_off_or_ordinary():
    christmas = {date(2026, 12, 25)}
    assert not schedule_active(WEEK, "off", christmas, at(2026, 12, 25, 10))    # a Friday, but a holiday
    assert schedule_active(WEEK, "normal", christmas, at(2026, 12, 25, 10))


def test_the_routes_clock_is_utc():
    from datetime import timezone
    from app.routes import unlock as route
    assert route._now().tzinfo == timezone.utc

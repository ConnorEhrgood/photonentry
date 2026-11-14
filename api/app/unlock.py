"""Opening one's own doors from the app (ARCHITECTURE §10.2; decision 25). CRITICAL: it decides which doors a person may open remotely.

A person signs in with PhotonID; their PhotonEntry access (any role: every role has `entry.unlock.own`, the door user role has only that) is
linked to **their own cardholder record** in that organization. They may open, now, exactly the doors that record would let their card open now:
- the cardholder is not suspended and is inside its validity;
- one of its access groups has a rule for the door whose schedule is active now (the site's time zone; off on the site's holidays when the
  schedule says so), or the rule is "at all times";
- the door is commissioned (decision 27), unless the group is the installer's test group;
- the door is not locked down, and its controller is in service.
The controller still has the last word (a door locked down meanwhile ignores the command).

**The system reads, scoped here.** Door users may not read doors, groups or cardholders (row-level security); this module reads them as the
system, only for the person's own linked cardholders, and the API calls it only for the signed-in person.

**Linking:** an admin links a cardholder to a person, or it happens by itself when exactly one cardholder of the organization, not yet linked,
has the person's email address (the address their PhotonID invitation went to; the person holds an Entry role there).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, List, Optional, Set
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (AccessGroup, Cardholder, CardholderGroup, Controller, Door, HolidayCalendar, Lockdown, Person, Schedule, Site)

DAY_CODES = ["mo", "tu", "we", "th", "fr", "sa", "su"]


@dataclass(frozen=True)
class Option:
    door_id: str
    door: str
    site_id: str
    site: str
    can_open: bool
    why: str            # "" | outside_schedule | not_commissioned | locked_down | out_of_service


def link_by_email(db: Session, tenant_id: uuid.UUID, person: Person) -> Optional[Cardholder]:
    """The person's cardholder, linking one by email when there is exactly one candidate (and none is linked yet)."""
    mine = db.execute(select(Cardholder).where(Cardholder.tenant_id == tenant_id, Cardholder.person_id == person.id)).scalars().first()
    if mine is not None or not person.email:
        return mine
    candidates = db.execute(select(Cardholder).where(Cardholder.tenant_id == tenant_id, Cardholder.person_id.is_(None),
                                                    func.lower(Cardholder.email) == person.email.lower())).scalars().all()
    if len(candidates) != 1:
        return None                                  # none, or ambiguous: an admin links by hand
    candidates[0].person_id = person.id
    db.flush()
    return candidates[0]


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def schedule_active(windows: List[dict], on_holidays: str, holidays: Set[date], local: datetime) -> bool:
    """Is a weekly schedule active at this local time? `end` may be 24:00."""
    if on_holidays == "off" and local.date() in holidays:
        return False
    day, now = DAY_CODES[local.weekday()], local.hour * 60 + local.minute
    return any(day in w["days"] and _minutes(w["start"]) <= now < _minutes(w["end"]) for w in windows)


def _valid(h: Cardholder, now: datetime) -> bool:
    return not h.suspended and (h.valid_from is None or h.valid_from <= now) and (h.valid_to is None or now < h.valid_to)


def options(db: Session, tenant_id: uuid.UUID, holders: List[Cardholder], now: datetime) -> List[Option]:
    """Every door the person's cardholders have a rule for, with whether it opens now and why not. Sorted by site, then door."""
    live = [h for h in holders if _valid(h, now)]
    if not live:
        return []
    memberships = db.execute(select(CardholderGroup).where(CardholderGroup.cardholder_id.in_([h.id for h in live]))).scalars().all()
    groups = {g.id: g for g in db.execute(select(AccessGroup).where(AccessGroup.id.in_([m.group_id for m in memberships]))).scalars()}
    site_ids = {g.site_id for g in groups.values()}
    sites = {s.id: s for s in db.execute(select(Site).where(Site.id.in_(site_ids), Site.tenant_id == tenant_id, Site.status == "active")).scalars()}
    doors = {d.id: d for d in db.execute(select(Door).where(Door.site_id.in_(list(sites)))).scalars()}
    schedules = {s.id: s for s in db.execute(select(Schedule).where(Schedule.site_id.in_(list(sites)))).scalars()}
    calendars = {c.site_id: {date.fromisoformat(d["day"]) for d in c.days} for c in
                 db.execute(select(HolidayCalendar).where(HolidayCalendar.site_id.in_(list(sites)))).scalars()}
    controllers = {c.id: c for c in db.execute(select(Controller).where(Controller.id.in_({d.controller_id for d in doors.values()}))).scalars()}
    locked: Set[str] = set()
    for lk in db.execute(select(Lockdown).where(Lockdown.site_id.in_(list(sites)), Lockdown.ended_at.is_(None))).scalars():
        locked.update(lk.door_ids)
    from app.sitedoc import in_service
    commissioned = set(in_service(db, list(doors.values())))

    best: Dict[str, Option] = {}
    for g in sorted(groups.values(), key=lambda g: g.name):          # a fixed order, so what is shown never depends on chance
        site = sites.get(g.site_id)
        if site is None:
            continue
        local = now.astimezone(ZoneInfo(site.timezone or "UTC"))
        for rule in g.rules:
            sched = schedules.get(uuid.UUID(rule["schedule_id"])) if rule.get("schedule_id") else None
            in_time = True if not rule.get("schedule_id") else (
                sched is not None and schedule_active(sched.windows, sched.on_holidays, calendars.get(site.id, set()), local))
            for door_id in rule["doors"]:
                d = doors.get(uuid.UUID(door_id))
                if d is None:
                    continue
                c = controllers.get(d.controller_id)
                why = ("out_of_service" if c is None or c.state != "claimed" else
                       "not_commissioned" if str(d.id) not in commissioned and not g.installer_test else
                       "locked_down" if str(d.id) in locked else
                       "" if in_time else "outside_schedule")
                opt = Option(str(d.id), d.name, str(site.id), site.name, why == "", why)
                prev = best.get(opt.door_id)
                if prev is None or (opt.can_open and not prev.can_open):
                    best[opt.door_id] = opt          # one group that opens the door is enough
    return sorted(best.values(), key=lambda o: (o.site, o.door))


"""A site's access settings, assembled from the database into the site document (app/document.py) that the compiler takes (CRITICAL: it decides
which people and which credentials reach which controller).

Runs in the publishing admin's own session, so row-level security applies to every row read. Card numbers and PINs are unsealed here and
nowhere else: they leave only inside the compiled settings for a controller. Intercoms' relay passwords are unsealed here only to hash them.

A cardholder belongs to the site's document when they are in at least one of the site's access groups, and only that site's groups are listed
for them. Ids in the document are the database's UUIDs as text (they become controller tokens such as `pe-c-<uuid>`).
"""
from __future__ import annotations

import hashlib
import uuid
from typing import Dict, List

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import commissioning, crypto
from app.document import SiteDocument
from app.models import AccessGroup, Cardholder, CardholderGroup, Commissioning, Credential, Door, HolidayCalendar, Intercom, Schedule, Site, utcnow
from app.passes import ended_ids


def build(db: Session, site: Site) -> SiteDocument:
    sid = site.id
    doors = db.execute(select(Door).where(Door.site_id == sid).order_by(Door.name)).scalars().all()
    schedules = db.execute(select(Schedule).where(Schedule.site_id == sid)).scalars().all()
    groups = db.execute(select(AccessGroup).where(AccessGroup.site_id == sid)).scalars().all()
    intercoms = db.execute(select(Intercom).where(Intercom.site_id == sid)).scalars().all()
    calendar = db.get(HolidayCalendar, sid)
    memberships = db.execute(select(CardholderGroup).where(CardholderGroup.site_id == sid)).scalars().all()
    over = ended_ids(db, sid, utcnow())          # visitors' passes that ended more than a day ago are no longer sent (app/passes.py)
    by_holder: Dict[uuid.UUID, List[str]] = {}
    for m in memberships:
        if m.cardholder_id in over:
            continue
        by_holder.setdefault(m.cardholder_id, []).append(str(m.group_id))
    holders = db.execute(select(Cardholder).where(Cardholder.id.in_(list(by_holder)))).scalars().all() if by_holder else []
    creds = db.execute(select(Credential).where(Credential.cardholder_id.in_([h.id for h in holders]))).scalars().all() if holders else []
    creds_by_holder: Dict[uuid.UUID, List[Credential]] = {}
    for c in creds:
        creds_by_holder.setdefault(c.cardholder_id, []).append(c)

    doc = {
        "site_id": str(sid),
        "timezone": site.timezone or "UTC",
        "holiday_calendar_id": "site" if calendar is not None else None,
        "holiday_calendars": [{"id": "site", "name": "Holidays", "days": calendar.days}] if calendar is not None else [],
        "schedules": [{"id": str(s.id), "name": s.name, "windows": s.windows, "on_holidays": s.on_holidays} for s in schedules],
        "doors": [{"id": str(d.id), "name": d.name, "controller_id": str(d.controller_id), "controller_door": d.controller_door,
                   "access_time_s": d.access_time_s, "open_too_long_s": d.open_too_long_s, "pre_alarm_s": d.pre_alarm_s,
                   "unlock_schedule_id": str(d.unlock_schedule_id) if d.unlock_schedule_id else None} for d in doors],
        "access_groups": [{"id": str(g.id), "name": g.name, "rules": g.rules, "installer_test": g.installer_test} for g in groups],
        "commissioned_doors": in_service(db, doors),
        "cardholders": [_holder(h, sorted(by_holder[h.id]), creds_by_holder.get(h.id, [])) for h in holders],
        # Only the hash of each relay password leaves for the controller: entry-link checks the intercom's password against it.
        "intercoms": [{"id": str(i.id), "name": i.name, "door_id": str(i.door_id),
                       "secret_sha256": hashlib.sha256(crypto.unseal(i.relay_secret_sealed).encode()).hexdigest()} for i in intercoms],
    }
    return SiteDocument.model_validate(doc)


def in_service(db: Session, doors: List[Door]) -> List[str]:
    """The site's doors that are commissioned now (app/commissioning.py): only they get the customer's real settings (decision 27)."""
    newest: Dict[uuid.UUID, Commissioning] = {}
    for c in db.execute(select(Commissioning).where(Commissioning.door_id.in_([d.id for d in doors])).order_by(Commissioning.signed_at)).scalars():
        newest[c.door_id] = c
    out = []
    for d in doors:
        c = newest.get(d.id)
        if commissioning.status(c.controller_door if c else None, bool(c and c.voided_at), d.controller_door).in_service:
            out.append(str(d.id))
    return sorted(out)


def _holder(h: Cardholder, groups: List[str], creds: List[Credential]) -> dict:
    return {"id": str(h.id), "name": h.name, "person_id": h.person_id, "groups": groups, "suspended": h.suspended,
            "valid_from": h.valid_from, "valid_to": h.valid_to, "credentials": [_credential(c) for c in creds]}


def _credential(c: Credential) -> dict:
    value = crypto.unseal(c.value_sealed)
    out = {"id": str(c.id), "kind": c.kind, "enabled": c.enabled, "valid_from": c.valid_from, "valid_to": c.valid_to}
    if c.kind == "card":
        out["card"] = {"format": c.card_format, "facility": c.card_facility, "number": int(value)}
    else:
        out["pin"] = value
    return out

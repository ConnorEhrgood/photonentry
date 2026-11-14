"""Seeding and removing the demo organization's PhotonEntry part (docs/DEMO.md §2).

`seed` sets the demo up through the API's own route functions, so every check, audit entry and publish is the one a person's request makes. It
acts as "Demo seed", the organization's owner by role but no person. It runs in a one-shot container as the database owner (row-level
security does not apply to it), and every write is scoped to the demo organization in code.

`seed` starts from nothing: it removes whatever an earlier seed left first, so a second run gives the same demo. It refuses any organization the
directory has not marked `demo`. `remove` deletes every PhotonEntry row of the demo organization. The directory's copies (the organization, its
sites, who has access) are the directory's and stay.
"""
from __future__ import annotations

import time
import uuid
from datetime import date, datetime, time as dtime, timedelta
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app import demo
from app.access import Grant
from app.compiler.wiegand import card_data
from app.crypto import unseal
from app.deps import Ctx, Who
from app.document import Card, Rule
from app.models import (AccessGroup, AuditLog, CallMatch, Cardholder, CardholderGroup, Commissioning, ConsoleFeedToken, Controller,
                        Credential, Door, DoorAlarm, DoorEvent, GuardCursor, GuardLink, HolidayCalendar, Intercom, License, LinkCommand, Lockdown,
                        Schedule, SettingsVersion, Site, SitePublication, Tenant, VisitorPass, VoxLink)
from app.routes import cardholders as holders_route
from app.routes import commissioning as commissioning_route
from app.routes import config as config_route
from app.routes import controllers as controllers_route
from app.routes import intercoms as intercoms_route
from app.routes import passes as passes_route

# Every table with the organization's PhotonEntry rows, children first. Not the directory's: tenant, site, access, person.
OWNED = (DoorEvent, DoorAlarm, CallMatch, GuardCursor, LinkCommand, SettingsVersion, SitePublication, Commissioning, VisitorPass, Intercom,
         Credential, CardholderGroup, Cardholder, AccessGroup, Door, Schedule, HolidayCalendar, Lockdown, License, GuardLink, VoxLink,
         ConsoleFeedToken, Controller, AuditLog)


class SeedError(Exception):
    pass


def _ctx() -> Ctx:
    return Ctx(Who(demo.SEED_ACTOR, "", "Demo seed", "", False), demo.ORG, Grant(role="owner"))


def _never_mail(to: str, subject: str, body: str) -> Optional[str]:  # noqa: ARG001
    return None


def check(db: Session) -> Tenant:
    """The demo organization, as the directory sent it; refuses anything else."""
    t = db.get(Tenant, demo.ORG)
    if t is None:
        raise SeedError(f"the directory has not sent organization {demo.ORG} to PhotonEntry (is entry switched on for it?)")
    if not t.demo:
        raise SeedError(f"organization {t.slug or t.id} is not marked demo by the directory: nothing seeded")
    if t.status != "active":
        raise SeedError(f"organization {t.slug or t.id} is {t.status}")
    for s in demo.SITES:
        site = db.get(Site, s.id)
        if site is None or site.tenant_id != demo.ORG or site.status != "active":
            raise SeedError(f"site {s.slug} ({s.id}) is not here yet, or not active")
    return t


def remove(db: Session) -> Dict[str, int]:
    """Delete every PhotonEntry row of the demo organization. Refuses an organization not marked demo. Returns the rows deleted per table."""
    t = db.get(Tenant, demo.ORG)
    if t is not None and not t.demo:
        raise SeedError(f"organization {t.slug or t.id} is not marked demo by the directory: nothing removed")
    counts = {}
    for model in OWNED:
        counts[model.__tablename__] = db.execute(delete(model).where(model.tenant_id == demo.ORG)).rowcount
    db.commit()
    return {k: v for k, v in counts.items() if v}


def _wait(db: Session, what: str, ready: Callable[[], bool], timeout_s: float, sleep: Callable[[float], None]) -> None:
    deadline = time.monotonic() + timeout_s
    while True:
        db.expire_all()
        if ready():
            return
        if time.monotonic() >= deadline:
            raise SeedError(f"timed out waiting for {what}")
        sleep(1.0)


def _local(site: Site, day: date, hh: int, mm: int = 0) -> datetime:
    return datetime.combine(day, dtime(hh, mm), tzinfo=ZoneInfo(site.timezone or "UTC"))


def seed(db: Session, claims: Dict[str, str], now: datetime, timeout_s: float = 180.0,
         sleep: Callable[[float], None] = time.sleep, store: Any = None) -> Dict[str, Any]:
    """Set the demo up from the simulators' claim codes ({controller key: code}). Returns the roster the simulators drive."""
    check(db)
    missing = sorted(set(demo.CONTROLLERS) - set(claims))
    if missing:
        raise SeedError(f"no claim code for {', '.join(missing)}")
    remove(db)
    ctx = _ctx()
    if store is None:
        from app.db import SystemSession
        from app.link.pgstore import PgStore
        store = PgStore(SystemSession)
    link = SimpleNamespace(store=store)

    # 1. The controllers, claimed to their sites and marked simulated.
    controllers: Dict[str, uuid.UUID] = {}
    for s in demo.SITES:
        for c in s.controllers:
            got = controllers_route.claim(controllers_route.ClaimIn(code=claims[c.key], site_id=s.id, name=c.name), ctx, db, link)
            controllers[c.key] = uuid.UUID(got["id"])
            db.get(Controller, controllers[c.key]).simulated = True
    db.commit()

    def inventories() -> bool:
        return all(len((db.get(Controller, cid).inventory or {}).get("doors", [])) == demo.CONTROLLERS[k].doors for k, cid in controllers.items())
    _wait(db, "every controller's inventory", inventories, timeout_s, sleep)

    roster: Dict[str, Any] = {"organization": str(demo.ORG), "generated_at": now.isoformat(), "history_days": demo.HISTORY_DAYS, "sites": []}
    everyone = demo.people()
    for s in demo.SITES:
        site = db.get(Site, s.id)
        doors: Dict[str, uuid.UUID] = {}
        groups: Dict[str, uuid.UUID] = {}
        schedules: Dict[str, uuid.UUID] = {}
        specs = {d.slot: d for d in s.doors}

        # 2. The templates, with the doors renamed.
        for key, slots, options in s.templates:
            chosen = {}
            for slot in slots:
                d = specs[slot]
                inv = db.get(Controller, controllers[d.controller]).inventory["doors"]
                token = next(x["token"] for x in inv if x["token"].endswith(f":door{d.door}"))
                chosen[slot] = config_route.TemplateDoor(controller_id=controllers[d.controller], controller_door=token, name=d.name)
            out = config_route.apply_template(s.id, key, config_route.ApplyTemplateIn(doors=chosen, options=options), ctx, db)
            doors.update({k: uuid.UUID(v) for k, v in out["doors"].items()})
            groups.update({k: uuid.UUID(v) for k, v in out["groups"].items()})
            schedules.update({k: uuid.UUID(v) for k, v in out["schedules"].items()})
        if s.visitors_door:
            g = config_route.add_group(s.id, config_route.GroupIn(name="Visitors", for_visitors=True, rules=[
                Rule(doors=[str(doors[s.visitors_door])], schedule_id=str(schedules["extended"]) if "extended" in schedules else None)]), ctx, db)
            groups["visitors"] = uuid.UUID(g["id"])

        # 3. The people, their groups and cards.
        site_people = []
        for p in (x for x in everyone if x.site == s.slug):
            h = holders_route.add_cardholder(holders_route.CardholderIn(name=p.name, ref=p.ref, email=p.email, suspended=p.suspended), ctx, db)
            hid = uuid.UUID(h["id"])
            holders_route.set_groups(hid, holders_route.GroupsIn(group_ids=[groups[g] for g in p.groups if g in groups]), ctx, db)
            card = Card(format="h10301", facility=s.facility, number=p.card) if p.card is not None else None
            if card is not None:
                holders_route.add_credential(hid, holders_route.CredentialIn(
                    kind="card", card=card, valid_to=now - timedelta(days=12) if p.card_expired else None), ctx, db)
            if p.pin:
                holders_route.add_credential(hid, holders_route.CredentialIn(kind="pin", pin=p.pin), ctx, db)
            site_people.append({"name": p.name, "tag": p.tag, "card": card_data(card) if card else None, "pin": p.pin, "id": str(hid)})

        # 4. The intercoms, reaching entry-link on the simulators' loopback.
        intercoms = []
        for i in s.intercoms:
            d = specs[i.door]
            port = demo.CONTROLLERS[d.controller].local_port
            got = intercoms_route.add_intercom(s.id, intercoms_route.IntercomIn(name=i.name, door_id=doors[i.door], model=i.model, mac=i.mac,
                                                                                 relay_address=f"127.0.0.1:{port}"), ctx, db, None)
            row = db.get(Intercom, uuid.UUID(got["id"]))
            row.simulated = True
            db.commit()
            intercoms.append({"id": got["id"], "name": i.name, "door": i.door, "mac": i.mac,
                              "provision_path": f"/provision/v1/{unseal(row.provision_token_sealed)}/"})

        # 5. Published, then every door commissioned (each signature sends the real settings to the door's controller).
        config_route.publish(s.id, ctx, db)
        lic = None
        if s.state == "WV":
            lic = commissioning_route.add_license(commissioning_route.LicenseIn(
                owner="organization", state="WV", kind="wv_sp_lv", holder=demo.INSTALLER, number="DEMO-0001",
                expires_on=now.date() + timedelta(days=730)), ctx, db)["id"]
        for d in s.doors:
            commissioning_route.sign(s.id, doors[d.slot], commissioning_route.CommissioningIn(
                jurisdiction=s.state, lock_type=d.lock_type, failure_state="fail_secure", egress=d.egress, special_locking="none",
                fire_release="none_present", rex_checked=True, contact_checked=True, ahj_reference="Demo permit (fictional)",
                installer=demo.INSTALLER, license_id=uuid.UUID(lic) if lic else None, notes="The demo organization's simulated door."), ctx, db)

        # 6. Two visitors' passes, never emailed.
        if "visitors" in groups:
            today = now.astimezone(ZoneInfo(site.timezone or "UTC")).date()
            for name, start, end in (("Morgan Visitor", now + timedelta(minutes=1), now + timedelta(hours=8)),
                                     ("Riley Guest", _local(site, today + timedelta(days=1), 9), _local(site, today + timedelta(days=1), 17))):
                passes_route.issue(s.id, passes_route.PassIn(visitor_name=name, group_id=groups["visitors"], valid_from=start, valid_to=end),
                                   ctx, db, _never_mail)

        cal = db.get(HolidayCalendar, s.id)
        roster["sites"].append({
            "slug": s.slug, "timezone": site.timezone, "holidays": [d["day"] for d in (cal.days if cal else [])],
            "controllers": {c.key: {"id": str(controllers[c.key]), "doors": c.doors, "model": c.model, "local_port": c.local_port}
                            for c in s.controllers},
            "doors": {d.slot: {"controller": d.controller, "door": d.door, "name": d.name, "id": str(doors[d.slot])} for d in s.doors},
            "people": site_people, "intercoms": intercoms})

    # 7. Done when every controller runs its newest settings.
    def applied() -> bool:
        for cid in controllers.values():
            latest = db.execute(select(func.max(SettingsVersion.version)).where(SettingsVersion.controller_id == cid)).scalar() or 0
            if latest == 0 or db.get(Controller, cid).applied_version != latest:
                return False
        return True
    _wait(db, "every controller to apply its settings", applied, timeout_s, sleep)
    return roster


def summary(db: Session) -> Dict[str, int]:
    """What the demo holds now (for `status` and the tests)."""
    def count(model: Any) -> int:
        return db.execute(select(func.count()).select_from(model).where(model.tenant_id == demo.ORG)).scalar() or 0
    return {m.__tablename__: count(m) for m in (Controller, Door, Cardholder, Credential, Intercom, Commissioning, VisitorPass, DoorEvent)}


__all__: List[str] = ["SeedError", "check", "remove", "seed", "summary"]

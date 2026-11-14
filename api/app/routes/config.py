"""A site's access configuration: its doors, schedules, holiday calendar and access groups; and publishing it to the site's controllers.

Everything here is per site: read with `entry.view` at the site, changed with `entry.config.manage` there (row-level security says the same).
Changes are drafts until **publish**, which assembles the site's document (app/sitedoc.py), compiles it for each controller at the site and
stores a new settings version for every controller whose settings changed; the link delivers it within about a second.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.compiler.axis import CompileError, compile_controller
from app.db import get_db
from app.deps import Ctx, tenant_ctx
from app.document import Holiday, Rule, Window
from app.link.pgstore import notify
from app.link.protocol import Inventory
from app.models import AccessGroup, CardholderGroup, Controller, Door, HolidayCalendar, Intercom, Schedule, SettingsVersion, Site, utcnow
from app.routes.common import log, not_found, problem, site_of
from app import sitedoc, templates

router = APIRouter(prefix="/tenants/{tenant_id}/sites/{site_id}")
VIEW, MANAGE = "entry.view", "entry.config.manage"


# ---- doors ----


class DoorIn(BaseModel):
    controller_id: uuid.UUID
    controller_door: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=64)
    access_time_s: int = Field(default=7, ge=1, le=600)
    open_too_long_s: int = Field(default=30, ge=1, le=3600)
    pre_alarm_s: int = Field(default=5, ge=0, le=600)
    unlock_schedule_id: Optional[uuid.UUID] = None


class DoorPatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=64)
    access_time_s: Optional[int] = Field(default=None, ge=1, le=600)
    open_too_long_s: Optional[int] = Field(default=None, ge=1, le=3600)
    pre_alarm_s: Optional[int] = Field(default=None, ge=0, le=600)
    unlock_schedule_id: Optional[uuid.UUID] = None
    clear_unlock_schedule: bool = False


def door_view(d: Door) -> Dict[str, Any]:
    return {"id": str(d.id), "name": d.name, "controller_id": str(d.controller_id), "controller_door": d.controller_door,
            "access_time_s": d.access_time_s, "open_too_long_s": d.open_too_long_s, "pre_alarm_s": d.pre_alarm_s,
            "unlock_schedule_id": str(d.unlock_schedule_id) if d.unlock_schedule_id else None}


def _schedule_at(db: Session, site: Site, schedule_id: Optional[uuid.UUID]) -> None:
    if schedule_id is not None:
        s = db.get(Schedule, schedule_id)
        if s is None or s.site_id != site.id:
            raise problem({"code": "no_such_schedule", "detail": "That schedule is not one of this site's"})


@router.get("/doors")
def list_doors(site_id: uuid.UUID, ctx: Ctx = Depends(tenant_ctx), db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    site = site_of(db, ctx, site_id, VIEW)
    return [door_view(d) for d in db.execute(select(Door).where(Door.site_id == site.id).order_by(Door.name)).scalars()]


@router.post("/doors", status_code=201)
def add_door(site_id: uuid.UUID, body: DoorIn, ctx: Ctx = Depends(tenant_ctx), db: Session = Depends(get_db)) -> Dict[str, Any]:
    site = site_of(db, ctx, site_id, MANAGE)
    c = db.get(Controller, body.controller_id)
    if c is None or c.site_id != site.id or c.state == "pending":
        raise problem({"code": "no_such_controller", "detail": "That controller is not at this site"})
    known = {d["token"] for d in (c.inventory or {}).get("doors", [])}
    if body.controller_door not in known:
        raise problem({"code": "no_such_controller_door", "detail": "The controller has not reported that door"})
    _schedule_at(db, site, body.unlock_schedule_id)
    d = Door(id=uuid.uuid4(), tenant_id=ctx.tenant_id, site_id=site.id, **body.model_dump())
    db.add(d)
    try:
        db.flush()
    except IntegrityError:
        raise problem({"code": "door_exists", "detail": "That controller door is already a door"}, 409)
    log(db, ctx, "door.add", site_id=site.id, target_type="door", target_id=d.id, name=d.name)
    db.commit()
    return door_view(d)


def _door(db: Session, site: Site, door_id: uuid.UUID) -> Door:
    d = db.get(Door, door_id)
    if d is None or d.site_id != site.id:
        raise not_found()
    return d


@router.patch("/doors/{door_id}")
def patch_door(site_id: uuid.UUID, door_id: uuid.UUID, body: DoorPatch, ctx: Ctx = Depends(tenant_ctx), db: Session = Depends(get_db)) -> Dict[str, Any]:
    site = site_of(db, ctx, site_id, MANAGE)
    d = _door(db, site, door_id)
    changes = body.model_dump(exclude_unset=True, exclude={"clear_unlock_schedule"})
    if "unlock_schedule_id" in changes:
        _schedule_at(db, site, body.unlock_schedule_id)
    for k, v in changes.items():
        setattr(d, k, v)
    if body.clear_unlock_schedule:
        d.unlock_schedule_id = None
    log(db, ctx, "door.change", site_id=site.id, target_type="door", target_id=d.id, **{k: str(v) for k, v in changes.items()})
    db.commit()
    return door_view(d)


@router.delete("/doors/{door_id}", status_code=204)
def remove_door(site_id: uuid.UUID, door_id: uuid.UUID, ctx: Ctx = Depends(tenant_ctx), db: Session = Depends(get_db)) -> None:
    site = site_of(db, ctx, site_id, MANAGE)
    d = _door(db, site, door_id)
    for g in db.execute(select(AccessGroup).where(AccessGroup.site_id == site.id)).scalars():
        if any(str(d.id) in r["doors"] for r in g.rules):
            raise problem({"code": "door_in_use", "detail": f"Access group '{g.name}' opens this door: change the group first"}, 409)
    for i in db.execute(select(Intercom).where(Intercom.door_id == d.id)).scalars():
        raise problem({"code": "door_in_use", "detail": f"Intercom '{i.name}' is at this door: move or remove it first"}, 409)
    db.delete(d)
    log(db, ctx, "door.remove", site_id=site.id, target_type="door", target_id=d.id, name=d.name)
    db.commit()


# ---- schedules ----


class ScheduleIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    windows: List[Window] = Field(min_length=1)
    on_holidays: str = Field(default="off", pattern="^(off|normal)$")


def schedule_view(s: Schedule) -> Dict[str, Any]:
    return {"id": str(s.id), "name": s.name, "windows": s.windows, "on_holidays": s.on_holidays}


@router.get("/schedules")
def list_schedules(site_id: uuid.UUID, ctx: Ctx = Depends(tenant_ctx), db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    site = site_of(db, ctx, site_id, VIEW)
    return [schedule_view(s) for s in db.execute(select(Schedule).where(Schedule.site_id == site.id).order_by(Schedule.name)).scalars()]


@router.post("/schedules", status_code=201)
def add_schedule(site_id: uuid.UUID, body: ScheduleIn, ctx: Ctx = Depends(tenant_ctx), db: Session = Depends(get_db)) -> Dict[str, Any]:
    site = site_of(db, ctx, site_id, MANAGE)
    s = Schedule(id=uuid.uuid4(), tenant_id=ctx.tenant_id, site_id=site.id, name=body.name,
                 windows=[w.model_dump() for w in body.windows], on_holidays=body.on_holidays)
    db.add(s)
    log(db, ctx, "schedule.add", site_id=site.id, target_type="schedule", target_id=s.id, name=s.name)
    db.commit()
    return schedule_view(s)


@router.put("/schedules/{schedule_id}")
def put_schedule(site_id: uuid.UUID, schedule_id: uuid.UUID, body: ScheduleIn, ctx: Ctx = Depends(tenant_ctx), db: Session = Depends(get_db)) -> Dict[str, Any]:
    site = site_of(db, ctx, site_id, MANAGE)
    s = db.get(Schedule, schedule_id)
    if s is None or s.site_id != site.id:
        raise not_found()
    s.name, s.windows, s.on_holidays = body.name, [w.model_dump() for w in body.windows], body.on_holidays
    log(db, ctx, "schedule.change", site_id=site.id, target_type="schedule", target_id=s.id, name=s.name)
    db.commit()
    return schedule_view(s)


@router.delete("/schedules/{schedule_id}", status_code=204)
def remove_schedule(site_id: uuid.UUID, schedule_id: uuid.UUID, ctx: Ctx = Depends(tenant_ctx), db: Session = Depends(get_db)) -> None:
    site = site_of(db, ctx, site_id, MANAGE)
    s = db.get(Schedule, schedule_id)
    if s is None or s.site_id != site.id:
        raise not_found()
    sid = str(s.id)
    users = [d.name for d in db.execute(select(Door).where(Door.unlock_schedule_id == s.id)).scalars()]
    users += [g.name for g in db.execute(select(AccessGroup).where(AccessGroup.site_id == site.id)).scalars()
              if any(r.get("schedule_id") == sid for r in g.rules)]
    if users:
        raise problem({"code": "schedule_in_use", "detail": f"In use by: {', '.join(sorted(users))}"}, 409)
    db.delete(s)
    log(db, ctx, "schedule.remove", site_id=site.id, target_type="schedule", target_id=s.id, name=s.name)
    db.commit()


# ---- the site's holiday calendar ----


class HolidaysIn(BaseModel):
    days: List[Holiday] = Field(max_length=400)


@router.get("/holidays")
def get_holidays(site_id: uuid.UUID, ctx: Ctx = Depends(tenant_ctx), db: Session = Depends(get_db)) -> Dict[str, Any]:
    site = site_of(db, ctx, site_id, VIEW)
    cal = db.get(HolidayCalendar, site.id)
    return {"days": cal.days if cal else []}


@router.put("/holidays")
def put_holidays(site_id: uuid.UUID, body: HolidaysIn, ctx: Ctx = Depends(tenant_ctx), db: Session = Depends(get_db)) -> Dict[str, Any]:
    site = site_of(db, ctx, site_id, MANAGE)
    days = sorted(({"day": h.day.isoformat(), "name": h.name} for h in body.days), key=lambda h: h["day"])
    cal = db.get(HolidayCalendar, site.id)
    if cal is None:
        db.add(HolidayCalendar(site_id=site.id, tenant_id=ctx.tenant_id, days=days))
    else:
        cal.days = days
    log(db, ctx, "holidays.change", site_id=site.id, target_type="site", target_id=site.id, days=len(days))
    db.commit()
    return {"days": days}


# ---- access groups ----


class GroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    rules: List[Rule] = Field(min_length=1)


def group_view(g: AccessGroup) -> Dict[str, Any]:
    return {"id": str(g.id), "name": g.name, "rules": g.rules}


def _check_rules(db: Session, site: Site, rules: List[Rule]) -> List[Dict[str, Any]]:
    doors = {str(d) for d in db.execute(select(Door.id).where(Door.site_id == site.id)).scalars()}
    schedules = {str(s) for s in db.execute(select(Schedule.id).where(Schedule.site_id == site.id)).scalars()}
    for r in rules:
        if any(d not in doors for d in r.doors):
            raise problem({"code": "no_such_door", "detail": "A rule names a door that is not this site's"})
        if r.schedule_id and r.schedule_id not in schedules:
            raise problem({"code": "no_such_schedule", "detail": "A rule names a schedule that is not this site's"})
    return [r.model_dump() for r in rules]


@router.get("/groups")
def list_groups(site_id: uuid.UUID, ctx: Ctx = Depends(tenant_ctx), db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    site = site_of(db, ctx, site_id, VIEW)
    return [group_view(g) for g in db.execute(select(AccessGroup).where(AccessGroup.site_id == site.id).order_by(AccessGroup.name)).scalars()]


@router.post("/groups", status_code=201)
def add_group(site_id: uuid.UUID, body: GroupIn, ctx: Ctx = Depends(tenant_ctx), db: Session = Depends(get_db)) -> Dict[str, Any]:
    site = site_of(db, ctx, site_id, MANAGE)
    g = AccessGroup(id=uuid.uuid4(), tenant_id=ctx.tenant_id, site_id=site.id, name=body.name, rules=_check_rules(db, site, body.rules))
    db.add(g)
    log(db, ctx, "group.add", site_id=site.id, target_type="group", target_id=g.id, name=g.name)
    db.commit()
    return group_view(g)


@router.put("/groups/{group_id}")
def put_group(site_id: uuid.UUID, group_id: uuid.UUID, body: GroupIn, ctx: Ctx = Depends(tenant_ctx), db: Session = Depends(get_db)) -> Dict[str, Any]:
    site = site_of(db, ctx, site_id, MANAGE)
    g = db.get(AccessGroup, group_id)
    if g is None or g.site_id != site.id:
        raise not_found()
    g.name, g.rules = body.name, _check_rules(db, site, body.rules)
    log(db, ctx, "group.change", site_id=site.id, target_type="group", target_id=g.id, name=g.name)
    db.commit()
    return group_view(g)


@router.delete("/groups/{group_id}", status_code=204)
def remove_group(site_id: uuid.UUID, group_id: uuid.UUID, ctx: Ctx = Depends(tenant_ctx), db: Session = Depends(get_db)) -> None:
    site = site_of(db, ctx, site_id, MANAGE)
    g = db.get(AccessGroup, group_id)
    if g is None or g.site_id != site.id:
        raise not_found()
    for m in db.execute(select(CardholderGroup).where(CardholderGroup.group_id == g.id)).scalars():
        db.delete(m)
    db.delete(g)
    log(db, ctx, "group.remove", site_id=site.id, target_type="group", target_id=g.id, name=g.name)
    db.commit()


# ---- publish ----


@router.post("/publish")
def publish(site_id: uuid.UUID, ctx: Ctx = Depends(tenant_ctx), db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Compile the site for each of its controllers and store a new settings version wherever the settings changed. Nothing is stored when any
    controller's settings cannot be compiled: a site is published whole or not at all."""
    site = site_of(db, ctx, site_id, MANAGE)
    try:
        doc = sitedoc.build(db, site)
    except ValidationError as e:
        raise problem({"code": "invalid", "problems": [f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()]})
    controllers = db.execute(select(Controller).where(Controller.site_id == site.id, Controller.state != "pending")
                             .order_by(Controller.name)).scalars().all()
    compiled, problems = [], []
    for c in controllers:
        if not any(d.controller_id == str(c.id) for d in doc.doors):
            continue                                 # a controller with no doors mapped yet gets nothing
        try:
            inv = Inventory.model_validate(c.inventory) if c.inventory is not None else None
            compiled.append((c, compile_controller(doc, str(c.id), inv)))
        except CompileError as e:
            problems += e.problems
    if problems:
        raise problem({"code": "invalid", "problems": sorted(set(problems))})
    out = []
    for c, settings in compiled:
        latest = db.execute(select(SettingsVersion).where(SettingsVersion.controller_id == c.id)
                            .order_by(SettingsVersion.version.desc()).limit(1)).scalar_one_or_none()
        if latest is not None and latest.document == settings:
            out.append({"controller_id": str(c.id), "version": latest.version, "changed": False})
            continue
        version = (latest.version if latest else 0) + 1
        db.add(SettingsVersion(controller_id=c.id, version=version, tenant_id=ctx.tenant_id, site_id=site.id, document=settings,
                               created_by=ctx.who.id))
        notify(db, c.id)
        out.append({"controller_id": str(c.id), "version": version, "changed": True})
    try:
        db.flush()
    except IntegrityError:
        raise problem({"code": "publish_conflict", "detail": "Someone published this site at the same moment: try again"}, 409)
    log(db, ctx, "site.publish", site_id=site.id, target_type="site", target_id=site.id,
        versions={o["controller_id"]: o["version"] for o in out if o["changed"]})
    db.commit()
    return {"controllers": out}


# ---- templates ----


class TemplateDoor(BaseModel):
    controller_id: uuid.UUID
    controller_door: str = Field(min_length=1, max_length=64)
    name: Optional[str] = Field(default=None, min_length=1, max_length=64)


class ApplyTemplateIn(BaseModel):
    doors: Dict[str, TemplateDoor] = Field(description="Slot key -> the controller door it is; optional slots may be left out")
    options: Dict[str, bool] = Field(default_factory=dict)
    years: Optional[List[int]] = Field(default=None, description="Holiday years (default: this year and next)")


@router.post("/templates/{key}/apply", status_code=201)
def apply_template(site_id: uuid.UUID, key: str, body: ApplyTemplateIn, ctx: Ctx = Depends(tenant_ctx), db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Create a template's doors, schedules and groups at the site and add its holidays to the site's calendar, in one transaction."""
    site = site_of(db, ctx, site_id, MANAGE)
    this_year = utcnow().year
    years = body.years or [this_year, this_year + 1]
    if any(y < 2000 or y > 2100 for y in years) or len(years) > 5:
        raise problem({"code": "invalid", "detail": "Holiday years are 2000 to 2100, at most five"})
    try:
        p = templates.plan(key, {k: {"controller_id": str(v.controller_id), "controller_door": v.controller_door, "name": v.name or ""}
                                 for k, v in body.doors.items()}, body.options, years)
    except templates.TemplateError as e:
        raise problem({"code": "invalid", "detail": str(e)})
    for _, cid, cdoor, _, _ in p.doors:
        c = db.get(Controller, uuid.UUID(cid))
        if c is None or c.site_id != site.id or c.state == "pending":
            raise problem({"code": "no_such_controller", "detail": "A chosen controller is not at this site"})
        if cdoor not in {d["token"] for d in (c.inventory or {}).get("doors", [])}:
            raise problem({"code": "no_such_controller_door", "detail": f"The controller has not reported door {cdoor}"})
    schedule_ids = {s.key: uuid.uuid4() for s in p.schedules}
    for s in p.schedules:
        db.add(Schedule(id=schedule_ids[s.key], tenant_id=ctx.tenant_id, site_id=site.id, name=s.name, windows=s.windows, on_holidays=s.on_holidays))
    door_ids: Dict[str, uuid.UUID] = {}
    for slot, cid, cdoor, name, unlock in p.doors:
        door_ids[slot.key] = uuid.uuid4()
        db.add(Door(id=door_ids[slot.key], tenant_id=ctx.tenant_id, site_id=site.id, controller_id=uuid.UUID(cid), controller_door=cdoor, name=name,
                    access_time_s=slot.access_time_s, open_too_long_s=slot.open_too_long_s, pre_alarm_s=slot.pre_alarm_s,
                    unlock_schedule_id=schedule_ids[unlock] if unlock else None))
    group_ids = {}
    for g, rules in p.groups:
        group_ids[g.key] = uuid.uuid4()
        db.add(AccessGroup(id=group_ids[g.key], tenant_id=ctx.tenant_id, site_id=site.id, name=g.name, rules=[
            {"doors": [str(door_ids[x]) for x in slots], "schedule_id": str(schedule_ids[sched]) if sched else None} for slots, sched in rules]))
    added = 0
    if p.holidays:
        cal = db.get(HolidayCalendar, site.id)
        have = {d["day"] for d in (cal.days if cal else [])}
        days = list(cal.days) if cal else []
        for day, name in p.holidays:
            if day.isoformat() not in have:
                days.append({"day": day.isoformat(), "name": name})
                added += 1
        days.sort(key=lambda d: d["day"])
        if cal is None:
            db.add(HolidayCalendar(site_id=site.id, tenant_id=ctx.tenant_id, days=days))
        else:
            cal.days = days
    try:
        db.flush()
    except IntegrityError:
        raise problem({"code": "door_exists", "detail": "One of the chosen controller doors is already a door at this site"}, 409)
    log(db, ctx, "site.template", site_id=site.id, target_type="site", target_id=site.id, template=key, doors=len(door_ids),
        schedules=len(schedule_ids), groups=len(group_ids), holidays=added)
    db.commit()
    return {"template": key, "doors": {k: str(v) for k, v in door_ids.items()}, "schedules": {k: str(v) for k, v in schedule_ids.items()},
            "groups": {k: str(v) for k, v in group_ids.items()}, "holidays_added": added}

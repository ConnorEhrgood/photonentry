"""A site's lockdown (ARCHITECTURE §9.6, decision 17), as a record: its scope, its reason, who started it and from where, each door's command,
and who ended it and why.

- **Start** (operators and up, `entry.lockdown`): the whole site or some doors, with a reason. One command per door to its controller
  (`tdc:LockDownDoor`): the controller holds the lockdown itself, with the cloud away, and ignores credentials, unlock schedules and remote
  unlocks until it is released. One lockdown at a time per site.
- **End** (the same capability), with a reason: the same doors released.
- **Everyone at the site sees it** (the app's banner), and it is in the audit trail.
- Egress and fire release are hardware and never touched (ARCHITECTURE §7.1).

Responders who keep working during a lockdown, and a wired panic input on the controller, wait for the bench: Axis documents neither on the
VAPIX track (sim/reference/AXIS-LOCKDOWN.md).
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Ctx, require, tenant_ctx
from app.models import Door, LinkCommand, Lockdown, Site, utcnow
from app.routes.actions import command
from app.routes.common import log, problem, site_of
from app.routes.tenants import PARTNER_LABEL

router = APIRouter(prefix="/tenants/{tenant_id}")
LOCK = "entry.lockdown"


class LockdownIn(BaseModel):
    on: bool
    reason: str = Field(min_length=1, max_length=200)
    door_ids: Optional[List[uuid.UUID]] = Field(default=None, min_length=1)      # none: every door of the site

    @field_validator("reason")
    @classmethod
    def _said(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("say why")
        return v


def _who(label: str, source: str) -> str:
    return PARTNER_LABEL if source in ("partner", "platform") else label


def view(db: Session, lk: Lockdown) -> Dict[str, Any]:
    """The lockdown with each door's state: `sent` (not confirmed yet), `done`, `failed` (the controller refused: see `error`), `expired`,
    `not_sent` (its controller is out of service)."""
    doors = {str(d.id): d for d in db.execute(select(Door).where(Door.site_id == lk.site_id)).scalars()}
    ids = [c for c in lk.start_commands + lk.end_commands if c]
    cmds = {c.id: c for c in db.execute(select(LinkCommand).where(LinkCommand.id.in_(ids))).scalars()} if ids else {}
    now = utcnow()

    def state(cid: str) -> Dict[str, Any]:
        if not cid:
            return {"state": "not_sent", "error": "Its controller is not in service"}
        c = cmds.get(cid)
        if c is None:
            return {"state": "sent", "error": ""}
        if c.done:
            return {"state": "done" if c.ok else "failed", "error": c.error}
        return {"state": "expired" if c.expires_at <= now else "sent", "error": ""}

    ending = bool(lk.end_commands)
    by_door = dict(zip(lk.door_ids, lk.end_commands if ending else lk.start_commands))
    site = db.get(Site, lk.site_id)
    return {
        "id": str(lk.id), "site_id": str(lk.site_id), "site": site.name if site else "", "whole_site": lk.whole_site, "reason": lk.reason,
        "source": lk.source, "started_by": _who(lk.started_by_label, lk.started_by_source), "started_at": lk.started_at.isoformat(),
        "active": lk.ended_at is None, "ended_at": lk.ended_at.isoformat() if lk.ended_at else None,
        "ended_by": _who(lk.ended_by_label, lk.ended_by_source) if lk.ended_at else None, "end_reason": lk.end_reason or None,
        "doors": [{"door_id": d, "door": doors[d].name if d in doors else "(removed)", **state(by_door.get(d, ""))} for d in lk.door_ids],
    }


def _send(db: Session, ctx: Ctx, door: Door, kind: str) -> Dict[str, Any]:
    """A lockdown never fails as a whole: a door whose controller is out of service is reported (its id ""), the others still lock down."""
    try:
        return command(db, ctx, door, kind)
    except HTTPException:
        return {"id": "", "door_id": str(door.id), "kind": kind, "expires_at": None}


def _active(db: Session, site_id: uuid.UUID) -> Optional[Lockdown]:
    return db.execute(select(Lockdown).where(Lockdown.site_id == site_id, Lockdown.ended_at.is_(None))).scalar_one_or_none()


@router.post("/sites/{site_id}/lockdown", status_code=202)
def lockdown(site_id: uuid.UUID, body: LockdownIn, ctx: Ctx = Depends(tenant_ctx), db: Session = Depends(get_db)) -> Dict[str, Any]:
    site = site_of(db, ctx, site_id, LOCK)
    site_name = site.name
    active = _active(db, site.id)
    if not body.on:
        if active is None:
            raise problem({"code": "not_locked_down", "detail": f"{site.name} is not locked down"}, 409)
        doors = {str(d.id): d for d in db.execute(select(Door).where(Door.site_id == site.id)).scalars()}
        cmds = [_send(db, ctx, doors[d], "lockdown_release") if d in doors else {"id": "", "door_id": d, "kind": "lockdown_release", "expires_at": None}
                for d in active.door_ids]
        active.ended_at, active.ended_by, active.ended_by_label, active.ended_by_source = utcnow(), ctx.who.id, ctx.who.label[:200], ctx.source
        active.end_reason, active.end_commands = body.reason, [c["id"] for c in cmds]
        log(db, ctx, "site.lockdown_end", site_id=site.id, target_type="site", target_id=site.id, reason=body.reason, lockdown=str(active.id))
        db.commit()
        return {"lockdown": view(db, active), "commands": cmds}
    if active is not None:
        raise problem({"code": "already_locked_down", "detail": f"{site.name} is already locked down: end that lockdown first"}, 409)
    doors = db.execute(select(Door).where(Door.site_id == site.id).order_by(Door.name)).scalars().all()
    if body.door_ids is not None:
        wanted = set(body.door_ids)
        doors = [d for d in doors if d.id in wanted]
        if len(doors) != len(wanted):
            raise problem({"code": "no_such_door", "detail": "A door is not this site's"})
    if not doors:
        raise problem({"code": "no_doors", "detail": f"{site.name} has no doors to lock down"})
    cmds = [_send(db, ctx, d, "lockdown") for d in doors]
    lk = Lockdown(id=uuid.uuid4(), tenant_id=ctx.tenant_id, site_id=site.id, door_ids=[str(d.id) for d in doors], whole_site=body.door_ids is None,
                  reason=body.reason, source="app", started_by=ctx.who.id, started_by_label=ctx.who.label[:200], started_by_source=ctx.source,
                  started_at=utcnow(), start_commands=[c["id"] for c in cmds])
    db.add(lk)
    try:
        db.flush()
    except IntegrityError:                     # another lockdown started at this site a moment ago: its commands stand, these are dropped
        name = site_name
        db.rollback()
        raise problem({"code": "already_locked_down", "detail": f"{name} is already locked down"}, 409)
    log(db, ctx, "site.lockdown", site_id=site.id, target_type="site", target_id=site.id, reason=body.reason, lockdown=str(lk.id),
        doors=[str(d.id) for d in doors])
    db.commit()
    return {"lockdown": view(db, lk), "commands": cmds}


@router.get("/sites/{site_id}/lockdowns")
def site_lockdowns(site_id: uuid.UUID, ctx: Ctx = Depends(tenant_ctx), db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    """The site's lockdowns, newest first (the active one, if any, first of all)."""
    site = site_of(db, ctx, site_id, "entry.view")
    rows = db.execute(select(Lockdown).where(Lockdown.site_id == site.id).order_by(Lockdown.started_at.desc()).limit(20)).scalars().all()
    return [view(db, lk) for lk in rows]


@router.get("/lockdowns/active")
def active_lockdowns(ctx: Ctx = Depends(require("entry.view")), db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    """Every site of the organization this person reaches that is locked down now: the app's banner on every page."""
    rows = db.execute(select(Lockdown).where(Lockdown.tenant_id == ctx.tenant_id, Lockdown.ended_at.is_(None))
                      .order_by(Lockdown.started_at)).scalars().all()
    return [view(db, lk) for lk in rows]

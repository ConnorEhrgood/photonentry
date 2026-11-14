"""Opening one's own doors from the app (decision 25; the rules: app/unlock.py). Anyone with an Entry role (`entry.unlock.own`) linked to a
cardholder of the organization.

- `GET /tenants/{t}/my/doors` the person's doors, and whether each opens now (and why not);
- `POST /tenants/{t}/my/doors/{door_id}/open` open it (the door's access time), checked again first; at most 10 a minute per person;
- `GET /tenants/{t}/my/commands/{id}` how that went (the person's own commands only).
The command is written by the system in the person's name (door users may not write commands), and audited.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, unlock
from app.db import SystemSession, get_db
from app.deps import Ctx, require
from app.link.pgstore import new_command, notify
from app.models import Cardholder, Door, LinkCommand, Person
from app.routes.common import not_found, problem
from app.throttle import Throttle

router = APIRouter(prefix="/tenants/{tenant_id}/my")
OWN = "entry.unlock.own"
open_throttle = Throttle(limit=10, window_s=60)
WHY = {"outside_schedule": "Not at this time", "not_commissioned": "Not in service yet", "locked_down": "Locked down",
       "out_of_service": "Its controller is out of service"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _mine(s: Session, ctx: Ctx):
    person = s.get(Person, ctx.who.id)
    holder = unlock.link_by_email(s, ctx.tenant_id, person)
    holders = s.execute(select(Cardholder).where(Cardholder.tenant_id == ctx.tenant_id, Cardholder.person_id == ctx.who.id)).scalars().all()
    return holder, holders


@router.get("/doors")
def my_doors(ctx: Ctx = Depends(require(OWN))) -> Dict[str, Any]:
    with SystemSession() as s:
        _, holders = _mine(s, ctx)
        s.commit()                                   # a link made by email stays made
        opts = unlock.options(s, ctx.tenant_id, holders, _now())
    return {"linked": bool(holders), "doors": [{"door_id": o.door_id, "door": o.door, "site_id": o.site_id, "site": o.site, "can_open": o.can_open,
                                                "why": o.why, "why_text": WHY.get(o.why, "")} for o in opts]}


@router.post("/doors/{door_id}/open", status_code=202)
def open_door(door_id: uuid.UUID, ctx: Ctx = Depends(require(OWN))) -> Dict[str, Any]:
    if not open_throttle.allow(str(ctx.who.id)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many tries: wait a minute")
    now = _now()
    with SystemSession() as s:
        _, holders = _mine(s, ctx)
        opt = next((o for o in unlock.options(s, ctx.tenant_id, holders, now) if o.door_id == str(door_id)), None)
        if opt is None:
            raise not_found()                        # not one of the person's doors
        if not opt.can_open:
            raise problem({"code": opt.why, "detail": f"{opt.door}: {WHY[opt.why].lower()}"}, 409)
        d = s.get(Door, door_id)
        cmd = new_command("access", d.controller_door, ctx.who.label, now)
        s.add(LinkCommand(id=cmd.id, tenant_id=ctx.tenant_id, site_id=d.site_id, controller_id=d.controller_id, kind="access", door=d.controller_door,
                          actor=ctx.who.label[:200], actor_person_id=ctx.who.id, expires_at=cmd.expires_at))
        notify(s, d.controller_id)
        audit.record(s, actor_id=ctx.who.id, actor_label=ctx.who.label, actor_source=ctx.source, action="door.open_own", tenant_id=ctx.tenant_id,
                     site_id=d.site_id, target_type="door", target_id=d.id, command=cmd.id)
        s.commit()
        return {"id": cmd.id, "door_id": str(d.id), "expires_at": cmd.expires_at.isoformat()}


@router.get("/commands/{command_id}")
def my_command(command_id: str, ctx: Ctx = Depends(require(OWN))) -> Dict[str, Any]:
    with SystemSession() as s:
        c = s.get(LinkCommand, command_id[:40])
        if c is None or c.tenant_id != ctx.tenant_id or c.actor_person_id != ctx.who.id:
            raise not_found()
        return {"id": c.id, "done": c.done, "ok": c.ok, "error": c.error, "expired": not c.done and c.expires_at <= _now()}

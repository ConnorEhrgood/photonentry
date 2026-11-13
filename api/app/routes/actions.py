"""Remote actions on doors, the site's lockdown, door events and the audit trail.

Remote actions are commands to the door's controller, delivered by the link within about a second and refused there once they expire
(a late unlock is worse than none). They are written in the acting person's own name, under row-level security, and audited. Lockdown is one
command per door of the site; ending it is the same, reversed. Neither touches egress or fire release, which are hardware (ARCHITECTURE §7.1).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.events import normalize
from app.deps import Ctx, require, tenant_ctx
from app.link.pgstore import new_command, notify
from app.models import AuditLog, Cardholder, Controller, Door, DoorEvent, LinkCommand, utcnow
from app.routes.common import log, not_found, problem, site_of
from app.routes.tenants import PARTNER_LABEL

router = APIRouter(prefix="/tenants/{tenant_id}")


class DoorAction(BaseModel):
    action: Literal["access", "unlock", "lock"] = "access"


class LockdownIn(BaseModel):
    on: bool
    door_ids: Optional[List[uuid.UUID]] = None      # none: every door of the site


def _command(db: Session, ctx: Ctx, door: Door, kind: str) -> Dict[str, Any]:
    c = db.get(Controller, door.controller_id)
    if c is None or c.state != "claimed":
        raise problem({"code": "controller_not_in_service", "detail": "This door's controller is not in service"}, 409)
    cmd = new_command(kind, door.controller_door, ctx.who.label, utcnow())
    db.add(LinkCommand(id=cmd.id, tenant_id=ctx.tenant_id, site_id=door.site_id, controller_id=c.id, kind=kind, door=door.controller_door,
                       actor=ctx.who.label[:200], actor_person_id=ctx.who.id, expires_at=cmd.expires_at))
    notify(db, c.id)
    return {"id": cmd.id, "door_id": str(door.id), "kind": kind, "expires_at": cmd.expires_at.isoformat()}


@router.post("/doors/{door_id}/action", status_code=202)
def door_action(door_id: uuid.UUID, body: DoorAction, ctx: Ctx = Depends(tenant_ctx), db: Session = Depends(get_db)) -> Dict[str, Any]:
    d = db.get(Door, door_id)
    if d is None or d.tenant_id != ctx.tenant_id:
        raise not_found()
    site_of(db, ctx, d.site_id, "entry.door.unlock")
    out = _command(db, ctx, d, body.action)
    log(db, ctx, f"door.{body.action}", site_id=d.site_id, target_type="door", target_id=d.id, command=out["id"])
    db.commit()
    return out


@router.post("/sites/{site_id}/lockdown", status_code=202)
def lockdown(site_id: uuid.UUID, body: LockdownIn, ctx: Ctx = Depends(tenant_ctx), db: Session = Depends(get_db)) -> Dict[str, Any]:
    site = site_of(db, ctx, site_id, "entry.lockdown")
    doors = db.execute(select(Door).where(Door.site_id == site.id).order_by(Door.name)).scalars().all()
    if body.door_ids is not None:
        wanted = set(body.door_ids)
        doors = [d for d in doors if d.id in wanted]
        if len(doors) != len(wanted):
            raise problem({"code": "no_such_door", "detail": "A door is not this site's"})
    kind = "lockdown" if body.on else "lockdown_release"
    commands = [_command(db, ctx, d, kind) for d in doors]
    log(db, ctx, "site.lockdown" if body.on else "site.lockdown_end", site_id=site.id, target_type="site", target_id=site.id,
        doors=[str(d.id) for d in doors])
    db.commit()
    return {"commands": commands}


@router.get("/commands/{command_id}")
def command_state(command_id: str, ctx: Ctx = Depends(require("entry.view")), db: Session = Depends(get_db)) -> Dict[str, Any]:
    c = db.get(LinkCommand, command_id[:40])
    if c is None or c.tenant_id != ctx.tenant_id:
        raise not_found()
    return {"id": c.id, "kind": c.kind, "done": c.done, "ok": c.ok, "error": c.error, "delivered": c.delivered_at is not None,
            "expires_at": c.expires_at.isoformat()}


@router.get("/sites/{site_id}/events")
def events(site_id: uuid.UUID, ctx: Ctx = Depends(tenant_ctx), db: Session = Depends(get_db), limit: int = Query(100, ge=1, le=1000),
           before: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """The site's door events, newest first, with the door and the cardholder each refers to where they can be worked out."""
    site = site_of(db, ctx, site_id, "entry.events.view")
    q = select(DoorEvent).where(DoorEvent.site_id == site.id)
    if before is not None:
        q = q.where(DoorEvent.occurred_at < before)
    rows = db.execute(q.order_by(DoorEvent.occurred_at.desc(), DoorEvent.seq.desc()).limit(limit)).scalars().all()
    doors = {(d.controller_id, d.controller_door): d for d in db.execute(select(Door).where(Door.site_id == site.id)).scalars()}
    points: Dict[Any, Door] = {}
    for c in db.execute(select(Controller).where(Controller.site_id == site.id)).scalars():
        for inv in (c.inventory or {}).get("doors", []):
            door = doors.get((c.id, inv["token"]))
            for ap in inv.get("access_points", []):
                if door is not None:
                    points[(c.id, ap)] = door
    holder_ids = set()
    for e in rows:
        name = e.data.get("CredentialHolderName", "")
        if name.startswith("pe-u-"):
            try:
                holder_ids.add(uuid.UUID(name[5:]))
            except ValueError:
                pass
    names = {}
    if holder_ids and ctx.can("entry.cardholders.view", site.id):
        names = {h.id: h.name for h in db.execute(select(Cardholder).where(Cardholder.id.in_(holder_ids))).scalars()}
    out = []
    for e in rows:
        door = doors.get((e.controller_id, e.source.get("DoorToken", ""))) or points.get((e.controller_id, e.source.get("AccessPointToken", "")))
        holder = e.data.get("CredentialHolderName", "")
        hid = None
        if holder.startswith("pe-u-"):
            try:
                hid = uuid.UUID(holder[5:])
            except ValueError:
                hid = None
        n = normalize(e.topic, e.data)
        out.append({"controller_id": str(e.controller_id), "seq": e.seq, "occurred_at": e.occurred_at.isoformat(),
                    "kind": n.kind, "label": n.label, "severity": n.severity,
                    "received_at": e.received_at.isoformat(), "topic": e.topic, "door_id": str(door.id) if door else None,
                    "door": door.name if door else None, "cardholder_id": str(hid) if hid and hid in names else None,
                    "cardholder": names.get(hid) if hid else None, "reason": e.data.get("Reason"), "state": e.data.get("State")})
    return out


@router.get("/audit")
def audit_trail(ctx: Ctx = Depends(require("entry.audit.view")), db: Session = Depends(get_db), limit: int = Query(200, ge=1, le=1000),
                before: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Newest first. Partner staff are shown as "Partner support" (suite §5); who they were stays in the record for Photon."""
    q = select(AuditLog).where(AuditLog.tenant_id == ctx.tenant_id)
    if before is not None:
        q = q.where(AuditLog.at < before)
    rows = db.execute(q.order_by(AuditLog.at.desc(), AuditLog.id.desc()).limit(limit)).scalars().all()
    return [{"at": a.at.isoformat(), "actor": PARTNER_LABEL if a.actor_source in ("partner", "platform") else a.actor_label,
             "action": a.action, "site_id": str(a.site_id) if a.site_id else None, "target_type": a.target_type, "target_id": a.target_id,
             "detail": a.detail} for a in rows]

"""Controllers: claim one by the code it shows, see them, rename, take out of service and back.

A controller that has said hello belongs to no organization until an admin of a site claims it with its code (ARCHITECTURE §3.2). Pending
controllers are visible to the system role only, so the claim goes through the link store, after this route has checked the person's right to
manage controllers at the site they name.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Ctx, require, tenant_ctx
from app.link.pgstore import notify
from app.link.store import NotFound
from app.models import Controller, SettingsVersion, utcnow
from app.routes.common import log, not_found, problem, site_of
from app.routes.tenants import visible_sites

router = APIRouter(prefix="/tenants/{tenant_id}")


def get_link(request: Request):
    return request.app.state.link


class ClaimIn(BaseModel):
    code: str = Field(pattern=r"^[0-9A-Za-z]{4}-?[0-9A-Za-z]{4}$")
    site_id: uuid.UUID
    name: str = Field(default="", max_length=64)


class ControllerPatch(BaseModel):
    name: Optional[str] = Field(default=None, max_length=64)
    in_service: Optional[bool] = None


def view(c: Controller, latest: Optional[int]) -> Dict[str, Any]:
    return {"id": str(c.id), "site_id": str(c.site_id), "name": c.name, "state": c.state, "device": c.device, "inventory": c.inventory,
            "settings": {"latest": latest or 0, "applied": c.applied_version, "error": c.apply_error,
                         "current": (latest or 0) == c.applied_version},
            "last_seen": c.last_seen.isoformat() if c.last_seen else None, "health": c.health}


def _latest(db: Session, controller_id: uuid.UUID) -> Optional[int]:
    return db.execute(select(func.max(SettingsVersion.version)).where(SettingsVersion.controller_id == controller_id)).scalar()


@router.get("/controllers")
def list_controllers(ctx: Ctx = Depends(require("entry.view")), db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    sites = {s.id for s in visible_sites(db, ctx)}
    rows = db.execute(select(Controller).where(Controller.tenant_id == ctx.tenant_id).order_by(Controller.name)).scalars().all()
    return [view(c, _latest(db, c.id)) for c in rows if c.site_id in sites]


@router.post("/controllers/claim", status_code=201)
def claim(body: ClaimIn, ctx: Ctx = Depends(tenant_ctx), db: Session = Depends(get_db), link=Depends(get_link)) -> Dict[str, Any]:
    site = site_of(db, ctx, body.site_id, "entry.controller.manage")
    code = body.code.upper().replace("-", "")
    try:
        claimed = link.store.claim(f"{code[:4]}-{code[4:]}", str(ctx.tenant_id), str(site.id), utcnow())
    except NotFound:
        raise problem({"code": "no_such_controller", "detail": "No controller is waiting with that code. Check the code on the controller."}, 404)
    c = db.get(Controller, uuid.UUID(claimed.id))
    if body.name:
        c.name = body.name
    log(db, ctx, "controller.claim", site_id=site.id, target_type="controller", target_id=c.id, model=c.device.get("model", ""),
        serial=c.device.get("serial", ""))
    db.commit()
    return view(c, None)


def _controller(db: Session, ctx: Ctx, controller_id: uuid.UUID, capability: str) -> Controller:
    c = db.get(Controller, controller_id)
    if c is None or c.tenant_id != ctx.tenant_id:
        raise not_found()
    site_of(db, ctx, c.site_id, capability)
    return c


@router.get("/controllers/{controller_id}")
def get_controller(controller_id: uuid.UUID, ctx: Ctx = Depends(tenant_ctx), db: Session = Depends(get_db)) -> Dict[str, Any]:
    c = _controller(db, ctx, controller_id, "entry.view")
    return view(c, _latest(db, c.id))


@router.patch("/controllers/{controller_id}")
def patch_controller(controller_id: uuid.UUID, body: ControllerPatch, ctx: Ctx = Depends(tenant_ctx), db: Session = Depends(get_db)) -> Dict[str, Any]:
    c = _controller(db, ctx, controller_id, "entry.controller.manage")
    if body.name is not None:
        c.name = body.name
    if body.in_service is not None:
        wanted = "claimed" if body.in_service else "disabled"
        if wanted != c.state:
            c.state = wanted
            notify(db, c.id)                       # a held sync learns at once
            log(db, ctx, "controller.enable" if body.in_service else "controller.disable", site_id=c.site_id, target_type="controller",
                target_id=c.id)
    if body.name is not None:
        log(db, ctx, "controller.rename", site_id=c.site_id, target_type="controller", target_id=c.id, name=body.name)
    db.commit()
    return view(c, _latest(db, c.id))

"""A site's intercoms (ARCHITECTURE §3.4, BUILD-GUIDE §5): Akuvox intercoms at doors, set up by PhotonEntry's provisioning server.

Admins at the site add an intercom (its door, model and MAC address); PhotonEntry makes every secret it needs: the relay password entry-link
checks, the intercom's own admin password, and the token in its provisioning address. The **setup** view shows the installer what to type into
the intercom once (the provisioning address), and is audited.

The intercom reaches entry-link on its door's controller: at the address the controller reports (`local_endpoint` in its health), unless the
admin sets `relay_address` (a NAT, another port). A new intercom, or a changed relay password, reaches entry-link at the next publish.

The SIP account is typed in for now; PhotonVox's door stations will fill it (ARCHITECTURE §9.2, docs/VOX.md).
"""
from __future__ import annotations

import secrets
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import akuvox, crypto
from app.config import settings
from app.db import get_db
from app.deps import Ctx, tenant_ctx
from app.models import Controller, Door, Intercom, Site
from app.routes.common import log, not_found, problem, site_of

router = APIRouter(prefix="/tenants/{tenant_id}/sites/{site_id}")
MANAGE = "entry.config.manage"
_ADDRESS = r"^[A-Za-z0-9.-]{1,64}:\d{1,5}$"


def normal_mac(v: str) -> str:
    mac = "".join(c for c in v.upper() if c in "0123456789ABCDEF")
    if len(mac) != 12 or len(v) > 17:
        raise ValueError("a MAC address is 12 hex digits, with or without : or -")
    return mac


class IntercomIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    door_id: uuid.UUID
    model: str
    mac: str
    relay_address: str = Field(default="", pattern=f"^$|{_ADDRESS}")
    sip_server: str = Field(default="", max_length=255)
    sip_port: int = Field(default=5061, ge=1, le=65535)
    sip_transport: str = Field(default="tls", pattern="^(udp|tcp|tls)$")
    sip_user: str = Field(default="", max_length=64)
    sip_password: str = Field(default="", max_length=128)

    _mac = field_validator("mac")(normal_mac)

    @field_validator("model")
    @classmethod
    def _model(cls, v: str) -> str:
        if v not in akuvox.MODELS:
            raise ValueError(f"model is one of {', '.join(akuvox.MODELS)}")
        return v


class IntercomPatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=64)
    door_id: Optional[uuid.UUID] = None
    model: Optional[str] = None
    mac: Optional[str] = None
    relay_address: Optional[str] = Field(default=None, pattern=f"^$|{_ADDRESS}")
    sip_server: Optional[str] = Field(default=None, max_length=255)
    sip_port: Optional[int] = Field(default=None, ge=1, le=65535)
    sip_transport: Optional[str] = Field(default=None, pattern="^(udp|tcp|tls)$")
    sip_user: Optional[str] = Field(default=None, max_length=64)
    sip_password: Optional[str] = Field(default=None, max_length=128)

    @field_validator("mac")
    @classmethod
    def _mac(cls, v: Optional[str]) -> Optional[str]:
        return None if v is None else normal_mac(v)

    @field_validator("model")
    @classmethod
    def _model(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in akuvox.MODELS:
            raise ValueError(f"model is one of {', '.join(akuvox.MODELS)}")
        return v


def relay_target(db: Session, i: Intercom) -> str:
    """Where the intercom reaches entry-link: the admin's address, else what the door's controller reports. "" if neither is known yet."""
    if i.relay_address:
        return i.relay_address
    door = db.get(Door, i.door_id)
    c = db.get(Controller, door.controller_id) if door is not None else None
    return str(((c.health or {}) if c is not None else {}).get("local_endpoint", ""))


def provision_url(token: str) -> str:
    return f"{settings.provision_url.rstrip('/')}/provision/v1/{token}/"


def view(db: Session, i: Intercom, doors: Dict[uuid.UUID, Door]) -> Dict[str, Any]:
    door = doors.get(i.door_id)
    return {"id": str(i.id), "name": i.name, "door_id": str(i.door_id), "door": door.name if door else "", "model": i.model,
            "mac": ":".join(i.mac[n:n + 2] for n in range(0, 12, 2)), "relay_address": i.relay_address, "relay_target": relay_target(db, i),
            "sip_server": i.sip_server, "sip_port": i.sip_port, "sip_transport": i.sip_transport, "sip_user": i.sip_user,
            "sip_password_set": bool(i.sip_password_sealed),
            "last_fetch_at": i.last_fetch_at.isoformat() if i.last_fetch_at else None, "last_fetch_ip": i.last_fetch_ip}


def _doors(db: Session, site: Site) -> Dict[uuid.UUID, Door]:
    return {d.id: d for d in db.execute(select(Door).where(Door.site_id == site.id)).scalars()}


def _door_at(doors: Dict[uuid.UUID, Door], door_id: uuid.UUID) -> Door:
    if door_id not in doors:
        raise problem({"code": "no_such_door", "detail": "That door is not one of this site's"})
    return doors[door_id]


def _intercom(db: Session, site: Site, intercom_id: uuid.UUID) -> Intercom:
    i = db.get(Intercom, intercom_id)
    if i is None or i.site_id != site.id:
        raise not_found()
    return i


def _flush(db: Session) -> None:
    try:
        db.flush()
    except IntegrityError:
        raise problem({"code": "intercom_exists", "detail": "An intercom with that MAC address is already set up"}, 409)


@router.get("/intercoms")
def list_intercoms(site_id: uuid.UUID, ctx: Ctx = Depends(tenant_ctx), db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    site = site_of(db, ctx, site_id, MANAGE)
    doors = _doors(db, site)
    return [view(db, i, doors) for i in db.execute(select(Intercom).where(Intercom.site_id == site.id).order_by(Intercom.name)).scalars()]


@router.post("/intercoms", status_code=201)
def add_intercom(site_id: uuid.UUID, body: IntercomIn, ctx: Ctx = Depends(tenant_ctx), db: Session = Depends(get_db)) -> Dict[str, Any]:
    site = site_of(db, ctx, site_id, MANAGE)
    doors = _doors(db, site)
    _door_at(doors, body.door_id)
    token = secrets.token_urlsafe(24)
    i = Intercom(id=uuid.uuid4(), tenant_id=ctx.tenant_id, site_id=site.id, door_id=body.door_id, name=body.name, model=body.model, mac=body.mac,
                 relay_address=body.relay_address, sip_server=body.sip_server, sip_port=body.sip_port, sip_transport=body.sip_transport,
                 sip_user=body.sip_user, sip_password_sealed=crypto.seal(body.sip_password) if body.sip_password else "",
                 relay_secret_sealed=crypto.seal(akuvox.new_password()), admin_password_sealed=crypto.seal(akuvox.new_password()),
                 provision_token_sealed=crypto.seal(token),
                 provision_token_hash=akuvox.token_hash(token), created_by=ctx.who.id)
    db.add(i)
    _flush(db)
    log(db, ctx, "intercom.add", site_id=site.id, target_type="intercom", target_id=i.id, name=i.name, mac=i.mac, model=i.model)
    db.commit()
    return view(db, i, doors)


@router.patch("/intercoms/{intercom_id}")
def patch_intercom(site_id: uuid.UUID, intercom_id: uuid.UUID, body: IntercomPatch, ctx: Ctx = Depends(tenant_ctx),
                   db: Session = Depends(get_db)) -> Dict[str, Any]:
    site = site_of(db, ctx, site_id, MANAGE)
    i = _intercom(db, site, intercom_id)
    doors = _doors(db, site)
    changes = body.model_dump(exclude_unset=True)
    empty = [k for k, v in changes.items() if v is None]
    if empty:
        raise problem({"code": "invalid", "detail": f"{empty[0]} cannot be empty"})
    if "door_id" in changes:
        _door_at(doors, body.door_id)
    password = changes.pop("sip_password", None)
    for k, v in changes.items():
        setattr(i, k, v)
    if password is not None:
        i.sip_password_sealed = crypto.seal(password) if password else ""
    _flush(db)
    shown = {k: str(v) for k, v in changes.items()}
    if password is not None:
        shown["sip_password"] = "changed"
    log(db, ctx, "intercom.change", site_id=site.id, target_type="intercom", target_id=i.id, **shown)
    db.commit()
    return view(db, i, doors)


@router.delete("/intercoms/{intercom_id}", status_code=204)
def remove_intercom(site_id: uuid.UUID, intercom_id: uuid.UUID, ctx: Ctx = Depends(tenant_ctx), db: Session = Depends(get_db)) -> None:
    site = site_of(db, ctx, site_id, MANAGE)
    i = _intercom(db, site, intercom_id)
    db.delete(i)
    log(db, ctx, "intercom.remove", site_id=site.id, target_type="intercom", target_id=i.id, name=i.name, mac=i.mac)
    db.commit()


@router.get("/intercoms/{intercom_id}/setup")
def setup(site_id: uuid.UUID, intercom_id: uuid.UUID, ctx: Ctx = Depends(tenant_ctx), db: Session = Depends(get_db)) -> Dict[str, Any]:
    """What the installer types into the intercom once (its Autop page), its own admin password afterward, and the code that opens the door
    from a call. Audited: these are secrets."""
    site = site_of(db, ctx, site_id, MANAGE)
    i = _intercom(db, site, intercom_id)
    log(db, ctx, "intercom.setup_view", site_id=site.id, target_type="intercom", target_id=i.id, name=i.name)
    db.commit()
    return {"provision_url": provision_url(crypto.unseal(i.provision_token_sealed)), "unlock_code": akuvox.UNLOCK_CODE,
            "admin_user": akuvox.ADMIN_USER, "admin_password": crypto.unseal(i.admin_password_sealed)}

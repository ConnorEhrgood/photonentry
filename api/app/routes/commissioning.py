"""Installers' licenses and doors' commissioning records (ARCHITECTURE §7.2, §7.7; the rules: app/commissioning.py).

- **Licenses** (`/tenants/{t}/licenses`): the partner's, managed by its own staff (an admin grant from the partner) and read by every customer
  it serves; or the organization's own, for an organization that installs its own doors, managed by its admins. Removing one keeps it (records
  name it). `expiring`: within 30 days.
- **Commissioning** (`/tenants/{t}/sites/{s}/…`): each door's status and newest record; signing a record (admins at the site, in their own
  name, audited); voiding one with a reason (the door needs commissioning again). Records are never edited.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import commissioning as rules
from app.db import get_db
from app.deps import Ctx, require, tenant_ctx
from app.models import Commissioning, Door, License, Site, Tenant, utcnow
from app.routes.common import log, not_found, problem, site_of
from app.routes.tenants import PARTNER_LABEL

router = APIRouter(prefix="/tenants/{tenant_id}")
MANAGE = "entry.config.manage"


def _today() -> date:                       # overridden in tests
    return datetime.now(timezone.utc).date()


# ---- licenses ----


class LicenseIn(BaseModel):
    owner: Literal["partner", "organization"]
    state: Literal["PA", "OH", "WV"]
    kind: str
    holder: str = Field(min_length=1, max_length=128)
    number: str = Field(min_length=1, max_length=64)
    expires_on: Optional[date] = None


class LicensePatch(BaseModel):
    holder: Optional[str] = Field(default=None, min_length=1, max_length=128)
    number: Optional[str] = Field(default=None, min_length=1, max_length=64)
    expires_on: Optional[date] = None


def license_text(lic: License) -> str:
    kind = rules.LICENSE_KINDS.get(lic.state, {}).get(lic.kind, lic.kind)
    to = f", to {lic.expires_on.isoformat()}" if lic.expires_on else ""
    return f"{lic.state} {kind} {lic.number}, {lic.holder}{to}"[:200]


def license_view(lic: License, today: date) -> Dict[str, Any]:
    return {"id": str(lic.id), "owner": "partner" if lic.partner_id else "organization", "state": lic.state, "kind": lic.kind,
            "kind_label": rules.LICENSE_KINDS.get(lic.state, {}).get(lic.kind, lic.kind), "holder": lic.holder, "number": lic.number,
            "expires_on": lic.expires_on.isoformat() if lic.expires_on else None,
            "expired": lic.expires_on is not None and lic.expires_on < today, "expiring": rules.expiring(lic.expires_on, today),
            "removed": lic.removed_at is not None, "text": license_text(lic)}


def _license(db: Session, ctx: Ctx, license_id: uuid.UUID) -> License:
    """A license this organization may use: its own, or its partner's (row-level security shows no other)."""
    lic = db.get(License, license_id)
    tenant = db.get(Tenant, ctx.tenant_id)
    if lic is None or not (lic.tenant_id == ctx.tenant_id or (lic.partner_id is not None and lic.partner_id == tenant.partner_id)):
        raise not_found()
    return lic


@router.get("/licenses")
def list_licenses(ctx: Ctx = Depends(require("entry.view")), db: Session = Depends(get_db)) -> Dict[str, Any]:
    tenant = db.get(Tenant, ctx.tenant_id)
    q = select(License).where(License.removed_at.is_(None))
    owned = License.tenant_id == ctx.tenant_id
    q = q.where(owned | (License.partner_id == tenant.partner_id)) if tenant.partner_id else q.where(owned)
    today = _today()
    rows = db.execute(q.order_by(License.state, License.holder)).scalars().all()
    return {"kinds": rules.LICENSE_KINDS, "can_manage_partner": ctx.source == "partner" and ctx.can(MANAGE) and tenant.partner_id is not None,
            "can_manage_organization": ctx.can(MANAGE), "licenses": [license_view(lic, today) for lic in rows]}


@router.post("/licenses", status_code=201)
def add_license(body: LicenseIn, ctx: Ctx = Depends(require(MANAGE)), db: Session = Depends(get_db)) -> Dict[str, Any]:
    if body.kind not in rules.LICENSE_KINDS[body.state]:
        raise problem({"code": "no_such_kind", "detail": f"That is not a kind of license recorded for {body.state}"})
    tenant = db.get(Tenant, ctx.tenant_id)
    if body.owner == "partner" and (ctx.source != "partner" or tenant.partner_id is None):
        raise problem({"code": "not_partner_staff", "detail": "Only the partner's own staff record the partner's licenses"}, 403)
    lic = License(id=uuid.uuid4(), partner_id=tenant.partner_id if body.owner == "partner" else None,
                  tenant_id=ctx.tenant_id if body.owner == "organization" else None, state=body.state, kind=body.kind,
                  holder=body.holder.strip(), number=body.number.strip(), expires_on=body.expires_on, created_by=ctx.who.id)
    db.add(lic)
    db.flush()
    log(db, ctx, "license.add", target_type="license", target_id=lic.id, text=license_text(lic))
    db.commit()
    return license_view(lic, _today())


def _may_change(ctx: Ctx, lic: License) -> None:
    if lic.partner_id is not None and ctx.source != "partner":
        raise problem({"code": "not_partner_staff", "detail": "Only the partner's own staff change the partner's licenses"}, 403)


@router.patch("/licenses/{license_id}")
def change_license(license_id: uuid.UUID, body: LicensePatch, ctx: Ctx = Depends(require(MANAGE)), db: Session = Depends(get_db)) -> Dict[str, Any]:
    lic = _license(db, ctx, license_id)
    _may_change(ctx, lic)
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        if v is None and k != "expires_on":
            raise problem({"code": "invalid", "detail": f"{k} cannot be empty"})
        setattr(lic, k, v.strip() if isinstance(v, str) else v)
    log(db, ctx, "license.change", target_type="license", target_id=lic.id, text=license_text(lic))
    db.commit()
    return license_view(lic, _today())


@router.delete("/licenses/{license_id}", status_code=204)
def remove_license(license_id: uuid.UUID, ctx: Ctx = Depends(require(MANAGE)), db: Session = Depends(get_db)) -> None:
    lic = _license(db, ctx, license_id)
    _may_change(ctx, lic)
    if lic.removed_at is None:
        lic.removed_at = utcnow()
        log(db, ctx, "license.remove", target_type="license", target_id=lic.id, text=license_text(lic))
        db.commit()


# ---- commissioning ----


class CommissioningIn(BaseModel):
    jurisdiction: Literal["PA", "OH", "WV", "ZZ"]
    lock_type: str
    failure_state: str
    egress: str = Field(max_length=200)
    special_locking: str
    fire_release: str
    fire_tested_on: Optional[date] = None
    fire_tested_by: str = Field(default="", max_length=128)
    rex_checked: bool
    contact_checked: bool
    reader_ul_verified: bool = False
    ahj_reference: str = Field(max_length=128)
    installer: str = Field(max_length=128)
    license_id: Optional[uuid.UUID] = None
    notes: str = Field(default="", max_length=2000)


class VoidIn(BaseModel):
    reason: str = Field(min_length=1, max_length=200)


def _signer(label: str, source: str) -> str:
    return PARTNER_LABEL if source in ("partner", "platform") else label


def record_view(c: Commissioning) -> Dict[str, Any]:
    return {"id": str(c.id), "door_id": str(c.door_id), "jurisdiction": c.jurisdiction, "lock_type": c.lock_type,
            "lock_type_label": rules.LOCK_TYPES.get(c.lock_type, c.lock_type), "failure_state": c.failure_state, "egress": c.egress,
            "special_locking": c.special_locking, "fire_release": c.fire_release,
            "fire_tested_on": c.fire_tested_on.isoformat() if c.fire_tested_on else None, "fire_tested_by": c.fire_tested_by,
            "rex_checked": c.rex_checked, "contact_checked": c.contact_checked, "reader_ul_verified": c.reader_ul_verified,
            "ahj_reference": c.ahj_reference, "installer": c.installer, "license": c.license_text or None, "notes": c.notes,
            "signed_by": _signer(c.signed_by_label, c.signed_by_source), "signed_at": c.signed_at.isoformat(),
            "voided_at": c.voided_at.isoformat() if c.voided_at else None, "voided_by": c.voided_by_label or None, "void_reason": c.void_reason or None}


def _newest(db: Session, door_ids: List[uuid.UUID]) -> Dict[uuid.UUID, Commissioning]:
    out: Dict[uuid.UUID, Commissioning] = {}
    if door_ids:
        for c in db.execute(select(Commissioning).where(Commissioning.door_id.in_(door_ids)).order_by(Commissioning.signed_at)).scalars():
            out[c.door_id] = c
    return out


def _flow(db: Session, ctx: Ctx, site: Site) -> Dict[str, Any]:
    """Decision 27: signing (or voiding) a record changes what the door's controller gets, at once, from the site as last published (never an
    admin's drafts). A site never published has nothing to update yet; its first publish carries it."""
    from app import passes
    try:
        passes.republish(db, site, ctx.who.id, utcnow())
    except passes.PassError as e:
        if e.code == "not_published":
            return {"settings": "not_published"}
        db.rollback()
        return {"settings": "not_updated", "settings_problem": e.detail}
    db.commit()
    return {"settings": "updated"}


def door_status(d: Door, c: Optional[Commissioning]) -> Dict[str, Any]:
    s = rules.status(c.controller_door if c else None, bool(c and c.voided_at), d.controller_door)
    return {"door_id": str(d.id), "door": d.name, "in_service": s.in_service, "why": s.why, "record": record_view(c) if c else None}


@router.get("/sites/{site_id}/commissioning")
def site_commissioning(site_id: uuid.UUID, ctx: Ctx = Depends(tenant_ctx), db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Each door's status and newest record; the site's state (from its address) and the form's choices."""
    site = site_of(db, ctx, site_id, "entry.view")
    doors = db.execute(select(Door).where(Door.site_id == site.id).order_by(Door.name)).scalars().all()
    newest = _newest(db, [d.id for d in doors])
    return {"jurisdiction": rules.state_of(site.address) or "ZZ", "required_license": rules.REQUIRED,
            "lock_types": rules.LOCK_TYPES, "special_locking": rules.SPECIAL,
            "doors": [door_status(d, newest.get(d.id)) for d in doors]}


def _door(db: Session, site: Site, door_id: uuid.UUID) -> Door:
    d = db.get(Door, door_id)
    if d is None or d.site_id != site.id:
        raise not_found()
    return d


@router.get("/sites/{site_id}/doors/{door_id}/commissioning")
def door_history(site_id: uuid.UUID, door_id: uuid.UUID, ctx: Ctx = Depends(tenant_ctx), db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    site = site_of(db, ctx, site_id, "entry.view")
    d = _door(db, site, door_id)
    rows = db.execute(select(Commissioning).where(Commissioning.door_id == d.id).order_by(Commissioning.signed_at.desc())).scalars().all()
    return [record_view(c) for c in rows]


@router.post("/sites/{site_id}/doors/{door_id}/commissioning", status_code=201)
def sign(site_id: uuid.UUID, door_id: uuid.UUID, body: CommissioningIn, ctx: Ctx = Depends(tenant_ctx), db: Session = Depends(get_db)) -> Dict[str, Any]:
    site = site_of(db, ctx, site_id, MANAGE)
    d = _door(db, site, door_id)
    lic = _license(db, ctx, body.license_id) if body.license_id else None
    today = _today()
    facts = rules.LicenseFacts(lic.state, lic.kind, lic.expires_on, lic.removed_at is not None) if lic else None
    record = rules.Record(body.jurisdiction, body.lock_type, body.failure_state, body.special_locking, body.fire_release, body.fire_tested_on,
                          body.fire_tested_by, body.rex_checked, body.contact_checked, body.reader_ul_verified, body.ahj_reference, body.installer,
                          body.egress)
    found = rules.problems(record, facts, today)
    if found:
        raise problem({"code": "incomplete", "detail": found[0], "problems": found})
    c = Commissioning(id=uuid.uuid4(), tenant_id=ctx.tenant_id, site_id=site.id, door_id=d.id, controller_door=d.controller_door,
                      jurisdiction=body.jurisdiction, lock_type=body.lock_type, failure_state=body.failure_state, egress=body.egress.strip(),
                      special_locking=body.special_locking, fire_release=body.fire_release,
                      fire_tested_on=body.fire_tested_on if body.fire_release == "tested" else None,
                      fire_tested_by=body.fire_tested_by.strip() if body.fire_release == "tested" else "",
                      rex_checked=True, contact_checked=True, reader_ul_verified=body.reader_ul_verified, ahj_reference=body.ahj_reference.strip(),
                      installer=body.installer.strip(), license_id=lic.id if lic else None, license_text=license_text(lic) if lic else "",
                      notes=body.notes.strip(), signed_by=ctx.who.id, signed_by_label=ctx.who.label[:200], signed_by_source=ctx.source,
                      signed_at=utcnow())
    db.add(c)
    db.flush()
    log(db, ctx, "door.commission", site_id=site.id, target_type="door", target_id=d.id, record=str(c.id), installer=c.installer,
        license=c.license_text)
    db.commit()
    return {**door_status(d, c), **_flow(db, ctx, site)}


@router.post("/sites/{site_id}/doors/{door_id}/commissioning/void")
def void(site_id: uuid.UUID, door_id: uuid.UUID, body: VoidIn, ctx: Ctx = Depends(tenant_ctx), db: Session = Depends(get_db)) -> Dict[str, Any]:
    """The door needs commissioning again (new lock, rewired, a failed test), with the reason. The record itself stays."""
    site = site_of(db, ctx, site_id, MANAGE)
    d = _door(db, site, door_id)
    c = _newest(db, [d.id]).get(d.id)
    if c is None or c.voided_at is not None:
        raise problem({"code": "not_in_service", "detail": "This door has no record in force"}, 409)
    reason = " ".join(body.reason.split())
    if not reason:
        raise problem({"code": "invalid", "detail": "Say why"})
    c.voided_at, c.voided_by_label, c.void_reason = utcnow(), _signer(ctx.who.label, ctx.source)[:200], reason
    log(db, ctx, "door.commission_void", site_id=site.id, target_type="door", target_id=d.id, record=str(c.id), reason=reason)
    db.commit()
    return {**door_status(d, c), **_flow(db, ctx, site)}

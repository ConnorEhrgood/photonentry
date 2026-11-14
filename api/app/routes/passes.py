"""Visitors' passes (app/passes.py): operators and up issue and revoke them at their sites; the visitor opens their own pass at a link.

- `GET /tenants/{t}/sites/{s}/passes` the site's passes, newest first; `GET …/visitor-groups` the groups admins opened to visitors.
- `POST …/passes` issue one (and email the visitor its link when an address is given and mail is configured); `POST …/passes/{id}/revoke`.
- `GET /passes/v1/{token}` the visitor's own pass (no sign-in; the token is the secret; limited per address): PIN and card number only while it
  is active or about to be.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import crypto, mail, passes
from app.config import settings
from app.db import SystemSession, get_db
from app.deps import Ctx, tenant_ctx
from app.models import AccessGroup, Site, VisitorPass
from app.routes.common import not_found, problem, site_of
from app.throttle import Throttle

router = APIRouter()
VISITORS = "entry.visitors.manage"
pass_throttle = Throttle(limit=30, window_s=60)


def get_mailer() -> mail.Sender:          # overridden in tests
    return mail.send


def _now() -> datetime:
    return datetime.now(timezone.utc)


def link(token: str) -> str:
    return f"{settings.web_url.rstrip('/')}/pass/{token}"


class PassIn(BaseModel):
    visitor_name: str = Field(min_length=1, max_length=128)
    visitor_email: Optional[str] = Field(default=None, max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    group_id: uuid.UUID
    valid_from: datetime
    valid_to: datetime


def view(p: VisitorPass, group: str, now: datetime) -> Dict[str, Any]:
    return {"id": str(p.id), "visitor_name": p.visitor_name, "visitor_email": p.visitor_email or None, "group_id": str(p.group_id), "group": group,
            "valid_from": p.valid_from.isoformat(), "valid_to": p.valid_to.isoformat(), "state": passes.state(p, now), "host": p.host_label,
            "created_at": p.created_at.isoformat(), "emailed": p.emailed_at is not None, "link": link(crypto.unseal(p.token_sealed)),
            "revoked_by": p.revoked_by_label or None}


def _fail(e: passes.PassError) -> HTTPException:
    return problem({"code": e.code, "detail": e.detail}, e.status)


@router.get("/tenants/{tenant_id}/sites/{site_id}/visitor-groups")
def visitor_groups(site_id: uuid.UUID, ctx: Ctx = Depends(tenant_ctx), db: Session = Depends(get_db)) -> List[Dict[str, str]]:
    site = site_of(db, ctx, site_id, VISITORS)
    rows = db.execute(select(AccessGroup).where(AccessGroup.site_id == site.id, AccessGroup.for_visitors.is_(True)).order_by(AccessGroup.name)).scalars()
    return [{"id": str(g.id), "name": g.name} for g in rows]


@router.get("/tenants/{tenant_id}/sites/{site_id}/passes")
def list_passes(site_id: uuid.UUID, ctx: Ctx = Depends(tenant_ctx), db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    site = site_of(db, ctx, site_id, VISITORS)
    groups = {g.id: g.name for g in db.execute(select(AccessGroup).where(AccessGroup.site_id == site.id)).scalars()}
    rows = db.execute(select(VisitorPass).where(VisitorPass.site_id == site.id).order_by(VisitorPass.valid_from.desc()).limit(200)).scalars()
    now = _now()
    return [view(p, groups.get(p.group_id, ""), now) for p in rows]


@router.post("/tenants/{tenant_id}/sites/{site_id}/passes", status_code=201)
def issue(site_id: uuid.UUID, body: PassIn, ctx: Ctx = Depends(tenant_ctx), db: Session = Depends(get_db),
          send: mail.Sender = Depends(get_mailer)) -> Dict[str, Any]:
    site = site_of(db, ctx, site_id, VISITORS)            # the person, checked in their own session first
    name, email = " ".join(body.visitor_name.split()), (body.visitor_email or "")
    if not name:
        raise problem({"code": "invalid", "detail": "Give the visitor's name"})
    now = _now()
    with SystemSession() as s:                            # then the system writes it (operators cannot write cardholders or credentials)
        try:
            p, token = passes.issue(s, site=s.get(Site, site.id), group_id=body.group_id, visitor_name=name, visitor_email=email,
                                    valid_from=body.valid_from, valid_to=body.valid_to, host_id=ctx.who.id, host_label=ctx.who.label,
                                    actor_source=ctx.source, now=now)
        except passes.PassError as e:
            s.rollback()
            raise _fail(e)
        secrets_ = passes.secret_values(s, p)
        group = s.get(AccessGroup, p.group_id).name
        s.commit()
        if email:
            body_text = (f"{ctx.who.name or 'Your host'} made you a pass for {site.name}{f', {site.address}' if site.address else ''}.\n\n"
                         f"From {p.valid_from:%a %b %d, %Y %H:%M} to {p.valid_to:%a %b %d, %Y %H:%M} (UTC).\n\nYour pass: {link(token)}\n")
            try:
                if send(email, f"Your pass for {site.name}", body_text):
                    p.emailed_at = _now()
                    s.commit()
            except httpx.HTTPError:
                pass                                      # the pass stands; the host shares its link
        return {**view(p, group, now), **secrets_}


@router.post("/tenants/{tenant_id}/sites/{site_id}/passes/{pass_id}/revoke")
def revoke(site_id: uuid.UUID, pass_id: uuid.UUID, ctx: Ctx = Depends(tenant_ctx), db: Session = Depends(get_db)) -> Dict[str, Any]:
    site = site_of(db, ctx, site_id, VISITORS)
    if db.get(VisitorPass, pass_id) is None:              # row-level security: one of the person's sites' passes, or nothing
        raise not_found()
    with SystemSession() as s:
        p = s.get(VisitorPass, pass_id)
        if p.site_id != site.id:
            raise not_found()
        try:
            passes.revoke(s, p, s.get(Site, site.id), by_id=ctx.who.id, by_label=ctx.who.label, actor_source=ctx.source, now=_now())
        except passes.PassError as e:
            s.rollback()
            raise _fail(e)
        group = s.get(AccessGroup, p.group_id)
        s.commit()
        return view(p, group.name if group else "", _now())


@router.get("/passes/v1/{token}")
def visitor_page(token: str, request: Request) -> Dict[str, Any]:
    """The visitor's own pass. The same 404 for every miss."""
    pass_throttle.check(request)
    if len(token) > 64:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    with SystemSession() as s:
        p = s.execute(select(VisitorPass).where(VisitorPass.token_hash == passes.token_hash(token))).scalar_one_or_none()
        if p is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
        site = s.get(Site, p.site_id)
        st = passes.state(p, _now())
        values = passes.secret_values(s, p) if st in ("active", "upcoming") else {"pin": None, "card_number": None}
        return {"visitor_name": p.visitor_name, "site": site.name, "address": site.address, "timezone": site.timezone, "host": p.host_label,
                "valid_from": p.valid_from.isoformat(), "valid_to": p.valid_to.isoformat(), "state": st, **values}

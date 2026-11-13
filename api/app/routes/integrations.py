"""PhotonGuard and PhotonConsole, set up from PhotonEntry (Settings), and the PhotonConsole feed itself.

- **Guard:** an admin pastes the ingest token their Guard admin made (scope `guard:events:write`); PhotonEntry seals it and the worker sends the
  doors' events (app/guard.py). Each door's binding key is listed so the Guard admin can bind it to the cameras that see the door. A test sends
  one event that no camera shows.
- **Console:** an admin makes a feed token for a PhotonConsole data source (shown once); Console polls `GET /integrations/console/v1/doors`.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import consolefeed, crypto, guard
from app.config import settings
from app.db import SystemSession, get_db
from app.deps import Ctx, require
from app.models import ConsoleFeedToken, Door, GuardLink, Site
from app.routes.common import log, not_found, problem

router = APIRouter()
MANAGE = "entry.config.manage"


def get_guard_post() -> guard.Post:        # overridden in tests
    return guard.http_post


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---- Guard ----


class GuardIn(BaseModel):
    token: str = Field(min_length=20, max_length=400, pattern=r"^[A-Za-z0-9._~+/=-]+$")


class GuardPatch(BaseModel):
    enabled: bool


def _guard_view(db: Session, ctx: Ctx, link: Optional[GuardLink]) -> Dict[str, Any]:
    sites = {s.id: s.name for s in db.execute(select(Site).where(Site.tenant_id == ctx.tenant_id)).scalars()}
    doors = db.execute(select(Door).where(Door.tenant_id == ctx.tenant_id).order_by(Door.name)).scalars().all()
    return {"connected": link is not None, "enabled": bool(link and link.enabled), "token_hint": link.token_hint if link else None,
            "last_ok_at": link.last_ok_at.isoformat() if link and link.last_ok_at else None, "last_error": link.last_error if link else "",
            "last_error_at": link.last_error_at.isoformat() if link and link.last_error_at else None, "sent": link.sent if link else 0,
            "guard_api_url": settings.guard_api_url,
            "bindings": [{"door_id": str(d.id), "door": d.name, "site": sites.get(d.site_id, ""), "binding": guard.binding(d)} for d in doors]}


@router.get("/tenants/{tenant_id}/integrations/guard")
def get_guard(ctx: Ctx = Depends(require(MANAGE)), db: Session = Depends(get_db)) -> Dict[str, Any]:
    return _guard_view(db, ctx, db.get(GuardLink, ctx.tenant_id))


@router.put("/tenants/{tenant_id}/integrations/guard")
def connect_guard(body: GuardIn, ctx: Ctx = Depends(require(MANAGE)), db: Session = Depends(get_db)) -> Dict[str, Any]:
    link = db.get(GuardLink, ctx.tenant_id)
    hint = "…" + body.token[-4:]
    if link is None:
        link = GuardLink(tenant_id=ctx.tenant_id, token_sealed=crypto.seal(body.token), token_hint=hint, enabled=True, created_by=ctx.who.id)
        db.add(link)
    else:
        link.token_sealed, link.token_hint, link.enabled = crypto.seal(body.token), hint, True
    log(db, ctx, "guard.connect", target_type="integration", target_id="guard", token=hint)
    db.commit()
    return _guard_view(db, ctx, link)


@router.patch("/tenants/{tenant_id}/integrations/guard")
def pause_guard(body: GuardPatch, ctx: Ctx = Depends(require(MANAGE)), db: Session = Depends(get_db)) -> Dict[str, Any]:
    link = db.get(GuardLink, ctx.tenant_id)
    if link is None:
        raise not_found()
    link.enabled = body.enabled
    log(db, ctx, "guard.resume" if body.enabled else "guard.pause", target_type="integration", target_id="guard")
    db.commit()
    return _guard_view(db, ctx, link)


@router.delete("/tenants/{tenant_id}/integrations/guard", status_code=204)
def disconnect_guard(ctx: Ctx = Depends(require(MANAGE)), db: Session = Depends(get_db)) -> None:
    link = db.get(GuardLink, ctx.tenant_id)
    if link is None:
        raise not_found()
    db.delete(link)
    log(db, ctx, "guard.disconnect", target_type="integration", target_id="guard")
    db.commit()


@router.post("/tenants/{tenant_id}/integrations/guard/test")
def test_guard(ctx: Ctx = Depends(require(MANAGE)), db: Session = Depends(get_db), post: guard.Post = Depends(get_guard_post)) -> Dict[str, Any]:
    link = db.get(GuardLink, ctx.tenant_id)
    if link is None:
        raise not_found()
    url = f"{settings.guard_api_url.rstrip('/')}/ingest/v1/events"
    try:
        code = post(url, crypto.unseal(link.token_sealed), guard.test_message())
    except httpx.HTTPError as e:
        return {"ok": False, "detail": f"PhotonGuard could not be reached ({type(e).__name__})."}
    if code in (401, 403):
        return {"ok": False, "detail": "PhotonGuard refused the token: make a new ingest token in PhotonGuard and paste it here."}
    if code >= 300:
        return {"ok": False, "detail": f"PhotonGuard answered HTTP {code}."}
    return {"ok": True, "detail": "PhotonGuard accepted a test event."}


# ---- Console feed tokens ----


class TokenIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    console_tenant_id: Optional[uuid.UUID] = None


def _token_view(t: ConsoleFeedToken) -> Dict[str, Any]:
    return {"id": str(t.id), "name": t.name, "console_tenant_id": str(t.console_tenant_id) if t.console_tenant_id else None,
            "created_at": t.created_at.isoformat(), "last_used_at": t.last_used_at.isoformat() if t.last_used_at else None,
            "revoked": t.revoked_at is not None}


@router.get("/tenants/{tenant_id}/integrations/console/tokens")
def list_tokens(ctx: Ctx = Depends(require(MANAGE)), db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    rows = db.execute(select(ConsoleFeedToken).where(ConsoleFeedToken.tenant_id == ctx.tenant_id).order_by(ConsoleFeedToken.created_at)).scalars()
    return [_token_view(t) for t in rows]


@router.post("/tenants/{tenant_id}/integrations/console/tokens", status_code=201)
def make_token(body: TokenIn, ctx: Ctx = Depends(require(MANAGE)), db: Session = Depends(get_db)) -> Dict[str, Any]:
    secret = consolefeed.new_secret()
    t = ConsoleFeedToken(id=uuid.uuid4(), tenant_id=ctx.tenant_id, console_tenant_id=body.console_tenant_id, name=body.name,
                         token_hash=consolefeed.hash_token(secret), created_by=ctx.who.id, created_at=_now())
    db.add(t)
    log(db, ctx, "console_token.issue", target_type="console_token", target_id=t.id, name=t.name)
    db.commit()
    return {**_token_view(t), "token": secret, "feed_url": "/integrations/console/v1/doors"}


@router.delete("/tenants/{tenant_id}/integrations/console/tokens/{token_id}", status_code=204)
def revoke_token(token_id: uuid.UUID, ctx: Ctx = Depends(require(MANAGE)), db: Session = Depends(get_db)) -> None:
    t = db.get(ConsoleFeedToken, token_id)
    if t is None or t.tenant_id != ctx.tenant_id or t.revoked_at is not None:
        raise not_found()
    t.revoked_at = _now()
    log(db, ctx, "console_token.revoke", target_type="console_token", target_id=t.id, name=t.name)
    db.commit()


# ---- the feed ----


@router.get("/integrations/console/v1/doors")
def console_feed(authorization: Optional[str] = Header(None), db: Session = Depends(get_db)) -> Dict[str, Any]:
    """PhotonConsole's poll. 401 JSON with `WWW-Authenticate: Bearer`, never a redirect, for anything but a live token."""
    refused = HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid feed token", headers={"WWW-Authenticate": "Bearer"})
    if not authorization or not authorization.lower().startswith("bearer "):
        raise refused
    now = _now()
    with SystemSession() as system:
        caller = consolefeed.authenticate(system, db, authorization[7:].strip(), now)
    if caller is None:
        raise refused
    return consolefeed.build(db, caller, now)

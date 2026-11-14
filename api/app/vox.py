"""PhotonVox, for the intercoms (docs/VOX.md; contract/vox/): door stations' SIP accounts onto intercoms, and who answered a door's call.

CRITICAL: SIP passwords cross from another product, and a person's name is put on a door opening. Every answer is checked against the
contract and must name the organization the token was connected for; anything else is an error, never data.

Nothing here is on the door's path: the intercom keeps the SIP account it was last given, and opening a door from a call needs only the
intercom and entry-link. PhotonVox being away only delays a name in the door's events.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app import crypto
from app.config import settings
from app.models import CallMatch, DoorEvent, Intercom, VoxLink

log = logging.getLogger("photonentry.vox")
UNLOCK = "PhotonEntry/Intercom/Unlock"
SETTLE = timedelta(seconds=20)       # PhotonVox's call record of a call that just ended may take a moment to land
GIVE_UP = timedelta(minutes=10)      # after this, "no answered call" is the answer
LOOK_BACK = timedelta(days=1)
WINDOW_S = 120
BATCH = 50

# (url, token, params) -> (HTTP status, parsed JSON or None); raises httpx.HTTPError when PhotonVox cannot be reached.
Fetch = Callable[[str, str, Dict[str, str]], Tuple[int, Any]]


def http_get(url: str, token: str, params: Dict[str, str]) -> Tuple[int, Any]:
    r = httpx.get(url, params=params, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"}, timeout=5.0)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, None


class _Doc(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Sip(_Doc):
    server: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)
    transport: Literal["udp", "tcp", "tls"]
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)
    outbound_proxy: Optional[str] = Field(default=None, pattern=r"^[A-Za-z0-9.-]+:[0-9]{1,5}$")


class Station(_Doc):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    name: str = Field(min_length=1, max_length=64)
    site_id: Optional[uuid.UUID]
    extension: str = Field(pattern=r"^[0-9]{2,8}$")
    sip: Sip
    updated_at: datetime


class Stations(_Doc):
    organization_id: uuid.UUID
    stations: List[Station] = Field(max_length=2000)


class AnsweredBy(_Doc):
    extension: str = Field(max_length=32)
    name: str = Field(max_length=128)
    person_id: Optional[uuid.UUID]


class Call(_Doc):
    id: str = Field(min_length=1, max_length=128)
    started_at: datetime
    answered_at: Optional[datetime]
    ended_at: Optional[datetime]
    answered_by: Optional[AnsweredBy]


class DoorCall(_Doc):
    organization_id: uuid.UUID
    station_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    call: Optional[Call]


class VoxError(Exception):
    """Something to tell the admin, in a sentence."""


class NotFound(VoxError):
    pass


def _get(fetch: Fetch, token: str, path: str, params: Dict[str, str], tenant_id: uuid.UUID, model: type) -> Any:
    try:
        status, body = fetch(f"{settings.vox_api_url.rstrip('/')}{path}", token, params)
    except httpx.HTTPError as e:
        raise VoxError(f"PhotonVox could not be reached ({type(e).__name__})")
    if status == 401:
        raise VoxError("PhotonVox refused the token: make a new integration token for PhotonEntry in PhotonVox and paste it here")
    if status == 403:
        raise VoxError("The token cannot read door stations: it needs the scope vox:entry")
    if status == 404:
        raise NotFound("PhotonVox has no such door station")
    if status != 200:
        raise VoxError(f"PhotonVox answered HTTP {status}")
    try:
        doc = model.model_validate(body)
    except ValidationError:
        raise VoxError("PhotonVox's answer is not what PhotonEntry expects (contract/vox)")
    if doc.organization_id != tenant_id:
        raise VoxError("PhotonVox answered for another organization: the token was made in another organization's PhotonVox")
    return doc


def stations(fetch: Fetch, token: str, tenant_id: uuid.UUID) -> List[Station]:
    return _get(fetch, token, "/integrations/entry/v1/door-stations", {}, tenant_id, Stations).stations


def door_call(fetch: Fetch, token: str, tenant_id: uuid.UUID, station_id: str, at: datetime) -> Optional[Call]:
    params = {"station": station_id, "at": at.isoformat(), "window_s": str(WINDOW_S)}
    doc = _get(fetch, token, "/integrations/entry/v1/door-calls", params, tenant_id, DoorCall)
    if doc.station_id != station_id:
        raise VoxError("PhotonVox answered about another door station")
    return doc.call


def copy_sip(i: Intercom, s: Station, now: datetime) -> bool:
    """Put the station's SIP account on the intercom (sealed). True if anything changed (the intercom gets it at its next hourly fetch)."""
    old = (i.vox_station_id, i.sip_server, i.sip_port, i.sip_transport, i.sip_user, i.sip_outbound_proxy,
           crypto.unseal(i.sip_password_sealed) if i.sip_password_sealed else "")
    new = (s.id, s.sip.server, s.sip.port, s.sip.transport, s.sip.username, s.sip.outbound_proxy or "", s.sip.password)
    i.sip_synced_at = now
    if old == new:
        return False
    i.vox_station_id, i.sip_server, i.sip_port, i.sip_transport, i.sip_user, i.sip_outbound_proxy = new[:6]
    i.sip_password_sealed = crypto.seal(s.sip.password)
    return True


def _ok(link: VoxLink, now: datetime) -> None:
    link.last_ok_at, link.last_error, link.last_error_at = now, "", None


def _failed(link: VoxLink, e: VoxError, now: datetime) -> None:
    link.last_error, link.last_error_at = str(e), now
    log.warning("vox: organization %s: %s", link.tenant_id, e)


def sync_tenant(db: Session, link: VoxLink, fetch: Fetch, now: datetime) -> int:
    """Every intercom with a door station gets that station's SIP account as PhotonVox has it now. A station PhotonVox no longer has leaves its
    intercom as it was (still registered with the old account until PhotonVox removes it), and is reported. Returns the intercoms changed."""
    try:
        found = {s.id: s for s in stations(fetch, crypto.unseal(link.token_sealed), link.tenant_id)}
    except VoxError as e:
        _failed(link, e, now)
        return 0
    changed, gone = 0, []
    for i in db.execute(select(Intercom).where(Intercom.tenant_id == link.tenant_id, Intercom.vox_station_id != "")).scalars():
        s = found.get(i.vox_station_id)
        if s is None:
            gone.append(i.name)
        elif copy_sip(i, s, now):
            changed += 1
    if gone:
        _failed(link, VoxError(f"PhotonVox no longer has the door station of {', '.join(sorted(gone))}"), now)
    else:
        _ok(link, now)
    return changed


def match_tenant(db: Session, link: VoxLink, fetch: Fetch, now: datetime, batch: int = BATCH) -> int:
    """Name who answered the call behind each recent "Opened from the intercom". Returns the events settled."""
    rows = db.execute(
        select(DoorEvent).outerjoin(CallMatch, and_(CallMatch.controller_id == DoorEvent.controller_id, CallMatch.seq == DoorEvent.seq))
        .where(DoorEvent.tenant_id == link.tenant_id, DoorEvent.topic == UNLOCK, CallMatch.seq.is_(None),
               DoorEvent.occurred_at >= now - LOOK_BACK, DoorEvent.occurred_at <= now - SETTLE)
        .order_by(DoorEvent.occurred_at).limit(batch)).scalars().all()
    if not rows:
        return 0
    intercoms = {str(i.id): i for i in db.execute(select(Intercom).where(Intercom.tenant_id == link.tenant_id)).scalars()}
    token = crypto.unseal(link.token_sealed)
    settled = 0
    for e in rows:
        i = intercoms.get(e.source.get("IntercomId", ""))
        if e.data.get("Result") != "ok" or i is None or not i.vox_station_id:
            db.add(CallMatch(controller_id=e.controller_id, seq=e.seq, tenant_id=e.tenant_id, state="none", matched_at=now))
            settled += 1
            continue
        try:
            call = door_call(fetch, token, link.tenant_id, i.vox_station_id, e.occurred_at)
        except NotFound:
            call = None
        except VoxError as err:
            _failed(link, err, now)
            return settled                      # PhotonVox is away or refusing: the rest wait for the next round
        if call is not None and call.answered_by is not None:
            a = call.answered_by
            db.add(CallMatch(controller_id=e.controller_id, seq=e.seq, tenant_id=e.tenant_id, state="found", call_id=call.id,
                             extension=a.extension, name=a.name, person_id=a.person_id, matched_at=now))
        elif now - e.occurred_at >= GIVE_UP:
            db.add(CallMatch(controller_id=e.controller_id, seq=e.seq, tenant_id=e.tenant_id, state="none", matched_at=now))
        else:
            continue                            # not in PhotonVox's records yet: next round
        settled += 1
    _ok(link, now)
    return settled


def run_all(db: Session, fetch: Fetch, now: datetime, sync: bool) -> Tuple[int, int]:
    """Every connected organization: match calls, and (hourly) refresh the intercoms' SIP accounts. Committed per organization."""
    changed = matched = 0
    for link in db.execute(select(VoxLink)).scalars().all():
        matched += match_tenant(db, link, fetch, now)
        if sync:
            changed += sync_tenant(db, link, fetch, now)
        db.commit()
    return changed, matched


def answered(m: Optional[CallMatch]) -> Optional[str]:
    """How the door's events name who opened it from a call: "Ann Lee (101)"."""
    if m is None or m.state != "found":
        return None
    return f"{m.name} ({m.extension})" if m.name else m.extension

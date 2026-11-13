"""Door events to PhotonGuard (ARCHITECTURE §9.1; Guard's ingest, Guard ARCHITECTURE §7.6; what is sent is pinned in contract/guard/).

The worker offers each controller's events to Guard in order, once, for every organization with a Guard link:
- **granted** and **denied** go as instant events on the door's binding (`entry-door-<door id>`), each asking for a clip from 10 s before to
  20 s after, so Guard's timeline shows "Denied: outside its schedule: Bob Jones at Side door" on the cameras that see that door;
- **forced** and **held open** start an alarm (severity critical, a clip); the door's alarm clearing ends it under the same `dedup_key`.
  **Tamper** likewise. Guard opens an incident for them (the `access` source, a change Guard's design takes on: §14);
- everything else (door modes, opening and closing, the exit button) stays in PhotonEntry: it is noise on a camera's timeline.

Exactly once and in order: a controller's cursor moves only past events that Guard accepted or that are not for Guard. A refusal stops that
organization's sending until the next pass (the error is shown in Settings); nothing is skipped. The `dedup_key` of an instant event is the
controller's own event token, so a duplicate from a controller's crash (contract/link) is one event in Guard too.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import crypto
from app.config import settings
from app.doorindex import DoorIndex, cardholder_id, for_controllers
from app.events import Normal, normalize
from app.models import Cardholder, Controller, Door, DoorAlarm, DoorEvent, GuardCursor, GuardLink

log = logging.getLogger("photonentry.guard")
BATCH = 200
CLIP = {"pre_s": 10, "post_s": 20}
ALARM_KINDS = {"forced": "alarm", "held_open": "alarm", "tamper": "tamper"}
ENDS = {"alarm_cleared": "alarm", "tamper_cleared": "tamper"}

# (url, token, payload) -> HTTP status; raises httpx.HTTPError when Guard cannot be reached.
Post = Callable[[str, str, Dict[str, Any]], int]


def http_post(url: str, token: str, payload: Dict[str, Any]) -> int:
    return httpx.post(url, json=payload, headers={"Authorization": f"Bearer {token}"}, timeout=10, follow_redirects=False).status_code


def binding(door: Door) -> str:
    """The Guard binding a door's events go to: the Guard admin binds it to the cameras that see the door (shown in PhotonEntry's settings)."""
    return f"entry-door-{door.id}"


@dataclass
class Message:
    payload: Dict[str, Any]
    opens: Optional[Tuple[str, str]] = None      # (alarm kind, dedup key): remember an alarm Guard now knows has started
    closes: Optional[str] = None                 # alarm kind whose end this is


def message(e: DoorEvent, n: Normal, door: Door, holder: Optional[str], open_alarms: Dict[str, str]) -> Optional[Message]:
    """What Guard is told about one event, or None when Guard is not told (CRITICAL: it decides what crosses to another product)."""
    who = f": {holder}" if holder else ""
    base = {"source": {"kind": "photonentry", "key": f"door:{door.id}", "name": door.name}, "occurred_at": e.occurred_at.isoformat(),
            "kind": "external", "severity": n.severity, "targets": {"binding": binding(door)},
            "link": f"{settings.web_url}/events?site={door.site_id}",
            "attributes": {"door": door.name, "entry_kind": n.kind, "reason": n.reason or "", "cardholder": holder or ""}}
    if n.kind in ("granted", "denied"):
        if n.method == "rex":
            return None
        return Message({**base, "dedup_key": f"entry:{e.controller_id}:{e.ref or e.seq}", "state": "instant",
                        "label": f"{n.label}{who} at {door.name}", "record": CLIP})
    if n.kind in ALARM_KINDS:
        kind = ALARM_KINDS[n.kind]
        if kind in open_alarms:
            return None                          # already started (held open after forced, a repeated tamper): one alarm until it ends
        key = f"entry:{kind}:{door.id}:{e.controller_id}:{e.seq}"
        return Message({**base, "dedup_key": key, "state": "started", "label": f"{n.label}: {door.name}", "record": CLIP}, opens=(kind, key))
    if n.kind in ENDS:
        kind = ENDS[n.kind]
        if kind not in open_alarms:
            return None
        return Message({**base, "dedup_key": open_alarms[kind], "state": "ended", "severity": "info", "label": f"{n.label}: {door.name}",
                        "record": False}, closes=kind)
    return None


@dataclass
class Result:
    sent: int = 0
    stopped: Optional[str] = None


def forward_tenant(db: Session, link: GuardLink, post: Post, now: datetime, batch: int = BATCH) -> Result:
    """One pass for one organization. `db` is a system session; commits as it goes, so what Guard accepted is never offered again."""
    out = Result()
    token = crypto.unseal(link.token_sealed)
    url = f"{settings.guard_api_url.rstrip('/')}/ingest/v1/events"
    controllers = db.execute(select(Controller).where(Controller.tenant_id == link.tenant_id, Controller.state != "pending")).scalars().all()
    index: DoorIndex = for_controllers(db, controllers)
    for c in controllers:
        cursor = db.get(GuardCursor, c.id)
        if cursor is None:
            cursor = GuardCursor(controller_id=c.id, tenant_id=link.tenant_id, seq=0)
            db.add(cursor)
        events = db.execute(select(DoorEvent).where(DoorEvent.controller_id == c.id, DoorEvent.seq > cursor.seq)
                            .order_by(DoorEvent.seq).limit(batch)).scalars().all()
        for e in events:
            door = index.door_of(c.id, e.source)
            msg = None
            if door is not None:
                alarms = {a.kind: a.dedup_key for a in db.execute(select(DoorAlarm).where(DoorAlarm.door_id == door.id)).scalars()}
                hid = cardholder_id(e.data)
                row = db.get(Cardholder, hid) if hid else None
                holder = row.name if row else None
                msg = message(e, normalize(e.topic, e.data), door, holder, alarms)
            if msg is not None:
                try:
                    status = post(url, token, msg.payload)
                except httpx.HTTPError as err:
                    out.stopped = f"Guard could not be reached: {type(err).__name__}"
                    break
                if status >= 300:
                    out.stopped = f"Guard refused an event (HTTP {status})"
                    break
                out.sent += 1
                if msg.opens:
                    db.add(DoorAlarm(door_id=door.id, kind=msg.opens[0], tenant_id=link.tenant_id, dedup_key=msg.opens[1], started_at=e.occurred_at))
                if msg.closes:
                    db.execute(DoorAlarm.__table__.delete().where(DoorAlarm.door_id == door.id, DoorAlarm.kind == msg.closes))
            cursor.seq = e.seq
            db.commit()
        if out.stopped:
            break
    link = db.get(GuardLink, link.tenant_id)
    if out.stopped:
        link.last_error, link.last_error_at = out.stopped, now
        log.warning("guard: %s: %s", link.tenant_id, out.stopped)
    elif out.sent:
        link.last_ok_at, link.last_error = now, ""
    link.sent += out.sent
    db.commit()
    return out


def forward_all(db: Session, post: Post, now: datetime) -> List[Result]:
    links = db.execute(select(GuardLink).where(GuardLink.enabled.is_(True))).scalars().all()
    return [forward_tenant(db, link, post, now) for link in links]


def test_message(door_name: str = "") -> Dict[str, Any]:
    """What "Send a test event" sends: shown on no camera (an unbound key), recorded nowhere; it proves the token and the address."""
    return {"source": {"kind": "photonentry", "key": "test", "name": "PhotonEntry"}, "dedup_key": f"entry:test:{datetime.now().timestamp()}",
            "state": "instant", "occurred_at": datetime.now().astimezone().isoformat(), "kind": "external", "severity": "info",
            "label": "PhotonEntry connection test", "targets": {"binding": "entry-connection-test"}, "record": False,
            "attributes": {"door": door_name, "entry_kind": "test", "reason": "", "cardholder": ""}}

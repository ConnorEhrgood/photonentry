"""PhotonEntry's line on the suite's home dashboard (photonid docs/HOME-PLAN.md §2, contract photonid directory/contract/summary.schema.json):
"8 of 8 doors online", per organization and per site. CRITICAL: it crosses to another app, and must say only what the person may see.

Worked out from what PhotonEntry already keeps (controllers' last contact, the doors' newest alarm state), never by asking a controller. Run in the
person's own session, so row-level security limits it to the sites they reach; cached 30 s per organization and scope (a viewer of one site never
gets the whole organization's answer from the cache).

A door is online when its controller is: claimed, not out of service, and heard from in the last two minutes. `attention` when a door is offline
or has an open alarm (forced or held open); `down` when none of the doors is online; `unknown` with no doors yet.
"""
from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, Hashable, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.consolefeed import OFFLINE_AFTER, _door_states
from app.models import Controller, Door, Site

PRODUCT = "entry"
CACHE_S = 30.0


def _online(c: Optional[Controller], now: datetime) -> bool:
    return c is not None and c.state == "claimed" and c.last_seen is not None and now - c.last_seen <= OFFLINE_AFTER


def _line(doors: int, online: int, alarms: int) -> Tuple[str, str]:
    if doors == 0:
        return "unknown", "No doors yet"
    text = f"{online} of {doors} door{'s' if doors != 1 else ''} online"
    if alarms:
        text += f" · {alarms} forced or held open"
    if online == 0:
        return "down", text
    return ("attention" if online < doors or alarms else "ok"), text


def _counts(db: Session, tenant_id: uuid.UUID, now: datetime) -> Tuple[List[Site], Dict[uuid.UUID, List[int]]]:
    """The organization's active sites, and per site [doors, online, with an open alarm]."""
    sites = db.execute(select(Site).where(Site.tenant_id == tenant_id, Site.status == "active").order_by(Site.name)).scalars().all()
    controllers = {c.id: c for c in db.execute(select(Controller).where(Controller.tenant_id == tenant_id)).scalars()}
    doors = db.execute(select(Door).where(Door.tenant_id == tenant_id)).scalars().all()
    states = _door_states(db, tenant_id)
    per_site: Dict[uuid.UUID, List[int]] = {}
    for d in doors:
        alarm = states.get((d.controller_id, d.controller_door, "Door/State/DoorAlarm"), {}).get("State")
        n = per_site.setdefault(d.site_id, [0, 0, 0])
        n[0] += 1
        n[1] += _online(controllers.get(d.controller_id), now)
        n[2] += alarm in ("DoorForcedOpen", "DoorOpenTooLong")
    return sites, per_site


def _total(per_site: Dict[uuid.UUID, List[int]]) -> List[int]:
    return [sum(v[i] for v in per_site.values()) for i in range(3)]


def build(db: Session, tenant_id: uuid.UUID, now: datetime) -> Dict[str, Any]:
    """One organization: its line, and a line per site with doors."""
    sites, per_site = _counts(db, tenant_id, now)
    site_lines = []
    for s in sites:
        if s.id in per_site:
            state, text = _line(*per_site[s.id])
            site_lines.append({"site_id": str(s.id), "state": state, "summary": text})
    state, text = _line(*_total(per_site))
    return {"product": PRODUCT, "organization_id": str(tenant_id), "as_of": now.isoformat(), "state": state, "summary": text, "sites": site_lines}


def across(db: Session, tenant_ids: List[uuid.UUID], now: datetime) -> Dict[str, Any]:
    """Every organization the person reaches, in one line (the dashboard's app tile): the doors added up."""
    totals = [0, 0, 0]
    for t in tenant_ids:
        totals = [a + b for a, b in zip(totals, _total(_counts(db, t, now)[1]))]
    state, text = _line(*totals)
    return {"product": PRODUCT, "organization_id": None, "as_of": now.isoformat(), "state": state, "summary": text, "sites": []}


class Cache:
    """At most one computation per key every CACHE_S seconds, per process."""

    def __init__(self, ttl_s: float = CACHE_S, clock: Callable[[], float] = time.monotonic) -> None:
        self.ttl_s, self.clock = ttl_s, clock
        self._items: Dict[Hashable, Tuple[float, Dict[str, Any]]] = {}
        self._lock = threading.Lock()

    def get(self, key: Hashable, make: Callable[[], Dict[str, Any]]) -> Dict[str, Any]:
        now = self.clock()
        with self._lock:
            hit = self._items.get(key)
            if hit is not None and now - hit[0] < self.ttl_s:
                return hit[1]
            if len(self._items) > 10_000:
                self._items = {k: v for k, v in self._items.items() if now - v[0] < self.ttl_s}
        value = make()
        with self._lock:
            self._items[key] = (now, value)
        return value


cache = Cache()

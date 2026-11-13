"""The PhotonConsole feed (ARCHITECTURE §9.5): a read-only, per-organization document of the doors and controllers and what needs someone. CRITICAL:
it is what a customer's monitoring sees, and a token must never see another organization.

A token (`pent_...`) is made by an admin of the organization, shown once, stored as a hash, revocable, and names the PhotonConsole tenant it was
issued for (Console refuses a document that names another, as with PhotonBoard's and PhotonEdge's feeds). In the database the feed is the
`feed` mode of row-level security (migration 0002): one organization's tenant, sites, doors, controllers and events, nothing else. Alerts are
worked out here from what PhotonEntry knows, never taken from a controller's word that all is well. Values a controller never gave are null.
"""
from __future__ import annotations

import base64
import hashlib
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app import rls
from app.doorindex import DoorIndex
from app.events import normalize
from app.models import ConsoleFeedToken, Controller, Door, DoorEvent, Site, Tenant

PREFIX = "pent_"
TOKEN_RE = re.compile(r"^pent_[A-Za-z0-9_-]{43}$")
TOUCH_EVERY = timedelta(minutes=1)
OFFLINE_AFTER = timedelta(minutes=2)
QUEUE_WARNING = 1000
SEVERITY = {"none": 0, "warning": 1, "critical": 2}


@dataclass(frozen=True)
class FeedCaller:
    token_id: uuid.UUID
    tenant_id: uuid.UUID
    console_tenant_id: Optional[uuid.UUID]


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_secret() -> str:
    return PREFIX + base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()


def authenticate(system: Session, db: Session, secret: str, now: datetime) -> Optional[FeedCaller]:
    """The caller a bearer token stands for, or None (unknown, malformed, revoked, or its organization no longer served). Looked up as the
    system (no one is identified yet); then `db`, the request's own session, is put in feed mode for that one organization."""
    if not TOKEN_RE.match(secret or ""):
        return None
    row = system.execute(select(ConsoleFeedToken).where(ConsoleFeedToken.token_hash == hash_token(secret))).scalar_one_or_none()
    if row is None or row.revoked_at is not None:
        return None
    tenant = system.get(Tenant, row.tenant_id)
    if tenant is None or tenant.status == "removed":
        return None
    if row.last_used_at is None or now - row.last_used_at > TOUCH_EVERY:
        row.last_used_at = now
        system.commit()
    caller = FeedCaller(row.id, row.tenant_id, row.console_tenant_id)
    rls.as_feed(db, caller.tenant_id)
    return caller


def _worst(alerts: List[Dict[str, str]]) -> str:
    return max((a["severity"] for a in alerts), key=lambda s: SEVERITY[s], default="none")


def controller_alerts(c: Controller, now: datetime) -> List[Dict[str, str]]:
    out = []
    if c.state == "disabled":
        out.append({"code": "out_of_service", "severity": "warning", "text": "Taken out of service"})
    elif c.last_seen is None:
        out.append({"code": "never_connected", "severity": "critical", "text": "Has never connected"})
    elif now - c.last_seen > OFFLINE_AFTER:
        out.append({"code": "offline", "severity": "critical", "text": f"Offline since {c.last_seen.isoformat()}"})
    if c.apply_error:
        out.append({"code": "settings_refused", "severity": "warning", "text": f"Refused its settings: {c.apply_error[:200]}"})
    queued = (c.health or {}).get("queued_events")
    if isinstance(queued, int) and queued >= QUEUE_WARNING:
        out.append({"code": "events_backlog", "severity": "warning", "text": f"{queued} events waiting to be sent"})
    return out


def _door_states(db: Session, tenant_id: uuid.UUID) -> Dict[Tuple[uuid.UUID, str, str], Dict[str, str]]:
    """The newest door mode, door position and door alarm each controller reported for each of its doors."""
    rows = db.execute(text(
        "SELECT DISTINCT ON (controller_id, source->>'DoorToken', topic) controller_id, source->>'DoorToken' AS door, topic, data "
        "FROM door_event WHERE tenant_id = :t AND topic IN ('Door/State/DoorMode', 'Door/State/DoorPhysicalState', 'Door/State/DoorAlarm', "
        "'Door/State/DoorTamper') ORDER BY controller_id, source->>'DoorToken', topic, seq DESC"), {"t": tenant_id}).all()
    return {(r.controller_id, r.door, r.topic): r.data for r in rows}


def build(db: Session, caller: FeedCaller, now: datetime) -> Dict[str, Any]:
    """The feed document. The database is already limited to the caller's organization (feed mode); the filters are belt and braces."""
    t = caller.tenant_id
    tenant = db.get(Tenant, t)
    sites = {s.id: s.name for s in db.execute(select(Site).where(Site.tenant_id == t)).scalars()}
    controllers = db.execute(select(Controller).where(Controller.tenant_id == t, Controller.state != "pending").order_by(Controller.name, Controller.id)).scalars().all()
    doors = db.execute(select(Door).where(Door.tenant_id == t).order_by(Door.name, Door.id)).scalars().all()
    index = DoorIndex(doors, controllers)
    states = _door_states(db, t)
    counts: Dict[uuid.UUID, Dict[str, int]] = {d.id: {"granted": 0, "denied": 0, "forced": 0, "heldOpen": 0} for d in doors}
    for e in db.execute(select(DoorEvent).where(DoorEvent.tenant_id == t, DoorEvent.occurred_at >= now - timedelta(hours=24),
                                                DoorEvent.topic.in_(("AccessControl/AccessGranted/Credential", "Door/State/DoorAlarm")) |
                                                DoorEvent.topic.like("AccessControl/Denied/%"))).scalars():
        door = index.door_of(e.controller_id, e.source)
        kind = normalize(e.topic, e.data).kind
        key = {"granted": "granted", "denied": "denied", "forced": "forced", "held_open": "heldOpen"}.get(kind)
        if door is not None and key:
            counts[door.id][key] += 1
    by_id = {c.id: c for c in controllers}
    door_docs = []
    for d in doors:
        mode = states.get((d.controller_id, d.controller_door, "Door/State/DoorMode"), {}).get("State")
        position = states.get((d.controller_id, d.controller_door, "Door/State/DoorPhysicalState"), {}).get("State")
        alarm = states.get((d.controller_id, d.controller_door, "Door/State/DoorAlarm"), {}).get("State")
        tamper = states.get((d.controller_id, d.controller_door, "Door/State/DoorTamper"), {}).get("State")
        alerts = []
        if alarm == "DoorForcedOpen":
            alerts.append({"code": "forced", "severity": "critical", "text": "Forced open"})
        if alarm == "DoorOpenTooLong":
            alerts.append({"code": "held_open", "severity": "critical", "text": "Held open"})
        if tamper == "TamperDetected":
            alerts.append({"code": "tamper", "severity": "critical", "text": "Tampered with"})
        if mode == "LockedDown":
            alerts.append({"code": "locked_down", "severity": "warning", "text": "Locked down"})
        c = by_id.get(d.controller_id)
        door_docs.append({
            "id": str(d.id), "name": d.name, "siteId": str(d.site_id), "siteName": sites.get(d.site_id, ""), "controllerId": str(d.controller_id),
            "controllerName": c.name if c else "", "mode": mode, "open": None if position is None else position == "Open",
            "alarm": {"DoorForcedOpen": "forced", "DoorOpenTooLong": "held_open"}.get(alarm or ""), "lockedDown": mode == "LockedDown",
            "counts24h": counts[d.id], "alertCount": len(alerts), "alertWorst": _worst(alerts), "alerts": alerts,
        })
    controller_docs = []
    for c in controllers:
        alerts = controller_alerts(c, now)
        online = c.state == "claimed" and c.last_seen is not None and now - c.last_seen <= OFFLINE_AFTER
        controller_docs.append({
            "id": str(c.id), "name": c.name, "siteId": str(c.site_id), "siteName": sites.get(c.site_id, ""), "state": c.state, "online": online,
            "model": (c.device or {}).get("model"), "firmware": (c.device or {}).get("firmware"), "appVersion": (c.device or {}).get("app_version"),
            "lastSeenAt": c.last_seen.isoformat() if c.last_seen else None, "settingsApplied": c.applied_version, "applyError": c.apply_error or None,
            "queuedEvents": (c.health or {}).get("queued_events"), "uptimeS": (c.health or {}).get("uptime_s"),
            "alertCount": len(alerts), "alertWorst": _worst(alerts), "alerts": alerts,
        })
    return {
        "organization": {"id": str(tenant.id), "name": tenant.name, "consoleTenantId": str(caller.console_tenant_id) if caller.console_tenant_id else None},
        "doors": door_docs, "controllers": controller_docs,
        "totals": {"doors": len(door_docs), "controllers": len(controller_docs), "online": sum(1 for c in controller_docs if c["online"]),
                   "offline": sum(1 for c in controller_docs if c["state"] == "claimed" and not c["online"]),
                   "withAlerts": sum(1 for x in door_docs + controller_docs if x["alertCount"])},
    }

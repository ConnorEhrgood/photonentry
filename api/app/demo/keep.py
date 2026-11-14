"""The demo organization's events are kept 45 days (docs/DEMO.md §2): the worker trims older ones, for demo organizations only."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.demo import KEEP_EVENTS_DAYS
from app.models import DoorEvent, Tenant


def trim(db: Session, now: datetime) -> int:
    """Delete demo organizations' events older than KEEP_EVENTS_DAYS. Returns how many."""
    demos = select(Tenant.id).where(Tenant.demo.is_(True))
    n = db.execute(delete(DoorEvent).where(DoorEvent.tenant_id.in_(demos),
                                           DoorEvent.occurred_at < now - timedelta(days=KEEP_EVENTS_DAYS))).rowcount
    db.commit()
    return n

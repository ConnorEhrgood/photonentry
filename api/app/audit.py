"""The audit trail (ARCHITECTURE §7.4, decision 18): every change to cardholders, credentials, groups, schedules, doors and controllers, every
publish and every remote action, written in the same transaction as the change. Append-only: no role may change or delete a row. Details never
hold secrets (no card numbers, no PINs)."""
from __future__ import annotations

import uuid
from typing import Any, Optional

from sqlalchemy import insert
from sqlalchemy.orm import Session

from app.models import AuditLog


def record(db: Session, *, actor_id: Optional[uuid.UUID], actor_label: str, actor_source: str, action: str, tenant_id: Optional[uuid.UUID] = None,
           site_id: Optional[uuid.UUID] = None, target_type: str = "", target_id: Any = "", **detail: Any) -> None:
    # A plain INSERT (no RETURNING): the people who write the log (admins, operators) are not the people who read it (owners).
    db.execute(insert(AuditLog).values(
        tenant_id=tenant_id, site_id=site_id, actor_person_id=actor_id, actor_label=actor_label[:320], actor_source=actor_source, action=action[:60],
        target_type=target_type[:40], target_id=str(target_id)[:80],
        detail={k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in detail.items()},
    ))

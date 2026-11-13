"""What every PhotonEntry route needs: the site it names (404 unless the person reaches it), the capability check at that site, and the audit
entry in the person's name."""
from __future__ import annotations

import uuid
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app import audit
from app.deps import Ctx
from app.models import Site


def site_of(db: Session, ctx: Ctx, site_id: uuid.UUID, capability: str) -> Site:
    """The site, if it is this organization's, active, and reached by the person (404 otherwise, so site ids cannot be probed), and the person's
    role there has `capability` (403)."""
    site = db.get(Site, site_id)       # row-level security: only sites the person reaches are visible at all
    if site is None or site.tenant_id != ctx.tenant_id or site.status != "active":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    ctx.need(capability, site.id)
    return site


def not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Not found")


def problem(detail: Any, code: int = 422) -> HTTPException:
    return HTTPException(code, detail)


def log(db: Session, ctx: Ctx, action: str, *, site_id: Optional[uuid.UUID] = None, target_type: str = "", target_id: Any = "", **detail: Any) -> None:
    """An audit entry in the acting person's real name, with how they had access (direct, partner, platform). The audit page shows partner
    staff to the customer as "Partner support" (suite §5); the record itself keeps who it was."""
    audit.record(db, actor_id=ctx.who.id, actor_label=ctx.who.label, actor_source=ctx.source, action=action, tenant_id=ctx.tenant_id, site_id=site_id,
                 target_type=target_type, target_id=target_id, **detail)

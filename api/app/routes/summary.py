"""GET /v1/summary: PhotonEntry's line on the suite's home dashboard (app/summary.py). The account app calls it from the browser with its own
token (another app's client, our audience): accepted here and nowhere else (app/deps.py `current_person_any_app`). CORS for the account app's
origin is handled for this route alone in app/main.py."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import access, summary
from app.db import get_db
from app.deps import Who, current_person_any_app, load_ctx
from app.models import Access, Tenant

router = APIRouter()
PATH = "/v1/summary"
VIEW = "entry.view"


def _no_access() -> HTTPException:
    return HTTPException(status.HTTP_403_FORBIDDEN, "No access to PhotonEntry in this organization")


@router.get(PATH)
def get_summary(response: Response, organization: Optional[uuid.UUID] = None, who: Who = Depends(current_person_any_app),
                db: Session = Depends(get_db)) -> Dict[str, Any]:
    response.headers["Cache-Control"] = "private, max-age=30"
    now = datetime.now(timezone.utc)
    if organization is None:
        tenants = []
        for a, t in db.execute(select(Access, Tenant).join(Tenant, Tenant.id == Access.tenant_id).where(Access.person_id == who.id)).all():
            grant = access.Grant.from_row(a)
            if t.status != "removed" and access.allowed(grant, VIEW, now):
                tenants.append(t.id)
        return summary.cache.get(("all", who.id), lambda: summary.across(db, sorted(tenants), now))
    ctx = load_ctx(db, who, organization)
    tenant = db.get(Tenant, organization)
    if ctx is None or tenant is None or tenant.status == "removed" or not ctx.can(VIEW):
        raise _no_access()
    g = ctx.grant
    # Row-level security gives the person exactly their grant's sites, so people with the same scope share an answer.
    key = (organization, g.scope_all, g.site_ids, g.others, who.is_platform_admin)
    return summary.cache.get(key, lambda: summary.build(db, organization, now))

"""Publishing a site document to its controllers (CRITICAL): compile it for each controller with doors at the site and store a new settings
version wherever the settings changed; nothing is stored when any controller's settings cannot be compiled (a site is published whole or not at
all). Used by an admin's publish (app/routes/config.py) and by visitors' passes (app/passes.py)."""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.compiler.axis import CompileError, compile_controller
from app.document import SiteDocument
from app.link.pgstore import notify
from app.link.protocol import Inventory
from app.models import Controller, SettingsVersion, Site


class PublishError(Exception):
    def __init__(self, problems: List[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def store(db: Session, site: Site, doc: SiteDocument, created_by: Optional[uuid.UUID]) -> List[Dict[str, Any]]:
    """Each controller's {controller_id, version, changed}. Raises PublishError (nothing stored) when a controller's settings cannot be compiled."""
    controllers = db.execute(select(Controller).where(Controller.site_id == site.id, Controller.state != "pending")
                             .order_by(Controller.name)).scalars().all()
    compiled, problems = [], []
    for c in controllers:
        if not any(d.controller_id == str(c.id) for d in doc.doors):
            continue                                 # a controller with no doors mapped yet gets nothing
        try:
            inv = Inventory.model_validate(c.inventory) if c.inventory is not None else None
            compiled.append((c, compile_controller(doc, str(c.id), inv)))
        except CompileError as e:
            problems += e.problems
    if problems:
        raise PublishError(sorted(set(problems)))
    out = []
    for c, settings in compiled:
        latest = db.execute(select(SettingsVersion).where(SettingsVersion.controller_id == c.id)
                            .order_by(SettingsVersion.version.desc()).limit(1)).scalar_one_or_none()
        if latest is not None and latest.document == settings:
            out.append({"controller_id": str(c.id), "version": latest.version, "changed": False})
            continue
        version = (latest.version if latest else 0) + 1
        db.add(SettingsVersion(controller_id=c.id, version=version, tenant_id=site.tenant_id, site_id=site.id, document=settings,
                               created_by=created_by))
        notify(db, c.id)
        out.append({"controller_id": str(c.id), "version": version, "changed": True})
    return out

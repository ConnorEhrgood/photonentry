"""Which door an event belongs to. A controller names a door by its own token (door events) or names the access point (reader side) the credential
was presented at (access events); the controller's inventory says which door each access point opens."""
from __future__ import annotations

import uuid
from typing import Dict, Iterable, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Controller, Door


class DoorIndex:
    def __init__(self, doors: Iterable[Door], controllers: Iterable[Controller]) -> None:
        self.by_token: Dict[Tuple[uuid.UUID, str], Door] = {(d.controller_id, d.controller_door): d for d in doors}
        self.by_point: Dict[Tuple[uuid.UUID, str], Door] = {}
        for c in controllers:
            for inv in (c.inventory or {}).get("doors", []):
                door = self.by_token.get((c.id, inv.get("token", "")))
                if door is not None:
                    for ap in inv.get("access_points", []):
                        self.by_point[(c.id, ap)] = door

    def door_of(self, controller_id: uuid.UUID, source: Dict[str, str]) -> Optional[Door]:
        return self.by_token.get((controller_id, source.get("DoorToken", ""))) or self.by_point.get((controller_id, source.get("AccessPointToken", "")))


def for_controllers(db: Session, controllers: Iterable[Controller]) -> DoorIndex:
    cs = list(controllers)
    ids = [c.id for c in cs]
    doors = db.execute(select(Door).where(Door.controller_id.in_(ids))).scalars().all() if ids else []
    return DoorIndex(doors, cs)


def cardholder_id(data: Dict[str, str]) -> Optional[uuid.UUID]:
    """The cardholder an access event names: the controller reports the credential's user token, `pe-u-<cardholder id>` (app/compiler/axis.py)."""
    name = data.get("CredentialHolderName", "")
    if not name.startswith("pe-u-"):
        return None
    try:
        return uuid.UUID(name[5:])
    except ValueError:
        return None

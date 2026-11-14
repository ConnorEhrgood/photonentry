"""PhotonEntry's roles and capabilities: the catalog published to the PhotonID directory (suite ARCHITECTURE §5) and the one place that says what
each role can do (ARCHITECTURE decision 11, §8). app/access.py applies it. A capability marked sensitive is one a customer will later be able to
hold back from partner staff (the privacy-controls pass, ARCHITECTURE §7.3)."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, FrozenSet

# key -> sensitive
CAPABILITIES: Dict[str, bool] = {
    "entry.view": False,                # doors, their state, controllers, schedules, groups, holidays
    "entry.events.view": False,         # door events (who opened what, when)
    "entry.cardholders.view": False,    # cardholders' names and groups (not their credentials)
    "entry.door.unlock": True,          # open a door remotely, or lock or unlock it
    "entry.lockdown": True,             # start and end a lockdown
    "entry.visitors.manage": True,      # issue and revoke visitors' passes (only for access groups an admin opened to visitors)
    "entry.cardholders.manage": False,  # add, change and remove cardholders and their groups
    "entry.credential.issue": True,     # issue, change and revoke cards and PINs
    "entry.config.manage": False,       # doors, schedules, holidays, access groups; publish to controllers
    "entry.controller.manage": False,   # claim, rename, disable controllers
    "entry.members.view": False,
    "entry.emergency.open": True,       # unlock every door at once (ARCHITECTURE §7.1)
    "entry.audit.view": False,
    "entry.unlock.own": False,          # open, from the app, the doors one's own cardholder record allows now (decision 25)
}

_DOOR_USER = ["entry.unlock.own"]          # every role has it: promoting a door user never takes the app's unlock away (one role per person)
_VIEWER = _DOOR_USER + ["entry.view", "entry.events.view"]
_OPERATOR = _VIEWER + ["entry.cardholders.view", "entry.door.unlock", "entry.lockdown", "entry.visitors.manage"]
_ADMIN = _OPERATOR + ["entry.cardholders.manage", "entry.credential.issue", "entry.config.manage", "entry.controller.manage", "entry.members.view"]
_OWNER = _ADMIN + ["entry.emergency.open", "entry.audit.view"]


@dataclass(frozen=True)
class RoleDef:
    key: str
    label: str
    rank: int
    site_limitable: bool
    capabilities: FrozenSet[str]
    description: str = ""          # shown under the role in the account app's picker (the directory stores it once deployed; ignored before)


ROLES: Dict[str, RoleDef] = {r.key: r for r in (
    # Ranks start at 1 (the directory refuses 0); they are only relative, and grants hold keys, not ranks.
    RoleDef("door_user", "Door user (opens doors with the app)", 1, True, frozenset(_DOOR_USER),
            "Opens, from the PhotonEntry app, the doors their own cardholder record allows. Sees nothing else in PhotonEntry."),
    RoleDef("viewer", "Viewer", 2, True, frozenset(_VIEWER)),
    RoleDef("operator", "Operator", 3, True, frozenset(_OPERATOR)),
    RoleDef("admin", "Admin", 4, True, frozenset(_ADMIN)),
    RoleDef("owner", "Owner", 5, False, frozenset(_OWNER)),
)}
assert all(c in CAPABILITIES for r in ROLES.values() for c in r.capabilities), "a role names a capability that does not exist"


def catalog() -> Dict[str, Any]:
    """What PUT /v1/products/entry/roles carries (photonid's contract/roles.schema.json)."""
    return {"roles": [
        {"key": r.key, "label": r.label, "rank": r.rank, "site_limitable": r.site_limitable, "capabilities": sorted(r.capabilities),
         "sensitive_capabilities": sorted(c for c in r.capabilities if CAPABILITIES[c]), **({"description": r.description} if r.description else {})}
        for r in sorted(ROLES.values(), key=lambda r: r.rank)
    ]}


def catalog_hash() -> str:
    return hashlib.sha256(json.dumps(catalog(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()

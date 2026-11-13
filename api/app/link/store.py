"""Where the link service keeps controllers, their settings versions, their events and the commands waiting for them.

`Store` is the interface; `MemoryStore` the Step 1 implementation (tests and the simulator runs). Step 2 adds the Postgres store, which must
pass the same tests (api/tests/unit/test_store.py is written against the interface).

The rules that matter, whatever the storage:
- **Events are stored exactly once, in order.** A batch is taken from `ack_seq + 1` onwards while the sequence is unbroken; anything at or below
  `ack_seq` is a resend and is skipped; a gap stops the batch (the controller resends from `ack_seq + 1`). Nothing is lost when a reply is.
- **Commands expire.** One past its `expires_at` is never handed out again; a command handed out but not answered is handed out again after
  `REDELIVER_S` (the controller ignores an id it has already carried out).
- **Claim codes are single-use and short-lived**: a pending controller can be claimed for `CLAIM_TTL_S` after its last hello.
"""
from __future__ import annotations

import copy
import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Protocol, Tuple

from app.link.protocol import Command, Event, Inventory

CLAIM_TTL_S = 24 * 3600
REDELIVER_S = 10
COMMAND_TTL_S = {"access": 15, "lock": 60, "unlock": 60, "lockdown": 300, "lockdown_release": 300}


class NotFound(Exception):
    pass


@dataclass
class Controller:
    id: str
    key_id: str
    public_key: bytes
    claim_code: str
    device: Dict[str, str]
    state: str = "pending"                 # pending | claimed | disabled
    tenant_id: Optional[str] = None
    site_id: Optional[str] = None
    inventory: Optional[Inventory] = None
    applied_version: int = 0
    apply_error: str = ""
    ack_seq: int = 0
    last_seen: Optional[datetime] = None
    health: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StoredCommand:
    command: Command
    controller_id: str
    delivered_at: Optional[datetime] = None
    done: bool = False
    ok: Optional[bool] = None
    error: str = ""


class Store(Protocol):
    def hello(self, key_id: str, public_key: bytes, claim_code: str, device: Dict[str, str], now: datetime) -> Controller: ...
    def claim(self, claim_code: str, tenant_id: str, site_id: str, now: datetime) -> Controller: ...
    def disable(self, controller_id: str) -> None: ...
    def by_key(self, key_id: str) -> Optional[Controller]: ...
    def get(self, controller_id: str) -> Controller: ...
    def seen(self, controller_id: str, now: datetime, health: Dict[str, Any]) -> None: ...
    def set_inventory(self, controller_id: str, inventory: Inventory) -> None: ...
    def set_applied(self, controller_id: str, version: int, error: str) -> None: ...
    def publish(self, controller_id: str, document: Dict[str, Any]) -> int: ...
    def latest(self, controller_id: str) -> Optional[Tuple[int, Dict[str, Any]]]: ...
    def add_events(self, controller_id: str, events: List[Event], now: datetime) -> int: ...
    def events(self, controller_id: str) -> List[Event]: ...
    def command(self, controller_id: str, kind: str, door: str, actor: str, now: datetime) -> Command: ...
    def due_commands(self, controller_id: str, now: datetime) -> List[Command]: ...
    def finish_command(self, controller_id: str, command_id: str, ok: bool, error: str) -> None: ...
    def command_state(self, command_id: str) -> StoredCommand: ...
    def mark(self, controller_id: str) -> int: ...


class MemoryStore:
    """Everything in dictionaries, behind one lock (the API serves controllers from worker threads and tests call it from their own)."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._controllers: Dict[str, Controller] = {}
        self._settings: Dict[str, List[Dict[str, Any]]] = {}
        self._events: Dict[str, List[Event]] = {}
        self._commands: Dict[str, StoredCommand] = {}
        self._marks: Dict[str, int] = {}

    # -- controllers -------------------------------------------------------------------------------------------------------------------------------

    def hello(self, key_id: str, public_key: bytes, claim_code: str, device: Dict[str, str], now: datetime) -> Controller:
        with self._lock:
            c = self.by_key(key_id)
            if c is None:
                c = Controller(id=f"ctl_{secrets.token_hex(8)}", key_id=key_id, public_key=public_key, claim_code=claim_code, device=device)
                self._controllers[c.id] = c
            if c.state == "pending":
                c.claim_code = claim_code     # the controller may have made a new code after a restart
            c.device = dict(device)
            c.last_seen = now
            return copy.deepcopy(c)

    def claim(self, claim_code: str, tenant_id: str, site_id: str, now: datetime) -> Controller:
        with self._lock:
            for c in self._controllers.values():
                if (c.state == "pending" and c.claim_code == claim_code.upper() and c.last_seen is not None
                        and c.last_seen >= now - timedelta(seconds=CLAIM_TTL_S)):
                    c.state, c.tenant_id, c.site_id, c.claim_code = "claimed", tenant_id, site_id, ""
                    self._bump(c.id)
                    return copy.deepcopy(c)
            raise NotFound("no controller is waiting with that code")

    def disable(self, controller_id: str) -> None:
        with self._lock:
            self._get(controller_id).state = "disabled"
            self._bump(controller_id)

    def by_key(self, key_id: str) -> Optional[Controller]:
        with self._lock:
            for c in self._controllers.values():
                if c.key_id == key_id:
                    return copy.deepcopy(c)
            return None

    def get(self, controller_id: str) -> Controller:
        with self._lock:
            return copy.deepcopy(self._get(controller_id))

    def _get(self, controller_id: str) -> Controller:
        c = self._controllers.get(controller_id)
        if c is None:
            raise NotFound(controller_id)
        return c

    def seen(self, controller_id: str, now: datetime, health: Dict[str, Any]) -> None:
        with self._lock:
            c = self._get(controller_id)
            c.last_seen, c.health = now, dict(health)

    def set_inventory(self, controller_id: str, inventory: Inventory) -> None:
        with self._lock:
            self._get(controller_id).inventory = inventory.model_copy(deep=True)

    def set_applied(self, controller_id: str, version: int, error: str) -> None:
        with self._lock:
            c = self._get(controller_id)
            c.applied_version, c.apply_error = version, error

    # -- settings ----------------------------------------------------------------------------------------------------------------------------------

    def publish(self, controller_id: str, document: Dict[str, Any]) -> int:
        with self._lock:
            self._get(controller_id)
            versions = self._settings.setdefault(controller_id, [])
            versions.append(copy.deepcopy(document))
            self._bump(controller_id)
            return len(versions)

    def latest(self, controller_id: str) -> Optional[Tuple[int, Dict[str, Any]]]:
        with self._lock:
            versions = self._settings.get(controller_id) or []
            return (len(versions), copy.deepcopy(versions[-1])) if versions else None

    # -- events ------------------------------------------------------------------------------------------------------------------------------------

    def add_events(self, controller_id: str, events: List[Event], now: datetime) -> int:
        with self._lock:
            c = self._get(controller_id)
            stored = self._events.setdefault(controller_id, [])
            for e in sorted(events, key=lambda e: e.seq):
                if e.seq <= c.ack_seq:
                    continue                  # a resend of something we have
                if e.seq != c.ack_seq + 1:
                    break                     # a gap: the controller resends from ack_seq + 1
                stored.append(e.model_copy(deep=True))
                c.ack_seq = e.seq
            return c.ack_seq

    def events(self, controller_id: str) -> List[Event]:
        with self._lock:
            return [e.model_copy(deep=True) for e in self._events.get(controller_id, [])]

    # -- commands ----------------------------------------------------------------------------------------------------------------------------------

    def command(self, controller_id: str, kind: str, door: str, actor: str, now: datetime) -> Command:
        with self._lock:
            c = self._get(controller_id)
            if c.state != "claimed":
                raise NotFound("the controller is not in service")
            cmd = Command(id=f"cmd_{secrets.token_hex(8)}", kind=kind, door=door, actor=actor,
                          expires_at=now + timedelta(seconds=COMMAND_TTL_S[kind]))
            self._commands[cmd.id] = StoredCommand(command=cmd, controller_id=controller_id)
            self._bump(controller_id)
            return cmd

    def due_commands(self, controller_id: str, now: datetime) -> List[Command]:
        """Commands to hand out now: not done, not expired, not handed out in the last REDELIVER_S. Marks them handed out."""
        with self._lock:
            out = []
            for sc in self._commands.values():
                if sc.controller_id != controller_id or sc.done or sc.command.expires_at <= now:
                    continue
                if sc.delivered_at is not None and sc.delivered_at > now - timedelta(seconds=REDELIVER_S):
                    continue
                sc.delivered_at = now
                out.append(sc.command.model_copy())
            return out

    def finish_command(self, controller_id: str, command_id: str, ok: bool, error: str) -> None:
        with self._lock:
            sc = self._commands.get(command_id)
            if sc is None or sc.controller_id != controller_id or sc.done:
                return                        # unknown, another controller's, or already answered: nothing to record
            sc.done, sc.ok, sc.error = True, ok, error

    def command_state(self, command_id: str) -> StoredCommand:
        with self._lock:
            sc = self._commands.get(command_id)
            if sc is None:
                raise NotFound(command_id)
            return copy.deepcopy(sc)

    # -- waking a held sync ------------------------------------------------------------------------------------------------------------------------

    def mark(self, controller_id: str) -> int:
        """A counter that changes whenever there is something new for the controller (settings, a command, a state change)."""
        with self._lock:
            return self._marks.get(controller_id, 0)

    def _bump(self, controller_id: str) -> None:
        self._marks[controller_id] = self._marks.get(controller_id, 0) + 1

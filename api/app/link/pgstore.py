"""The link's store on Postgres (CRITICAL). Same interface and the same rules as MemoryStore (app/link/store.py), and the same tests
(tests/unit/test_store.py runs against both).

It works as the system role: the link finds controllers by their key, not by a person, so there is no person for row-level security to
apply to. Everything it writes is scoped by the controller row it found.

Concurrency: a controller syncs from two threads (control and events), so every change to a controller's bookkeeping takes its row lock first
(SELECT ... FOR UPDATE); commands are handed out with SKIP LOCKED so two syncs never get the same one at the same moment.

Waking a held sync: anything new for a controller (settings, a command, a change of state) sends `NOTIFY entry_link, '<controller id>'` in the
same transaction. One listener thread per process turns notices into in-memory counters (`mark`), which the long-poll watches. If the listener
loses its connection it wakes everyone when it is back (a missed notice must not leave a sync asleep for its whole wait).
"""
from __future__ import annotations

import logging
import secrets
import threading
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

import psycopg
from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.link.protocol import Command, Event, Inventory
from app.link.store import CLAIM_TTL_S, COMMAND_TTL_S, REDELIVER_S, Controller, NotFound, StoredCommand
from app.models import Controller as ControllerRow
from app.models import DoorEvent, LinkCommand, SettingsVersion

log = logging.getLogger("photonentry.link")
CHANNEL = "entry_link"


def notify(db: Session, controller_id: Any) -> None:
    """Wake any sync held for this controller, when the current transaction commits."""
    db.execute(text("SELECT pg_notify(:c, :p)"), {"c": CHANNEL, "p": str(controller_id)})


class Listener:
    """LISTEN entry_link on its own connection, in a thread; counts notices per controller."""

    def __init__(self, conninfo: str) -> None:
        self.conninfo = conninfo
        self.marks: Dict[str, int] = {}
        self.epoch = 0
        self.lock = threading.Lock()
        self.stopping = threading.Event()
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._run, name="entry-link-listener", daemon=True)

    def start(self) -> "Listener":
        self.thread.start()
        self.ready.wait(10)
        return self

    def stop(self) -> None:
        self.stopping.set()
        self.thread.join(5)

    def mark(self, controller_id: str) -> int:
        with self.lock:
            return self.marks.get(controller_id, 0) + self.epoch

    def _run(self) -> None:
        while not self.stopping.is_set():
            try:
                with psycopg.connect(self.conninfo, autocommit=True) as conn:
                    conn.execute(f"LISTEN {CHANNEL}")
                    with self.lock:
                        self.epoch += 1          # (re)connected: anything may have been missed, so every held sync looks again
                    self.ready.set()
                    while not self.stopping.is_set():
                        for n in conn.notifies(timeout=1.0, stop_after=100):
                            with self.lock:
                                self.marks[n.payload] = self.marks.get(n.payload, 0) + 1
            except psycopg.Error as e:
                log.warning("link listener lost its connection: %s", e)
                self.ready.set()
                time.sleep(1)


def _controller(row: ControllerRow) -> Controller:
    return Controller(id=str(row.id), key_id=row.key_id, public_key=bytes(row.public_key), claim_code=row.claim_code, device=dict(row.device or {}),
                      state=row.state, tenant_id=str(row.tenant_id) if row.tenant_id else None, site_id=str(row.site_id) if row.site_id else None,
                      inventory=Inventory.model_validate(row.inventory) if row.inventory is not None else None,
                      applied_version=row.applied_version, failed_version=row.failed_version, apply_error=row.apply_error, ack_seq=row.ack_seq, last_seen=row.last_seen,
                      health=dict(row.health or {}))


class PgStore:
    def __init__(self, sessions: Callable[[], Session], listener: Optional[Listener] = None) -> None:
        self.sessions = sessions
        self.listener = listener

    # -- controllers ---------------------------------------------------------------------------------------------------------------------------

    def _row(self, db: Session, controller_id: str, lock: bool = False) -> ControllerRow:
        try:
            cid = uuid.UUID(str(controller_id))
        except ValueError as e:                      # a malformed id is simply not found
            raise NotFound(controller_id) from e
        q = select(ControllerRow).where(ControllerRow.id == cid)
        row = db.execute(q.with_for_update() if lock else q).scalar_one_or_none()
        if row is None:
            raise NotFound(controller_id)
        return row

    def hello(self, key_id: str, public_key: bytes, claim_code: str, device: Dict[str, str], now: datetime) -> Controller:
        with self.sessions() as db:
            db.execute(insert(ControllerRow).values(id=uuid.uuid4(), key_id=key_id, public_key=public_key, claim_code=claim_code, device=device,
                                                    last_seen=now).on_conflict_do_nothing(index_elements=["key_id"]))
            row = db.execute(select(ControllerRow).where(ControllerRow.key_id == key_id).with_for_update()).scalar_one()
            if row.state == "pending":
                row.claim_code = claim_code
            row.device, row.last_seen = dict(device), now
            db.commit()
            return _controller(row)

    def claim(self, claim_code: str, tenant_id: str, site_id: str, now: datetime) -> Controller:
        with self.sessions() as db:
            row = db.execute(select(ControllerRow).where(
                ControllerRow.state == "pending", ControllerRow.claim_code == claim_code.upper(),
                ControllerRow.last_seen >= now - timedelta(seconds=CLAIM_TTL_S)).with_for_update()).scalars().first()
            if row is None:
                raise NotFound("no controller is waiting with that code")
            row.state, row.tenant_id, row.site_id, row.claim_code, row.claimed_at = "claimed", tenant_id, site_id, "", now
            notify(db, row.id)
            db.commit()
            return _controller(row)

    def disable(self, controller_id: str) -> None:
        with self.sessions() as db:
            self._row(db, controller_id, lock=True).state = "disabled"
            notify(db, controller_id)
            db.commit()

    def by_key(self, key_id: str) -> Optional[Controller]:
        with self.sessions() as db:
            row = db.execute(select(ControllerRow).where(ControllerRow.key_id == key_id)).scalar_one_or_none()
            return _controller(row) if row else None

    def get(self, controller_id: str) -> Controller:
        with self.sessions() as db:
            return _controller(self._row(db, controller_id))

    def seen(self, controller_id: str, now: datetime, health: Dict[str, Any]) -> None:
        with self.sessions() as db:
            db.execute(update(ControllerRow).where(ControllerRow.id == controller_id).values(last_seen=now, health=health))
            db.commit()

    def set_inventory(self, controller_id: str, inventory: Inventory) -> None:
        with self.sessions() as db:
            db.execute(update(ControllerRow).where(ControllerRow.id == controller_id).values(inventory=inventory.model_dump(mode="json")))
            db.commit()

    def set_applied(self, controller_id: str, version: int, error: str, failed_version: int = 0) -> None:
        with self.sessions() as db:
            db.execute(update(ControllerRow).where(ControllerRow.id == controller_id).values(applied_version=version, apply_error=error,
                                                                                              failed_version=failed_version))
            db.commit()

    # -- settings ----------------------------------------------------------------------------------------------------------------------------

    def publish(self, controller_id: str, document: Dict[str, Any], created_by: Optional[Any] = None) -> int:
        with self.sessions() as db:
            row = self._row(db, controller_id, lock=True)
            version = (db.execute(select(func.max(SettingsVersion.version)).where(SettingsVersion.controller_id == row.id)).scalar() or 0) + 1
            db.add(SettingsVersion(controller_id=row.id, version=version, tenant_id=row.tenant_id, site_id=row.site_id, document=document,
                                   created_by=created_by))
            notify(db, controller_id)
            db.commit()
            return version

    def latest(self, controller_id: str) -> Optional[Tuple[int, Dict[str, Any]]]:
        with self.sessions() as db:
            row = db.execute(select(SettingsVersion).where(SettingsVersion.controller_id == controller_id)
                             .order_by(SettingsVersion.version.desc()).limit(1)).scalar_one_or_none()
            return (row.version, row.document) if row else None

    # -- events ------------------------------------------------------------------------------------------------------------------------------

    def add_events(self, controller_id: str, events: List[Event], now: datetime) -> int:
        with self.sessions() as db:
            row = self._row(db, controller_id, lock=True)
            ack = row.ack_seq
            for e in sorted(events, key=lambda e: e.seq):
                if e.seq <= ack:
                    continue
                if e.seq != ack + 1:
                    break
                db.add(DoorEvent(controller_id=row.id, seq=e.seq, tenant_id=row.tenant_id, site_id=row.site_id, occurred_at=e.occurred_at,
                                 received_at=now, topic=e.topic, source=e.source, data=e.data, ref=e.ref))
                ack = e.seq
            row.ack_seq = ack
            db.commit()
            return ack

    def events(self, controller_id: str) -> List[Event]:
        with self.sessions() as db:
            rows = db.execute(select(DoorEvent).where(DoorEvent.controller_id == controller_id).order_by(DoorEvent.seq)).scalars()
            return [Event(seq=r.seq, occurred_at=r.occurred_at, topic=r.topic, source=r.source, data=r.data, ref=r.ref) for r in rows]

    # -- commands ----------------------------------------------------------------------------------------------------------------------------

    def command(self, controller_id: str, kind: str, door: str, actor: str, now: datetime) -> Command:
        with self.sessions() as db:
            row = self._row(db, controller_id)
            if row.state != "claimed":
                raise NotFound("the controller is not in service")
            cmd = new_command(kind, door, actor, now)
            db.add(LinkCommand(id=cmd.id, tenant_id=row.tenant_id, site_id=row.site_id, controller_id=row.id, kind=kind, door=door, actor=actor,
                               expires_at=cmd.expires_at, created_at=now))
            notify(db, controller_id)
            db.commit()
            return cmd

    def due_commands(self, controller_id: str, now: datetime) -> List[Command]:
        with self.sessions() as db:
            rows = db.execute(select(LinkCommand).where(
                LinkCommand.controller_id == controller_id, LinkCommand.done.is_(False), LinkCommand.expires_at > now,
                (LinkCommand.delivered_at.is_(None)) | (LinkCommand.delivered_at <= now - timedelta(seconds=REDELIVER_S)),
            ).order_by(LinkCommand.created_at).with_for_update(skip_locked=True)).scalars().all()
            out = []
            for r in rows:
                r.delivered_at = now
                out.append(Command(id=r.id, kind=r.kind, door=r.door, expires_at=r.expires_at, actor=r.actor))
            db.commit()
            return out

    def finish_command(self, controller_id: str, command_id: str, ok: bool, error: str) -> None:
        with self.sessions() as db:
            db.execute(update(LinkCommand).where(LinkCommand.id == command_id, LinkCommand.controller_id == controller_id,
                                                 LinkCommand.done.is_(False)).values(done=True, ok=ok, error=error[:2000]))
            db.commit()

    def command_state(self, command_id: str) -> StoredCommand:
        with self.sessions() as db:
            r = db.get(LinkCommand, command_id[:40])
            if r is None:
                raise NotFound(command_id)
            return StoredCommand(command=Command(id=r.id, kind=r.kind, door=r.door, expires_at=r.expires_at, actor=r.actor),
                                 controller_id=str(r.controller_id), delivered_at=r.delivered_at, done=r.done, ok=r.ok, error=r.error)

    def mark(self, controller_id: str) -> int:
        if self.listener is None:
            return 0                     # no listener: a held sync simply runs to its end (development without LISTEN)
        return self.listener.mark(str(controller_id))


def new_command(kind: str, door: str, actor: str, now: datetime) -> Command:
    return Command(id=f"cmd_{secrets.token_hex(8)}", kind=kind, door=door, actor=actor, expires_at=now + timedelta(seconds=COMMAND_TTL_S[kind]))


def conninfo(sqlalchemy_url: str) -> str:
    """A psycopg connection string from a SQLAlchemy URL (postgresql+psycopg://... -> postgresql://...)."""
    from sqlalchemy.engine import make_url
    url = make_url(sqlalchemy_url).set(drivername="postgresql")
    return url.render_as_string(hide_password=False)

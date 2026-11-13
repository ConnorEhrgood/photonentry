"""The link service: what controllers talk to (CRITICAL: 100% branch coverage). Served on `link.entry.photonind.com`.

It never decides who may open a door. It hands each claimed controller its newest settings and its commands, and stores its events. A
controller that is pending (not yet claimed) learns only that; a disabled one learns only that; an unknown or badly signed request gets 401
with no detail (the reason goes to our log).

Long-poll: a sync with `wait: true` and nothing to answer is held until there is something (new settings, a command, a state change) or
`wait_s` passes. The store's change counter (`mark`) is checked every `poll_s`: in memory for both stores (the Postgres store's is fed by
LISTEN/NOTIFY), so a held sync costs no database queries. Store calls run in the thread pool: they block (Postgres), the event loop must not.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.link import signing
from app.link.protocol import HelloRequest, HelloResponse, Settings, SyncRequest, SyncResponse
from app.link.store import Store

log = logging.getLogger("photonentry.link")
MAX_BODY = 4 * 1024 * 1024


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Link:
    store: Store
    nonces: signing.NonceCache = field(default_factory=signing.NonceCache)
    clock: Callable[[], datetime] = _utcnow
    wait_s: float = 25.0
    poll_s: float = 0.2
    idle_poll_ms: int = 0        # the pause a controller takes between syncs when it is idle (it waits with `wait` instead)


def _refuse(status: int, reason: str, state: Optional[str] = None) -> JSONResponse:
    log.info("link request refused: %s", reason)
    return JSONResponse({"state": state} if state else {"detail": "refused"}, status_code=status)


async def _body(request: Request) -> Optional[bytes]:
    if int(request.headers.get("content-length") or 0) > MAX_BODY:
        return None
    body = await request.body()
    return body if len(body) <= MAX_BODY else None


def router(link: Link) -> APIRouter:
    r = APIRouter(prefix="/link/v1")

    @r.post("/hello")
    async def hello(request: Request):
        body = await _body(request)
        if body is None:
            return _refuse(413, "body too large")
        try:
            msg = HelloRequest.model_validate_json(body)
            public = signing.unb64u(msg.public_key)
        except (ValidationError, ValueError):
            return _refuse(400, "malformed hello")
        if len(public) != 32:
            return _refuse(400, "public key is not 32 bytes")
        now = link.clock()
        try:
            # The key in the body must be the key that signed: a hello proves possession of the private key it names.
            kid = signing.verify(request.headers.get(signing.HEADER), "POST", request.url.path, body, lambda _k: public, link.nonces,
                                 int(now.timestamp()))
        except signing.LinkAuthError as e:
            return _refuse(401, str(e))
        c = await run_in_threadpool(link.store.hello, kid, public, msg.claim_code, msg.device.model_dump(), now)
        return HelloResponse(state=c.state, controller_id=c.id if c.state == "claimed" else None).model_dump(mode="json")

    @r.post("/sync")
    async def sync(request: Request):
        body = await _body(request)
        if body is None:
            return _refuse(413, "body too large")
        now = link.clock()

        def public_key_for(kid: str) -> Optional[bytes]:
            c = link.store.by_key(kid)
            return c.public_key if c else None

        try:
            kid = await run_in_threadpool(signing.verify, request.headers.get(signing.HEADER), "POST", request.url.path, body, public_key_for,
                                          link.nonces, int(now.timestamp()))
        except signing.LinkAuthError as e:
            return _refuse(401, str(e))
        c = await run_in_threadpool(link.store.by_key, kid)
        assert c is not None   # verify() found it a moment ago and controllers are never deleted
        if c.state != "claimed":
            return _refuse(403, f"controller {c.id} is {c.state}", state=c.state)
        try:
            msg = SyncRequest.model_validate(json.loads(body))
        except (ValidationError, ValueError):
            return _refuse(400, "malformed sync")

        ack = await run_in_threadpool(_record, link, c.id, msg, now)

        deadline = time.monotonic() + (link.wait_s if msg.wait and not msg.events else 0)
        while True:
            mark = link.store.mark(c.id)
            answer = await run_in_threadpool(_answer, link, c.id, msg.applied_version, msg.failed_version, ack)
            if answer.settings or answer.commands or time.monotonic() >= deadline:
                return answer.model_dump(mode="json")
            while link.store.mark(c.id) == mark and time.monotonic() < deadline:
                await asyncio.sleep(link.poll_s)
            state = (await run_in_threadpool(link.store.get, c.id)).state
            if state != "claimed":
                return _refuse(403, f"controller {c.id} left service while waiting", state=state)

    return r


def _record(link: Link, controller_id: str, msg: SyncRequest, now: datetime) -> int:
    """What the controller told us: its health, inventory, applied version, command results and events. Returns the new ack."""
    link.store.seen(controller_id, now, msg.health.model_dump(mode="json"))
    if msg.inventory is not None:
        link.store.set_inventory(controller_id, msg.inventory)
    link.store.set_applied(controller_id, msg.applied_version, msg.apply_error, msg.failed_version)
    for res in msg.results:
        link.store.finish_command(controller_id, res.id, res.ok, res.error)
    return link.store.add_events(controller_id, msg.events, now)


def _answer(link: Link, controller_id: str, applied_version: int, failed_version: int, ack: int) -> SyncResponse:
    latest = link.store.latest(controller_id)
    settings = None
    if latest and latest[0] not in (applied_version, failed_version):
        settings = Settings(version=latest[0], document=latest[1])
    commands = link.store.due_commands(controller_id, link.clock())
    return SyncResponse(ack_seq=ack, settings=settings, commands=commands, poll_after_ms=link.idle_poll_ms)

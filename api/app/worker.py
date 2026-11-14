"""Background jobs. `python -m app.worker` runs them; keep it a single process.

Now: keep the directory copy current (a periodic pull, so a lost notice delays a change and never loses it) and publish our role catalog to the
directory; send the doors' events to PhotonGuard (app/guard.py); name who answered a door's call and keep the intercoms' SIP accounts as
PhotonVox has them (app/vox.py, hourly). Later steps add visitor-pass mail and retention.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import text

from app import guard, mail, notify, obs, sync, vox
from app.config import settings
from app.db import SystemSession
from app.deps import get_directory
from app.models import utcnow

log = logging.getLogger("photonentry.worker")

TICK_S = 15
PUBLISH_RETRY_S = 600
VOX_SYNC_S = 3600
HEARTBEAT_FILE = os.environ.get("WORKER_HEARTBEAT_FILE", "/tmp/worker.ok")   # the container healthcheck reads its age


def run_job(what: str, job: Callable[[Any], Any]) -> Any:
    """Run one job in a session of its own. A job that fails, or leaves its transaction broken, cannot take the next job down with it."""
    with SystemSession() as db:
        try:
            return job(db)
        except Exception:  # noqa: BLE001 - housekeeping must never take the worker down
            log.exception("%s failed", what)
            db.rollback()
            return None


def tick(state: dict, clock: Callable[[], float] = time.monotonic) -> None:
    """One pass: whatever is due. `state` remembers when each job last ran."""
    now = clock()
    sent = run_job("guard", lambda db: sum(r.sent for r in guard.forward_all(db, guard.http_post, utcnow())))
    if sent:
        log.info("guard: sent %d event(s)", sent)
    notified = run_job("lockdown mail", lambda db: notify.notify_lockdowns(db, mail.send, utcnow()))
    if notified:
        log.info("lockdown mail: %d notice(s)", notified)
    sync_sip = now - state.get("vox_sync", float("-inf")) >= VOX_SYNC_S
    if sync_sip:
        state["vox_sync"] = now
    done = run_job("vox", lambda db: vox.run_all(db, vox.http_get, utcnow(), sync_sip))
    if done and any(done):
        log.info("vox: %d intercom(s) given a new SIP account, %d call(s) matched", *done)
    directory = get_directory()
    if directory is None:
        return
    if now - state.get("pull", float("-inf")) >= settings.directory_pull_every_s:
        state["pull"] = now
        result = run_job("directory pull", lambda db: sync.pull(db, directory, utcnow()))
        if result is not None and result.applied:
            log.info("directory: applied %d change(s)", result.applied)
    if now >= state.get("publish", float("-inf")):
        sent = run_job("role catalog", lambda db: sync.publish_roles(db, directory))
        # Until the directory has accepted the catalog, try again in ten minutes; after that the hash makes an hourly check free.
        state["publish"] = now + (PUBLISH_RETRY_S if sent is None else 3600)
        if sent:
            log.info("directory: published the role catalog")


def check_config() -> None:
    """The worker refuses to start on an unsafe production configuration, as the API does."""
    problem = settings.production_safe()
    if problem:
        raise RuntimeError(f"Unsafe production configuration: {problem}")


def heartbeat() -> None:
    """The row /readyz reads (the API cannot see this container's file)."""
    with SystemSession() as db:
        db.execute(text("INSERT INTO worker_heartbeat (id, at) VALUES (1, now()) ON CONFLICT (id) DO UPDATE SET at = now()"))
        db.commit()


def main() -> None:
    obs.configure("worker")
    check_config()
    state: dict = {}
    while True:
        tick(state)
        run_job("heartbeat", lambda db: heartbeat())
        try:
            Path(HEARTBEAT_FILE).touch()
        except OSError:
            log.exception("could not write the heartbeat file")
        time.sleep(TICK_S)


if __name__ == "__main__":  # pragma: no cover
    main()

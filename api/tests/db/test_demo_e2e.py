"""The demo end to end on Postgres (docs/DEMO.md §3): the six simulated controllers with the real `entry-link` on each, claimed and set up by the
seed, two days of history written through their logs, then live: a card at a reader, a forced door, and an intercom call (the simulated Akuvox
fetching its settings from the provisioning server) that ends in an unlock. Everything is read back through the API, as the demo's owner."""
from __future__ import annotations

import os
import subprocess
import threading
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
import uvicorn
from sqlalchemy import func, select

from app import demo
from app.db import SystemSession
from app.demo import seed as demo_seed
from app.deps import get_directory, get_verifier
from app.link.pgstore import PgStore
from app.main import create_app
from app.models import DoorEvent
from demo_sim import plan, run
from demo_sim.intercom import Intercom
from tests.db.conftest import VERIFIER, auth
from tests.db.test_demo import demo_org, owner_session  # noqa: F401 (a fixture)
from tests.db.test_e2e_link import ROOT, free_port, until


@pytest.fixture()
def api(fake, link, demo_org):  # noqa: F811
    r = subprocess.run(["make", "-s", "-C", os.path.join(ROOT, "acap", "entry-link")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    app = create_app(link)
    app.dependency_overrides[get_verifier] = lambda: VERIFIER
    app.dependency_overrides[get_directory] = lambda: fake.factory()
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    until(lambda: server.started, "the API")
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True


@pytest.mark.timeout(300)
def test_the_demo_from_claim_to_a_live_intercom_unlock(api, tmp_path: Path):
    runner = run.Runner(tmp_path, api, api, os.path.join(ROOT, "acap", "entry-link", "build", "entry-link"))
    try:
        runner.start_devices()
        runner.start_links()
        codes = runner.claims()
        assert set(codes) == set(run.CONTROLLERS)
        with owner_session() as db:
            roster = demo_seed.seed(db, codes, datetime.now(timezone.utc), store=PgStore(SystemSession), timeout_s=60)
        until(lambda: runner.settled(roster), "the cards on every simulated controller", timeout=30)

        done = run.history(roster["sites"], runner.devices, runner.clocks, 2, datetime.now(timezone.utc),
                           wait_read=lambda: run.read_up(runner.devices, timeout_s=60))
        assert done["granted"] > 100 and done["denied"] > 0 and done["opened_from_intercom"] > 0, done
        owner = auth("d-owner")
        http = httpx.Client(base_url=api, timeout=10)

        def events(site):
            return http.get(f"/tenants/{demo.ORG}/sites/{site}/events", headers=owner, params={"limit": 500}).json()

        def history_in():
            with SystemSession() as db:
                return db.execute(select(func.count()).select_from(DoorEvent).where(
                    DoorEvent.tenant_id == demo.ORG, DoorEvent.occurred_at < datetime.now(timezone.utc) - timedelta(hours=1))).scalar() > 500
        until(history_in, "the history in PhotonEntry", timeout=90)
        # Exactly once, in order: one row per (controller, seq), no gaps.
        with SystemSession() as db:
            per = db.execute(select(DoorEvent.controller_id, func.count(), func.max(DoorEvent.seq)).where(DoorEvent.tenant_id == demo.ORG)
                             .group_by(DoorEvent.controller_id)).all()
            assert len(per) == 6 and all(n == top for _, n, top in per), per
        kinds = Counter(e["kind"] for e in events(demo.APARTMENTS))
        assert kinds["granted"] and kinds["denied"] and kinds["intercom_call"], kinds

        # Live: the lobby intercom fetches its settings, rings, the resident answers and opens; the watcher walks through.
        ex = run.Executor(runner.devices, runner.clocks, runner.intercoms(roster), live=True)
        watcher = run.Watcher(ex)
        lobby = next(i for s in roster["sites"] for i in s["intercoms"] if i["name"] == "Lobby intercom")
        assert ex.intercoms[lobby["id"]].provision_now()
        now = datetime.now(timezone.utc)
        hq_site = plan.Site.from_roster(roster["sites"][0])
        someone = next(p for p in hq_site.people if p["tag"] == "manager")
        for a in (plan.Action(now, "call", "apt-lobby", 1, seconds=0.5, answered=True, intercom=lobby["id"]),
                  plan.Action(now, "badge", "hq-lobby", 1, id_data=(("Card", someone["card"]),)),
                  plan.Action(now, "force", "hq-lobby", 2, seconds=1)):
            ex.add(a)
        deadline = now + timedelta(seconds=40)

        def settle():
            watcher.check()
            ex.run(until=datetime.now(timezone.utc))
            return not ex.heap or datetime.now(timezone.utc) > deadline
        until(settle, "the live steps", timeout=60)

        def live(site, label):
            return [e for e in events(site) if e["label"] == label and e["occurred_at"] >= now.isoformat()[:19]]
        until(lambda: live(demo.APARTMENTS, "Opened from the intercom"), "the intercom's unlock in the API", timeout=30)
        until(lambda: live(demo.APARTMENTS, "Intercom call ended"), "the call's end", timeout=30)
        assert live(demo.APARTMENTS, "Intercom call")
        until(lambda: [e for e in live(demo.HQ, "Access granted") if e["cardholder"] == someone["name"]], "the manager's card", timeout=30)
        until(lambda: live(demo.HQ, "Door forced open"), "the forced door", timeout=30)
        # The lobby door was walked through after the unlock, and is closed and locked again.
        assert runner.devices["apt-lobby"].runtime[run.door_token("apt-lobby", 1)].physical == "Closed"
        # A restart keeps each controller's settings and recent log.
        runner.snapshot()
        snap = (tmp_path / "devices" / "apt-lobby.json").read_text()
        assert '"pe-c-' in snap and len(snap) < 15_000_000
    finally:
        runner.shutdown()

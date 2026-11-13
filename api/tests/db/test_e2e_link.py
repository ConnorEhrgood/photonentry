"""End to end on Postgres, through the integrator's own API: the real `entry-link` (C) and the simulated Axis controller, claimed, set up,
published, opened, locked down, every step done by a signed-in person with the right role, every result read back through the API."""
from __future__ import annotations

import os
import signal
import socket
import subprocess
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

import httpx
import pytest
import uvicorn
from sqlalchemy import select

from app.compiler.wiegand import card_data
from app.db import SystemSession
from app.deps import get_directory, get_verifier
from app.document import Card
from app.main import create_app
from app.models import Controller
from axis_sim.device import Device
from axis_sim.server import SimClock, run
from tests.db.conftest import VERIFIER, auth

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
MAC = "00408c184bdb"
DOOR1, DOOR2, R2IN = f"Axis-{MAC}:door1", f"Axis-{MAC}:door2", f"Axis-{MAC}:reader2in"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def until(check: Callable[[], Any], what: str, timeout: float = 20.0) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        got = check()
        if got:
            return got
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {what}")


@pytest.fixture()
def stack(world, fake, link, tmp_path):
    r = subprocess.run(["make", "-s", "-C", os.path.join(ROOT, "acap", "entry-link")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    app = create_app(link)
    app.dependency_overrides[get_verifier] = lambda: VERIFIER
    app.dependency_overrides[get_directory] = lambda: fake.factory()
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    until(lambda: server.started, "the API")
    clock = SimClock()
    device = Device(mac=MAC, doors=2, tz="America/New_York", clock=clock)
    sim_port = free_port()
    sim, _ = run(device, port=sim_port)
    log = open(tmp_path / "entry-link.log", "w")
    env = dict(os.environ, ENTRY_LINK_CLOUD=f"http://127.0.0.1:{port}", ENTRY_LINK_STATE_DIR=str(tmp_path / "state"),
               ENTRY_LINK_VAPIX=f"http://127.0.0.1:{sim_port}", ENTRY_LINK_VAPIX_USER="root", ENTRY_LINK_VAPIX_PASS="pass",
               ENTRY_LINK_MODEL="AXIS A1610", ENTRY_LINK_SERIAL=MAC.upper(), ENTRY_LINK_FIRMWARE="12.6.1", ENTRY_LINK_EVENT_POLL_MS="100")
    proc = subprocess.Popen([os.path.join(ROOT, "acap", "entry-link", "build", "entry-link")], env=env, stdout=log, stderr=log)
    api = httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=10)
    yield type("Stack", (), {"api": api, "device": device, "clock": clock, "world": world})()
    proc.send_signal(signal.SIGTERM)
    proc.wait(5)
    server.should_exit = True
    sim.should_exit = True
    log.close()


def test_a_door_from_claim_to_unlock_through_the_api(stack):
    api, w = stack.api, stack.world
    admin, op, t, s = auth("a-admin"), auth("a-op"), w.a, w.a1

    def pending_code():
        with SystemSession() as db:
            return db.execute(select(Controller.claim_code).where(Controller.state == "pending")).scalar()
    code = until(pending_code, "the controller's hello")
    r = api.post(f"/tenants/{t}/controllers/claim", headers=admin, json={"code": code, "site_id": s, "name": "Front desk"})
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    until(lambda: api.get(f"/tenants/{t}/controllers/{cid}", headers=admin).json()["inventory"], "the inventory")

    office = api.post(f"/tenants/{t}/sites/{s}/schedules", headers=admin, json={
        "name": "Office hours", "windows": [{"days": ["mo", "tu", "we", "th", "fr"], "start": "08:00", "end": "18:00"}]}).json()
    side = api.post(f"/tenants/{t}/sites/{s}/doors", headers=admin, json={"controller_id": cid, "controller_door": DOOR2, "name": "Side door"}).json()
    group = api.post(f"/tenants/{t}/sites/{s}/groups", headers=admin, json={"name": "Staff", "rules": [{"doors": [side["id"]], "schedule_id": office["id"]}]}).json()
    holder = api.post(f"/tenants/{t}/cardholders", headers=admin, json={"name": "Bob Jones"}).json()
    api.put(f"/tenants/{t}/cardholders/{holder['id']}/groups", headers=admin, json={"group_ids": [group["id"]]})
    api.post(f"/tenants/{t}/cardholders/{holder['id']}/credentials", headers=admin, json={"kind": "card", "card": {"format": "w34", "number": 3735928559}})
    pub = api.post(f"/tenants/{t}/sites/{s}/publish", headers=admin)
    assert pub.status_code == 200, pub.text
    until(lambda: api.get(f"/tenants/{t}/controllers/{cid}", headers=admin).json()["settings"]["current"], "the settings applied")
    assert "pe-c-" + api.get(f"/tenants/{t}/cardholders/{holder['id']}/credentials", headers=admin).json()[0]["id"] in stack.device.store["Credential"]

    # Monday 10:00 at the site: Bob's card opens the side door; the event comes back with his name.
    target = datetime(2026, 11, 16, 10, 0, tzinfo=ZoneInfo("America/New_York")).astimezone(timezone.utc)
    stack.clock.offset = target - datetime.now(timezone.utc)
    with stack.device.lock:
        assert stack.device.present(R2IN, [{"Name": "Card", "Value": card_data(Card(format="w34", number=3735928559))}]) == (True, "Granted")

    def granted():
        return [e for e in api.get(f"/tenants/{t}/sites/{s}/events", headers=op).json() if e["topic"] == "AccessControl/AccessGranted/Credential"]
    [event] = until(granted, "the grant in the API")
    assert event["door"] == "Side door" and event["cardholder"] == "Bob Jones"

    # The operator opens the door remotely; the controller carries it out and says so.
    cmd = api.post(f"/tenants/{t}/doors/{side['id']}/action", headers=op, json={"action": "access"}).json()
    until(lambda: api.get(f"/tenants/{t}/commands/{cmd['id']}", headers=op).json()["done"], "the remote unlock")
    assert api.get(f"/tenants/{t}/commands/{cmd['id']}", headers=op).json()["ok"] is True
    # Lockdown and its end, for the whole site.
    lock = api.post(f"/tenants/{t}/sites/{s}/lockdown", headers=op, json={"on": True}).json()["commands"][0]
    until(lambda: api.get(f"/tenants/{t}/commands/{lock['id']}", headers=op).json()["done"], "the lockdown")
    assert stack.device.runtime[DOOR2].mode == "LockedDown"
    end = api.post(f"/tenants/{t}/sites/{s}/lockdown", headers=op, json={"on": False}).json()["commands"][0]
    until(lambda: api.get(f"/tenants/{t}/commands/{end['id']}", headers=op).json()["done"], "the end of the lockdown")
    assert stack.device.runtime[DOOR2].mode != "LockedDown"
    # The owner sees it all in the audit trail.
    actions = [a["action"] for a in api.get(f"/tenants/{t}/audit", headers=auth("a-owner")).json()]
    for a in ("controller.claim", "site.publish", "door.access", "site.lockdown", "site.lockdown_end"):
        assert a in actions

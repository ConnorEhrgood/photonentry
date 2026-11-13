"""End to end, with no hardware: the real `entry-link` (C, host build) between the simulated Axis controller and the cloud's link service, each
over real HTTP. What a controller in the field does, in order: introduce itself, be claimed, report its doors, take settings, let the right
people in at the right times, send every event once and in order, carry out commands, ride out the cloud and itself going away."""
from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import pytest
import uvicorn

from app.compiler.axis import compile_controller
from app.compiler.wiegand import card_data
from app.document import Card
from app.link.service import Link
from app.link.store import MemoryStore
from app.main import create_app
from axis_sim.device import Device
from axis_sim.server import SimClock, run
from tests.fixtures.site import site

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
BINARY = os.path.join(ROOT, "acap", "entry-link", "build", "entry-link")
MAC = "00408c184bdb"
DOOR1, DOOR2 = f"Axis-{MAC}:door1", f"Axis-{MAC}:door2"
R2IN = f"Axis-{MAC}:reader2in"
BOB = card_data(Card(format="w34", number=3735928559))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def until(check: Callable[[], Any], what: str, timeout: float = 15.0) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        got = check()
        if got:
            return got
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {what}")


class Cloud:
    """The link service on a real port, restartable on the same port with the same store (a cloud outage)."""

    def __init__(self) -> None:
        self.port = free_port()
        self.link = Link(store=MemoryStore(), wait_s=2.0, poll_s=0.05)
        self.server = None

    def start(self) -> None:
        self.server = uvicorn.Server(uvicorn.Config(create_app(self.link), host="127.0.0.1", port=self.port, log_level="warning"))
        threading.Thread(target=self.server.run, daemon=True).start()
        until(lambda: self.server.started, "the cloud to start")

    def stop(self) -> None:
        self.server.should_exit = True
        time.sleep(0.3)

    @property
    def store(self) -> MemoryStore:
        return self.link.store


@pytest.fixture(scope="module")
def binary():
    r = subprocess.run(["make", "-s", "-C", os.path.join(ROOT, "acap", "entry-link")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return BINARY


@pytest.fixture()
def world(binary, tmp_path):
    clock = SimClock()
    device = Device(mac=MAC, doors=2, tz="America/New_York", clock=clock)
    sim_port = free_port()
    sim_server, _ = run(device, port=sim_port, max_limit=2)        # small pages: entry-link must follow NextStartReference
    cloud = Cloud()
    cloud.start()
    state = tmp_path / "state"
    log = open(tmp_path / "entry-link.log", "w")
    env = dict(os.environ, ENTRY_LINK_CLOUD=f"http://127.0.0.1:{cloud.port}", ENTRY_LINK_STATE_DIR=str(state),
               ENTRY_LINK_VAPIX=f"http://127.0.0.1:{sim_port}", ENTRY_LINK_VAPIX_USER="root", ENTRY_LINK_VAPIX_PASS="pass",
               ENTRY_LINK_MODEL="AXIS A1610", ENTRY_LINK_SERIAL=MAC.upper(), ENTRY_LINK_FIRMWARE="12.6.1", ENTRY_LINK_EVENT_POLL_MS="100")
    procs = []

    def start_link():
        p = subprocess.Popen([binary], env=env, stdout=log, stderr=log)
        procs.append(p)
        return p

    w = type("World", (), {})()
    w.device, w.clock, w.cloud, w.start_link, w.state, w.log_path = device, clock, cloud, start_link, state, tmp_path / "entry-link.log"
    w.proc = start_link()
    yield w
    for p in procs:
        if p.poll() is None:
            p.send_signal(signal.SIGTERM)
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                p.kill()
    cloud.stop()
    sim_server.should_exit = True
    log.close()
    if os.environ.get("KEEP_E2E_LOGS"):
        shutil.copy(tmp_path / "entry-link.log", os.path.join(ROOT, "entry-link-e2e.log"))


def at(w, local: str) -> None:
    from zoneinfo import ZoneInfo
    target = datetime.fromisoformat(local).replace(tzinfo=ZoneInfo("America/New_York")).astimezone(timezone.utc)
    w.clock.offset = target - datetime.now(timezone.utc)


def claim(w):
    pending = until(lambda: next((c for c in w.cloud.store._controllers.values() if c.state == "pending"), None), "a hello")
    assert pending.device["model"] == "AXIS A1610" and len(pending.claim_code) == 9
    c = w.cloud.store.claim(pending.claim_code, "tenant-a", "site-1", datetime.now(timezone.utc))
    until(lambda: w.cloud.store.get(c.id).inventory, "the inventory")
    return c.id


def publish(w, cid, **over):
    doors = [
        {"id": "front", "name": "Front door", "controller_id": cid, "controller_door": DOOR1, "unlock_schedule_id": "office"},
        {"id": "side", "name": "Side door", "controller_id": cid, "controller_door": DOOR2, "access_time_s": 4},
        {"id": "server", "name": "Server room", "controller_id": "another-controller", "controller_door": "door-b1"},
    ]
    settings = compile_controller(site(doors=doors, **over), cid, w.cloud.store.get(cid).inventory)
    version = w.cloud.store.publish(cid, settings)
    until(lambda: w.cloud.store.get(cid).applied_version == version, f"settings version {version} applied")
    return version


def present(w, value: str):
    with w.device.lock:
        w.device.tick()
        return w.device.present(R2IN, [{"Name": "Card", "Value": value}])


def topics(w, cid):
    return [e.topic for e in w.cloud.store.events(cid)]


def test_claim_settings_decisions_events_and_commands(world):
    w = world
    cid = claim(w)
    inv = w.cloud.store.get(cid).inventory
    assert {d.token: d.access_points for d in inv.doors} == {DOOR1: [f"Axis-{MAC}:ap1in", f"Axis-{MAC}:ap1out"], DOOR2: [f"Axis-{MAC}:ap2in"]}

    publish(w, cid)
    st = w.device.store
    assert {t for t in st["Credential"]} == {"pe-c-alice-card", "pe-c-alice-pin", "pe-c-bob-card", "pe-c-carol-card"}
    assert st["Door"][DOOR2]["AccessTime"] == "PT4S" and st["DoorConfiguration"][DOOR1]["DoorScheduleConfiguration"] == "pe-d-front"
    assert "standard_always" in st["Schedule"] and "CardOnly" in st["AuthenticationProfile"]           # Axis's own objects untouched

    at(w, "2026-11-16 10:00")                          # Monday, office hours
    assert present(w, BOB) == (True, "Granted")
    at(w, "2026-11-15 10:00")                          # Sunday
    assert present(w, BOB) == (False, "NotPermittedAtThisTime")
    until(lambda: topics(w, cid).count("AccessControl/Denied/Credential") == 1, "the denial in the cloud")
    granted = next(e for e in w.cloud.store.events(cid) if e.topic == "AccessControl/AccessGranted/Credential")
    assert granted.data["CredentialToken"] == "pe-c-bob-card" and granted.source["AccessPointToken"] == f"Axis-{MAC}:ap2in" and granted.ref

    cmd = w.cloud.store.command(cid, "access", DOOR2, "Jane at the front desk", datetime.now(timezone.utc))
    until(lambda: w.cloud.store.command_state(cmd.id).done, "the unlock command")
    assert w.cloud.store.command_state(cmd.id).ok
    assert w.device.runtime[DOOR2].mode == "Accessed"

    cmd = w.cloud.store.command(cid, "lockdown", DOOR2, "Jane", datetime.now(timezone.utc))
    until(lambda: w.cloud.store.command_state(cmd.id).done, "the lockdown")
    assert w.device.runtime[DOOR2].mode == "LockedDown"
    cmd = w.cloud.store.command(cid, "unlock", DOOR2, "Jane", datetime.now(timezone.utc))      # refused by the controller while locked down
    until(lambda: w.cloud.store.command_state(cmd.id).done, "the refused unlock")
    assert not w.cloud.store.command_state(cmd.id).ok and "Failure" in w.cloud.store.command_state(cmd.id).error
    cmd = w.cloud.store.command(cid, "lockdown_release", DOOR2, "Jane", datetime.now(timezone.utc))
    until(lambda: w.cloud.store.command_state(cmd.id).done, "the release")
    assert w.device.runtime[DOOR2].mode != "LockedDown"

    # Every event of the controller's log reached the cloud once, in order.
    until(lambda: len(w.cloud.store.events(cid)) == len(w.device.log), "every event")
    events = w.cloud.store.events(cid)
    assert [e.seq for e in events] == list(range(1, len(events) + 1))
    assert [e.ref for e in events] == [r["token"] for r in w.device.log]


def test_settings_change_and_removal(world):
    w = world
    cid = claim(w)
    publish(w, cid)
    at(w, "2026-11-16 10:00")
    assert present(w, BOB)[0] is True
    # Bob is suspended, Carol leaves, the side door gets a longer access time.
    doc = site()
    holders = [h.model_dump() for h in doc.cardholders if h.id != "carol"]
    for h in holders:
        if h["id"] == "bob":
            h["suspended"] = True
    v2 = publish(w, cid, cardholders=holders)
    assert v2 == 2
    assert present(w, BOB) == (False, "CredentialNotEnabled")
    assert "pe-c-carol-card" not in w.device.store["Credential"] and "pe-u-carol" not in w.device.store["User"]
    # Something made on the controller by hand is left alone (it is not ours).
    w.device.store["User"]["installer-test"] = {"token": "installer-test", "Name": "Test", "Attribute": []}
    publish(w, cid, cardholders=holders, holiday_calendar_id=None)
    assert "installer-test" in w.device.store["User"]


def test_settings_that_fail_are_reported_and_not_resent(world):
    w = world
    cid = claim(w)
    settings = compile_controller(site(doors=[
        {"id": "front", "name": "Front", "controller_id": cid, "controller_door": DOOR1},
        {"id": "side", "name": "Side", "controller_id": cid, "controller_door": DOOR2},
        {"id": "server", "name": "Server", "controller_id": "another-controller", "controller_door": "door-b1"}]), cid,
                                  w.cloud.store.get(cid).inventory)
    settings["access_profiles"][0]["AccessPolicy"][0]["AccessPoint"] = "no-such-access-point"   # the controller will refuse this
    version = w.cloud.store.publish(cid, settings)
    until(lambda: w.cloud.store.get(cid).apply_error, "the failure report")
    assert "InvalidAccessProfileFault" in w.cloud.store.get(cid).apply_error and w.cloud.store.get(cid).applied_version != version
    good = publish(w, cid)
    assert good == version + 1 and w.cloud.store.get(cid).apply_error == ""


def test_the_cloud_away_loses_nothing(world):
    w = world
    cid = claim(w)
    publish(w, cid)
    at(w, "2026-11-16 10:00")
    w.cloud.stop()
    for _ in range(25):
        assert present(w, BOB)[0] is True                  # the controller decides alone
        with w.device.lock:
            w.device.set_physical(DOOR2, "Open")
            w.device.set_physical(DOOR2, "Closed")
    time.sleep(1.0)
    w.cloud.start()
    until(lambda: len(w.cloud.store.events(cid)) == len(w.device.log), "every event after the outage", timeout=40)
    assert [e.seq for e in w.cloud.store.events(cid)] == list(range(1, len(w.device.log) + 1))


def test_a_restart_keeps_identity_queue_and_settings(world):
    w = world
    cid = claim(w)
    publish(w, cid)
    until(lambda: len(w.cloud.store.events(cid)) == len(w.device.log), "the first events")
    w.cloud.stop()
    at(w, "2026-11-16 10:00")
    present(w, BOB)
    time.sleep(0.5)                                       # read into the queue, not delivered
    w.proc.send_signal(signal.SIGTERM)
    w.proc.wait(5)
    queued = (w.state / "queue.jsonl").read_text().strip().splitlines()
    assert queued, "events were queued on disk"
    w.cloud.start()
    w.proc = w.start_link()
    until(lambda: len(w.cloud.store.events(cid)) == len(w.device.log), "the queued events after the restart")
    assert [e.seq for e in w.cloud.store.events(cid)] == list(range(1, len(w.device.log) + 1))
    assert len(w.cloud.store._controllers) == 1                   # the same key: not a new controller
    assert w.cloud.store.get(cid).applied_version == 1


def test_the_controller_away_and_back(world):
    w = world
    cid = claim(w)
    publish(w, cid)
    w.device.offline = True
    at(w, "2026-11-16 10:00")
    present(w, BOB)                                       # the device decides; only its API is unreachable
    time.sleep(0.5)
    w.device.offline = False
    until(lambda: len(w.cloud.store.events(cid)) == len(w.device.log), "the events after the controller's API returns")


def test_a_disabled_controller_stops_syncing(world):
    w = world
    cid = claim(w)
    w.cloud.store.disable(cid)
    w.cloud.store._marks[cid] = w.cloud.store.mark(cid) + 1
    time.sleep(3.0)
    seen = w.cloud.store.get(cid).last_seen
    time.sleep(2.0)
    assert w.cloud.store.get(cid).last_seen == seen                    # no more syncs, only hellos (which do not count as syncs)
    assert "disabled" in w.log_path.read_text()

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi.testclient import TestClient

from app.link import signing
from app.link.service import MAX_BODY, Link
from app.link.store import MemoryStore
from app.main import create_app

NOW = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)
DEVICE = {"model": "A1610", "serial": "B8A44F000001", "firmware": "12.6.1", "app_version": "0.1.0"}


class Controller:
    """A controller as the cloud sees one: a key and signed calls."""

    def __init__(self, client, key=None):
        self.client, self.key = client, key or Ed25519PrivateKey.generate()
        self.pub = self.key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)

    def post(self, path, payload, t=None, key=None, raw=None):
        body = raw if raw is not None else json.dumps(payload).encode()
        header = signing.sign(key or self.key, int((t or NOW).timestamp()), "POST", path, body)
        return self.client.post(path, content=body, headers={signing.HEADER: header, "content-type": "application/json"})

    def hello(self, code="ABCD-EFGH"):
        return self.post("/link/v1/hello", {"public_key": signing.b64u(self.pub), "claim_code": code, "device": DEVICE})

    def sync(self, **body):
        return self.post("/link/v1/sync", body)


@pytest.fixture()
def link():
    return Link(store=MemoryStore(), clock=lambda: NOW, wait_s=0.6, poll_s=0.02)


@pytest.fixture()
def client(link):
    with TestClient(create_app(link)) as c:
        yield c


def claimed(client, link, code="ABCD-EFGH"):
    ctl = Controller(client)
    assert ctl.hello(code).json() == {"state": "pending", "controller_id": None}
    ctl.id = link.store.claim(code, "tenant-a", "site-1", NOW).id
    return ctl


def test_healthz(client):
    assert client.get("/healthz").json() == {"ok": True}


def test_hello_then_claim_then_sync(client, link):
    ctl = Controller(client)
    assert ctl.sync().status_code == 401                                    # unknown key
    assert ctl.hello().json()["state"] == "pending"
    r = ctl.sync()
    assert r.status_code == 403 and r.json() == {"state": "pending"}
    cid = link.store.claim("ABCD-EFGH", "tenant-a", "site-1", NOW).id
    assert ctl.hello().json() == {"state": "claimed", "controller_id": cid}
    assert ctl.sync().json() == {"ack_seq": 0, "settings": None, "commands": [], "poll_after_ms": 0}


def test_hello_must_be_signed_by_the_key_it_names(client):
    ctl, other = Controller(client), Ed25519PrivateKey.generate()
    body = {"public_key": signing.b64u(ctl.pub), "claim_code": "ABCD-EFGH", "device": DEVICE}
    assert ctl.post("/link/v1/hello", body, key=other).status_code == 401


@pytest.mark.parametrize("payload", [
    {"public_key": "x", "claim_code": "bad", "device": DEVICE},
    {"public_key": signing.b64u(b"short"), "claim_code": "ABCD-EFGH", "device": DEVICE},
    {"public_key": "!!!", "claim_code": "ABCD-EFGH", "device": DEVICE},
])
def test_malformed_hello(client, payload):
    assert Controller(client).post("/link/v1/hello", payload).status_code == 400


def test_bodies_too_large_are_refused(client, link):
    ctl = claimed(client, link)
    big = b"{" + b" " * (MAX_BODY + 1) + b"}"
    assert ctl.post("/link/v1/sync", None, raw=big).status_code == 413
    assert ctl.post("/link/v1/hello", None, raw=big).status_code == 413


def test_malformed_sync(client, link):
    ctl = claimed(client, link)
    assert ctl.sync(nonsense=1).status_code == 400
    assert ctl.post("/link/v1/sync", None, raw=b"not json").status_code == 400


def test_a_disabled_controller_is_told_so(client, link):
    ctl = claimed(client, link)
    link.store.disable(ctl.id)
    r = ctl.sync()
    assert r.status_code == 403 and r.json() == {"state": "disabled"}


def test_settings_until_applied_and_not_resent_when_they_failed(client, link):
    ctl = claimed(client, link)
    link.store.publish(ctl.id, {"users": []})
    assert ctl.sync().json()["settings"] == {"version": 1, "document": {"users": []}}
    assert ctl.sync(applied_version=1).json()["settings"] is None
    link.store.publish(ctl.id, {"users": [1]})
    assert ctl.sync(applied_version=1, failed_version=2, apply_error="capacity").json()["settings"] is None
    assert link.store.get(ctl.id).apply_error == "capacity"
    link.store.publish(ctl.id, {"users": [2]})
    assert ctl.sync(applied_version=1, failed_version=2).json()["settings"]["version"] == 3


def test_inventory_health_events_and_results(client, link):
    ctl = claimed(client, link)
    cmd = link.store.command(ctl.id, "access", "d1", "Jane", NOW)
    events = [{"seq": n, "occurred_at": NOW.isoformat(), "topic": "tns1:Door/State/DoorPhysicalState", "source": {"DoorToken": "d1"},
               "data": {"State": "Open"}} for n in (1, 2)]
    r = ctl.sync(inventory={"doors": [{"token": "d1", "name": "Front", "access_points": ["ap1"]}]}, events=events,
                 results=[{"id": cmd.id, "ok": True}], health={"uptime_s": 9, "queued_events": 0})
    assert r.json()["ack_seq"] == 2 and r.json()["commands"] == []
    c = link.store.get(ctl.id)
    assert c.inventory.doors[0].token == "d1" and c.health["uptime_s"] == 9
    assert link.store.command_state(cmd.id).ok is True


def test_commands_are_handed_out(client, link):
    ctl = claimed(client, link)
    cmd = link.store.command(ctl.id, "unlock", "d1", "Jane", NOW)
    got = ctl.sync().json()["commands"]
    assert [c["id"] for c in got] == [cmd.id] and got[0]["kind"] == "unlock"


def test_a_held_sync_returns_when_a_command_arrives(client, link):
    ctl = claimed(client, link)
    link.wait_s = 5
    threading.Timer(0.2, lambda: link.store.command(ctl.id, "access", "d1", "Jane", NOW)).start()
    started = time.monotonic()
    got = ctl.sync(wait=True).json()
    assert got["commands"] and time.monotonic() - started < 3


def test_a_held_sync_ends_after_the_wait(client, link):
    ctl = claimed(client, link)
    started = time.monotonic()
    assert ctl.sync(wait=True).json()["commands"] == []
    assert 0.5 <= time.monotonic() - started < 3


def test_a_held_sync_with_events_does_not_wait(client, link):
    ctl = claimed(client, link)
    started = time.monotonic()
    ctl.sync(wait=True, events=[{"seq": 1, "occurred_at": NOW.isoformat(), "topic": "t"}])
    assert time.monotonic() - started < 0.5


def test_a_controller_disabled_while_held_is_told_so(client, link):
    ctl = claimed(client, link)
    link.wait_s = 5
    threading.Timer(0.2, lambda: link.store.disable(ctl.id)).start()
    r = ctl.sync(wait=True)
    assert r.status_code == 403 and r.json() == {"state": "disabled"}


def test_a_replayed_sync_is_refused(client, link):
    ctl = claimed(client, link)
    body = json.dumps({}).encode()
    header = signing.sign(ctl.key, int(NOW.timestamp()), "POST", "/link/v1/sync", body)
    headers = {signing.HEADER: header, "content-type": "application/json"}
    assert client.post("/link/v1/sync", content=body, headers=headers).status_code == 200
    assert client.post("/link/v1/sync", content=body, headers=headers).status_code == 401


def test_a_stale_clock_is_refused(client, link):
    ctl = claimed(client, link)
    assert ctl.post("/link/v1/sync", {}, t=NOW - timedelta(minutes=10)).status_code == 401


def test_the_default_clock_is_utc_now():
    from app.link.service import _utcnow
    assert abs((_utcnow() - datetime.now(timezone.utc)).total_seconds()) < 5

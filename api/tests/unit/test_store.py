"""The store's rules, written against the interface so the Postgres store (Step 2) runs the same tests."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import os

import pytest

from app.link.protocol import Event, Inventory, InventoryDoor
from app.link.store import CLAIM_TTL_S, REDELIVER_S, MemoryStore, NotFound

T0 = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)
DEVICE = {"model": "A1610", "serial": "B8A44F000001", "firmware": "12.6.1", "app_version": "0.1.0"}


STORES = ["memory"] + (["postgres"] if os.environ.get("PHOTONENTRY_DB_TESTS") else [])


@pytest.fixture(params=STORES)
def store(request):
    if request.param == "memory":
        return MemoryStore()
    # The same rules on Postgres (the database suite's schema fixture has migrated it; each test starts empty).
    request.getfixturevalue("clean")
    from app.db import SystemSession
    from app.link.pgstore import PgStore
    return PgStore(SystemSession, request.getfixturevalue("listener"))


TENANT_A, SITE_1 = "0a000000-0000-4000-8000-00000000000a", "05000000-0000-4000-8000-000000000001"
TENANT_B, SITE_2 = "0b000000-0000-4000-8000-00000000000b", "05000000-0000-4000-8000-000000000002"


def _claimed(store, kid="k1"):
    store.hello(kid, b"p" * 32, "ABCD-EFGH", DEVICE, T0)
    return store.claim("ABCD-EFGH", TENANT_A, SITE_1, T0)


def ev(seq):
    return Event(seq=seq, occurred_at=T0, topic="tns1:Door/State/DoorPhysicalState", source={"DoorToken": "d1"}, data={"State": "Open"})


def test_hello_records_a_pending_controller_and_refreshes_it(store):
    c = store.hello("k1", b"p" * 32, "ABCD-EFGH", DEVICE, T0)
    assert c.state == "pending" and c.claim_code == "ABCD-EFGH"
    again = store.hello("k1", b"p" * 32, "WXYZ-2345", {**DEVICE, "firmware": "12.7"}, T0 + timedelta(minutes=1))
    assert again.id == c.id and again.claim_code == "WXYZ-2345" and again.device["firmware"] == "12.7"


def test_claim_by_code_once(store):
    c = _claimed(store)
    assert c.state == "claimed" and c.tenant_id == TENANT_A and c.site_id == SITE_1 and c.claim_code == ""
    with pytest.raises(NotFound):
        store.claim("ABCD-EFGH", TENANT_B, SITE_2, T0)
    # A claimed controller keeps its state on a later hello.
    assert store.hello("k1", b"p" * 32, "QQQQ-QQQQ", DEVICE, T0).state == "claimed"


def test_claim_codes_expire_and_are_case_insensitive(store):
    store.hello("k1", b"p" * 32, "ABCD-EFGH", DEVICE, T0)
    with pytest.raises(NotFound):
        store.claim("ABCD-EFGH", TENANT_A, SITE_1, T0 + timedelta(seconds=CLAIM_TTL_S + 1))
    assert store.claim("abcd-efgh", TENANT_A, SITE_1, T0).state == "claimed"


def test_unknown_controllers(store):
    assert store.by_key("nope") is None
    missing = "0f000000-0000-4000-8000-0000000000ff"
    for call in (lambda: store.get("x"), lambda: store.disable("x"), lambda: store.publish("x", {}), lambda: store.command_state("x"),
                 lambda: store.get(missing)):
        with pytest.raises(NotFound):
            call()


def test_events_are_stored_once_in_order(store):
    c = _claimed(store)
    assert store.add_events(c.id, [ev(2), ev(1)], T0) == 2
    assert store.add_events(c.id, [ev(1), ev(2), ev(3)], T0) == 3          # 1 and 2 are resends
    assert store.add_events(c.id, [ev(5), ev(6)], T0) == 3                 # a gap: nothing taken, the controller resends from 4
    assert store.add_events(c.id, [ev(4), ev(5), ev(7)], T0) == 5          # taken up to the next gap
    assert [e.seq for e in store.events(c.id)] == [1, 2, 3, 4, 5]


def test_settings_versions(store):
    c = _claimed(store)
    assert store.latest(c.id) is None
    assert store.publish(c.id, {"a": 1}) == 1
    assert store.publish(c.id, {"a": 2}) == 2
    assert store.latest(c.id) == (2, {"a": 2})


def test_state_inventory_and_health(store):
    c = _claimed(store)
    store.set_inventory(c.id, Inventory(doors=[InventoryDoor(token="d1", access_points=["ap1"])]))
    store.set_applied(c.id, 3, "capacity", 4)
    store.seen(c.id, T0, {"uptime_s": 5})
    got = store.get(c.id)
    assert got.inventory.doors[0].token == "d1" and got.applied_version == 3 and got.health == {"uptime_s": 5}
    assert (got.failed_version, got.apply_error) == (4, "capacity")
    store.disable(c.id)
    assert store.get(c.id).state == "disabled"


def test_commands_expire_redeliver_and_finish_once(store):
    c = _claimed(store)
    cmd = store.command(c.id, "access", "d1", "Jane", T0)
    assert [x.id for x in store.due_commands(c.id, T0)] == [cmd.id]
    assert store.due_commands(c.id, T0 + timedelta(seconds=1)) == []                      # handed out a moment ago
    assert [x.id for x in store.due_commands(c.id, T0 + timedelta(seconds=REDELIVER_S + 1))] == [cmd.id]
    assert store.due_commands(c.id, cmd.expires_at) == []                                  # expired: never again
    store.finish_command(c.id, cmd.id, True, "")
    store.finish_command(c.id, cmd.id, False, "late duplicate")                            # the first answer stands
    store.finish_command(c.id, "cmd_unknown", True, "")
    st = store.command_state(cmd.id)
    assert st.done and st.ok and st.error == ""


def test_commands_are_per_controller_and_only_in_service(store):
    c = _claimed(store)
    store.hello("k2", b"q" * 32, "ZZZZ-ZZZZ", DEVICE, T0)
    other = store.claim("ZZZZ-ZZZZ", TENANT_B, SITE_2, T0)
    cmd = store.command(c.id, "lockdown", "d1", "Jane", T0)
    assert store.due_commands(other.id, T0) == []
    store.finish_command(other.id, cmd.id, True, "")                                       # not its command: ignored
    assert not store.command_state(cmd.id).done
    store.disable(c.id)
    with pytest.raises(NotFound):
        store.command(c.id, "access", "d1", "Jane", T0)


def _changes(store, cid, m):
    for _ in range(100):                     # the Postgres store learns through LISTEN/NOTIFY, a moment after the commit
        if store.mark(cid) != m:
            return True
        time.sleep(0.02)
    return False


def test_marks_change_when_there_is_something_new(store):
    c = _claimed(store)
    m = store.mark(c.id)
    store.publish(c.id, {})
    assert _changes(store, c.id, m)
    m = store.mark(c.id)
    store.command(c.id, "access", "d1", "", T0)
    assert _changes(store, c.id, m)
    m = store.mark(c.id)
    store.disable(c.id)
    assert _changes(store, c.id, m)

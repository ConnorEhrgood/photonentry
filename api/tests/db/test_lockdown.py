"""Lockdown as a record (ARCHITECTURE §9.6): scope and reason, one at a time, each door's state, who ended it and why, who sees it."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import ProgrammingError

from app.models import AuditLog, Lockdown
from tests.db.conftest import as_person, auth
from tests.db.test_routes import setup_site


def lock(client, world, who="a-op", **body):
    return client.post(f"/tenants/{world.a}/sites/{world.a1}/lockdown", headers=auth(who), json={"on": True, "reason": "Threat reported", **body})


def end(client, world, who="a-op", reason="All clear from police"):
    return client.post(f"/tenants/{world.a}/sites/{world.a1}/lockdown", headers=auth(who), json={"on": False, "reason": reason})


def test_a_lockdown_with_a_reason_its_doors_and_its_end(client, world, link, db):
    ids = setup_site(client, world, link)
    assert client.post(f"/tenants/{world.a}/sites/{world.a1}/lockdown", headers=auth("a-op"), json={"on": True}).status_code == 422
    assert lock(client, world, reason="   ").status_code == 422
    r = lock(client, world)
    assert r.status_code == 202, r.text
    lk = r.json()["lockdown"]
    assert (lk["active"], lk["whole_site"], lk["reason"], lk["started_by"], lk["source"]) == (True, True, "Threat reported", "A Op", "app")
    assert sorted(d["door"] for d in lk["doors"]) == ["Front door", "Side door"] and {d["state"] for d in lk["doors"]} == {"sent"}
    due = link.store.due_commands(ids["controller"], datetime.now(timezone.utc))
    assert sorted((c.kind, c.door) for c in due) == [("lockdown", "door1"), ("lockdown", "door2")]
    # The controller confirms one door and refuses the other: each door says so.
    link.store.finish_command(ids["controller"], due[0].id, True, "")
    link.store.finish_command(ids["controller"], due[1].id, False, "Failure")
    shown = client.get(f"/tenants/{world.a}/sites/{world.a1}/lockdowns", headers=auth("a-viewer")).json()[0]
    assert sorted(d["state"] for d in shown["doors"]) == ["done", "failed"]
    # One at a time; everyone at the site sees it; the banner lists it.
    assert lock(client, world, who="a-admin").json()["detail"]["code"] == "already_locked_down"
    banner = client.get(f"/tenants/{world.a}/lockdowns/active", headers=auth("a-viewer")).json()
    assert [b["site"] for b in banner] == ["Main office"]
    assert client.get(f"/tenants/{world.a}/lockdowns/active", headers=auth("a-viewer-s2")).json() == []      # not their site
    # Ending it: the same doors released, with a reason, by name.
    assert end(client, world, who="a-viewer").status_code == 403
    assert end(client, world, reason="").status_code == 422
    r = end(client, world, who="tech")
    assert r.status_code == 202, r.text
    over = r.json()["lockdown"]
    assert (over["active"], over["ended_by"], over["end_reason"]) == (False, "Partner support", "All clear from police")
    assert sorted(c["kind"] for c in r.json()["commands"]) == ["lockdown_release", "lockdown_release"]
    assert end(client, world).json()["detail"]["code"] == "not_locked_down"
    assert client.get(f"/tenants/{world.a}/lockdowns/active", headers=auth("a-viewer")).json() == []
    trail = [(a.action, a.detail.get("reason")) for a in db.execute(select(AuditLog).order_by(AuditLog.id)).scalars() if "lockdown" in a.action]
    assert trail == [("site.lockdown", "Threat reported"), ("site.lockdown_end", "All clear from police")]


def test_some_doors_only_and_a_controller_out_of_service(client, world, link, db):
    ids = setup_site(client, world, link)
    assert lock(client, world, door_ids=[str(uuid.uuid4())]).json()["detail"]["code"] == "no_such_door"
    assert lock(client, world, door_ids=[]).status_code == 422
    db.execute(text("UPDATE controller SET state = 'disabled' WHERE id = :c"), {"c": ids["controller"]})
    db.commit()
    r = lock(client, world, door_ids=[ids["side"]])
    assert r.status_code == 202, r.text
    lk = r.json()["lockdown"]
    # Never refused as a whole: the door is listed, and why it could not be reached.
    assert (lk["whole_site"], [d["door"] for d in lk["doors"]]) == (False, ["Side door"])
    assert lk["doors"][0]["state"] == "not_sent" and "not in service" in lk["doors"][0]["error"]
    assert end(client, world).json()["lockdown"]["doors"][0]["state"] == "not_sent"


def test_a_site_with_no_doors_and_who_may_start_one(client, world, link):
    assert lock(client, world).json()["detail"]["code"] == "no_doors"
    setup_site(client, world, link)
    assert lock(client, world, who="a-viewer").status_code == 403
    assert client.post(f"/tenants/{world.b}/sites/{world.a1}/lockdown", headers=auth("b-owner"),
                       json={"on": True, "reason": "x"}).status_code == 404


def test_row_level_security_writes_only_in_ones_own_name(client, world, link):
    setup_site(client, world, link)
    lock(client, world)
    with as_person(world.pid("a-viewer")) as s:
        assert len(s.execute(select(Lockdown)).scalars().all()) == 1
        assert s.execute(text("UPDATE lockdown SET end_reason = 'x' RETURNING id")).all() == []      # viewers cannot end it
    with as_person(world.pid("a-op")) as s, pytest.raises(ProgrammingError, match="permission denied"):
        s.execute(text("UPDATE lockdown SET reason = 'changed'"))                                    # what started it is never rewritten
    with as_person(world.pid("b-owner")) as s:
        assert s.execute(select(Lockdown)).scalars().all() == []


def test_two_lockdowns_at_once_and_doors_not_confirmed_in_time(client, world, link, db, monkeypatch):
    setup_site(client, world, link)
    first = lock(client, world).json()["lockdown"]
    # Started a moment after another, past the check: the database's one-active-per-site index refuses it.
    from app.routes import lockdown as route
    monkeypatch.setattr(route, "_active", lambda db, site_id: None)
    r = lock(client, world, who="a-admin")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "already_locked_down"
    monkeypatch.undo()
    # A command never confirmed before it expired; one whose record is gone (still waiting, as far as anyone can tell).
    lk = db.get(Lockdown, uuid.UUID(first["id"]))
    db.execute(text("UPDATE link_command SET expires_at = now() - interval '1 minute' WHERE id = :c"), {"c": lk.start_commands[0]})
    db.execute(text("UPDATE lockdown SET start_commands = jsonb_set(start_commands, '{1}', '\"cmd_gone\"') WHERE id = :l"), {"l": lk.id})
    db.commit()
    shown = client.get(f"/tenants/{world.a}/lockdowns/active", headers=auth("a-viewer")).json()[0]
    assert [d["state"] for d in shown["doors"]] == ["expired", "sent"]

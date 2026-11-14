"""Opening one's own doors from the app (decision 25): the door user role, linking to a cardholder, which doors open when, and nothing else."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select, text

from app.models import AuditLog, Cardholder, LinkCommand
from app.routes import unlock as route
from tests.db.conftest import auth, pull
from tests.db.test_routes import setup_site

NY = ZoneInfo("America/New_York")
MONDAY_10 = datetime(2026, 11, 16, 10, 0, tzinfo=NY).astimezone(timezone.utc)
SUNDAY_10 = datetime(2026, 11, 15, 10, 0, tzinfo=NY).astimezone(timezone.utc)


@pytest.fixture(autouse=True)
def monday(monkeypatch):
    monkeypatch.setattr(route, "_now", lambda: MONDAY_10)
    route.open_throttle.hits.clear()


def door_user(fake, world, db, sub="a-door", email="dana@example.com", role="door_user"):
    pid = fake.add_person(sub, name="Dana Door")
    fake.grant(pid, world.a, role)
    assert pull(fake).ok
    db.execute(text("UPDATE person SET email = :e WHERE sub = :s"), {"e": email, "s": sub})
    db.commit()
    return uuid.UUID(pid)


def staff_member(client, world, ids, name="Dana Door", email="Dana@Example.com"):
    h = client.post(f"/tenants/{world.a}/cardholders", headers=auth("a-admin"), json={"name": name, "email": email}).json()
    client.put(f"/tenants/{world.a}/cardholders/{h['id']}/groups", headers=auth("a-admin"), json={"group_ids": [ids["staff"]]})
    return h


def test_a_door_user_signs_in_is_linked_by_email_and_opens_their_door(client, world, link, fake, db):
    ids = setup_site(client, world, link)
    pid = door_user(fake, world, db)
    holder = staff_member(client, world, ids)
    me = client.get("/me", headers=auth("a-door")).json()["tenants"][0]
    assert (me["name"], me["role"], me["capabilities"]) == ("Cedar Works", "door_user", ["entry.unlock.own"])
    mine = client.get(f"/tenants/{world.a}/my/doors", headers=auth("a-door")).json()
    assert mine["linked"] is True and [(d["door"], d["can_open"]) for d in mine["doors"]] == [("Front door", True), ("Side door", True)]
    assert db.get(Cardholder, uuid.UUID(holder["id"])).person_id == pid                                # linked by email, case aside
    r = client.post(f"/tenants/{world.a}/my/doors/{ids['side']}/open", headers=auth("a-door"))
    assert r.status_code == 202, r.text
    cmd = db.get(LinkCommand, r.json()["id"])
    assert (cmd.kind, cmd.door, cmd.actor_person_id) == ("access", "door2", pid)
    state = client.get(f"/tenants/{world.a}/my/commands/{cmd.id}", headers=auth("a-door")).json()
    assert state == {"id": cmd.id, "done": False, "ok": None, "error": "", "expired": False}
    assert db.execute(select(AuditLog).where(AuditLog.action == "door.open_own")).scalar_one().actor_label == "Dana Door"
    # Nothing else of PhotonEntry is theirs.
    for path in ("/sites", "/cardholders", "/controllers", "/lockdowns/active"):
        assert client.get(f"/tenants/{world.a}{path}", headers=auth("a-door")).status_code in (403, 404), path
    assert client.post(f"/tenants/{world.a}/doors/{ids['side']}/action", headers=auth("a-door"), json={"action": "access"}).status_code in (403, 404)
    # Someone else's command is not theirs to read.
    other = client.post(f"/tenants/{world.a}/doors/{ids['side']}/action", headers=auth("a-op"), json={"action": "access"}).json()["id"]
    assert client.get(f"/tenants/{world.a}/my/commands/{other}", headers=auth("a-door")).status_code == 404


def test_which_doors_open_and_why_not(client, world, link, fake, db, monkeypatch):
    ids = setup_site(client, world, link)
    door_user(fake, world, db)
    staff_member(client, world, ids)
    base = f"/tenants/{world.a}/my/doors"
    monkeypatch.setattr(route, "_now", lambda: SUNDAY_10)                                              # Staff is office hours, weekdays
    assert {d["why"] for d in client.get(base, headers=auth("a-door")).json()["doors"]} == {"outside_schedule"}
    r = client.post(f"{base}/{ids['front']}/open", headers=auth("a-door"))
    assert r.status_code == 409 and r.json()["detail"]["detail"] == "Front door: not at this time"
    monkeypatch.setattr(route, "_now", lambda: MONDAY_10)
    client.post(f"/tenants/{world.a}/sites/{world.a1}/lockdown", headers=auth("a-op"), json={"on": True, "reason": "Drill", "door_ids": [ids["front"]]})
    doors = {d["door"]: d for d in client.get(base, headers=auth("a-door")).json()["doors"]}
    assert (doors["Front door"]["why"], doors["Front door"]["why_text"], doors["Side door"]["can_open"]) == ("locked_down", "Locked down", True)
    client.post(f"/tenants/{world.a}/sites/{world.a1}/doors/{ids['side']}/commissioning/void", headers=auth("a-admin"), json={"reason": "New lock"})
    doors = {d["door"]: d for d in client.get(base, headers=auth("a-door")).json()["doors"]}
    assert doors["Side door"]["why"] == "not_commissioned"
    assert client.post(f"{base}/{uuid.uuid4()}/open", headers=auth("a-door")).status_code == 404                # not one of theirs
    db.execute(text("UPDATE controller SET state = 'disabled'"))
    db.commit()
    assert {d["why"] for d in client.get(base, headers=auth("a-door")).json()["doors"]} == {"out_of_service"}


def test_no_cardholder_an_ambiguous_email_a_suspended_record_and_too_many_tries(client, world, link, fake, db):
    ids = setup_site(client, world, link)
    door_user(fake, world, db)
    base = f"/tenants/{world.a}/my/doors"
    assert client.get(base, headers=auth("a-door")).json() == {"linked": False, "doors": []}                # no record yet: no doors
    staff_member(client, world, ids, name="Dana One")
    staff_member(client, world, ids, name="Dana Two")                                                    # the same address twice
    assert client.get(base, headers=auth("a-door")).json()["linked"] is False                              # ambiguous: an admin links by hand
    holders = client.get(f"/tenants/{world.a}/cardholders", headers=auth("a-admin")).json()
    one = next(h for h in holders if h["name"] == "Dana One")
    pid = str(db.execute(text("SELECT id FROM person WHERE sub = 'a-door'")).scalar())
    assert client.patch(f"/tenants/{world.a}/cardholders/{one['id']}", headers=auth("a-admin"), json={"person_id": pid}).status_code == 200
    two = next(h for h in holders if h["name"] == "Dana Two")
    r = client.patch(f"/tenants/{world.a}/cardholders/{two['id']}", headers=auth("a-admin"), json={"person_id": pid})
    assert r.status_code == 409 and "already linked to Dana One" in r.json()["detail"]["detail"]
    stranger = str(db.execute(text("SELECT id FROM person WHERE sub = 'stranger'")).scalar())
    r = client.patch(f"/tenants/{world.a}/cardholders/{two['id']}", headers=auth("a-admin"), json={"person_id": stranger})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "not_a_member"
    r = client.post(f"/tenants/{world.a}/cardholders", headers=auth("a-admin"), json={"name": "Dana Three", "person_id": stranger})
    assert r.status_code == 422
    for _ in range(10):
        client.post(f"{base}/{ids['front']}/open", headers=auth("a-door"))
    assert client.post(f"{base}/{ids['front']}/open", headers=auth("a-door")).status_code == 429
    client.patch(f"/tenants/{world.a}/cardholders/{one['id']}", headers=auth("a-admin"), json={"suspended": True})
    assert client.get(base, headers=auth("a-door")).json() == {"linked": True, "doors": []}


def test_every_role_can_open_its_own_doors_and_a_viewer_too(client, world, link, fake, db):
    ids = setup_site(client, world, link)
    db.execute(text("UPDATE person SET email = 'viv@example.com' WHERE sub = 'a-viewer'"))
    db.commit()
    staff_member(client, world, ids, name="Viv Viewer", email="viv@example.com")
    assert client.post(f"/tenants/{world.a}/my/doors/{ids['front']}/open", headers=auth("a-viewer")).status_code == 202
    assert client.get(f"/tenants/{world.a}/my/doors", headers=auth("b-owner")).status_code == 404            # another customer


def test_the_best_of_several_groups_a_removed_site_and_a_stale_rule(client, world, link, fake, db):
    ids = setup_site(client, world, link)
    door_user(fake, world, db)
    holder = staff_member(client, world, ids)
    anytime = client.post(f"/tenants/{world.a}/sites/{world.a1}/groups", headers=auth("a-admin"),
                          json={"name": "Anytime", "rules": [{"doors": [ids["front"]]}]}).json()
    client.put(f"/tenants/{world.a}/cardholders/{holder['id']}/groups", headers=auth("a-admin"), json={"group_ids": [ids["staff"], anytime["id"]]})
    from app.routes import unlock as r

    def sunday():
        return SUNDAY_10
    r_now = r._now
    r._now = sunday
    try:
        doors = {d["door"]: d["can_open"] for d in client.get(f"/tenants/{world.a}/my/doors", headers=auth("a-door")).json()["doors"]}
        assert doors == {"Front door": True, "Side door": False}                       # Anytime opens the front door even on Sunday
        # A rule naming a door that is gone (a stale rule) is skipped, never an error.
        db.execute(text("UPDATE access_group SET rules = jsonb_set(rules, '{0,doors}', rules->0->'doors' || to_jsonb(CAST(:gone AS text))) WHERE id = :g"),
                   {"gone": str(uuid.uuid4()), "g": anytime["id"]})
        db.commit()
        assert len(client.get(f"/tenants/{world.a}/my/doors", headers=auth("a-door")).json()["doors"]) == 2
        # A site taken out of service: its doors are nobody's to open.
        db.execute(text("UPDATE site SET status = 'removed' WHERE id = :s"), {"s": world.a1})
        db.commit()
        assert client.get(f"/tenants/{world.a}/my/doors", headers=auth("a-door")).json()["doors"] == []
    finally:
        r._now = r_now
    assert client.get(f"/tenants/{world.a}/my/commands/cmd_nothing", headers=auth("a-door")).status_code == 404

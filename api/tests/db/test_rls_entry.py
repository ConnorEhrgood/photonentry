"""PhotonEntry's own row-level security, tested at the database with no filter in the query: what a route that forgot its checks would get."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import insert, select, text, update
from sqlalchemy.exc import DBAPIError, ProgrammingError

from app.models import AccessGroup, AuditLog, Cardholder, CardholderGroup, Controller, Credential, Door, DoorEvent, LinkCommand, Schedule
from tests.db.conftest import as_person

WINDOWS = [{"days": ["mo"], "start": "08:00", "end": "09:00"}]


@pytest.fixture()
def data(world, db):
    """A controller and its door at each of Cedar Works' sites, a schedule and a group at a1, a cardholder with a card, an event and a command."""
    a, a1, a2 = uuid.UUID(world.a), uuid.UUID(world.a1), uuid.UUID(world.a2)
    out = {}
    for site, name in ((a1, "main"), (a2, "annex")):
        c = Controller(id=uuid.uuid4(), key_id=uuid.uuid4().hex[:16], public_key=b"k" * 32, state="claimed", tenant_id=a, site_id=site)
        d = Door(id=uuid.uuid4(), tenant_id=a, site_id=site, controller_id=c.id, controller_door="door1", name=f"{name} door")
        db.add_all([c, d])
        out[name] = (c.id, d.id)
    pending = Controller(id=uuid.uuid4(), key_id="pendingkey000000", public_key=b"p" * 32, claim_code="ABCD-EFGH")
    s = Schedule(id=uuid.uuid4(), tenant_id=a, site_id=a1, name="Hours", windows=WINDOWS)
    g = AccessGroup(id=uuid.uuid4(), tenant_id=a, site_id=a1, name="Staff", rules=[])
    h = Cardholder(id=uuid.uuid4(), tenant_id=a, name="Alice")
    k = Credential(id=uuid.uuid4(), tenant_id=a, cardholder_id=h.id, kind="pin", value_sealed="sealed", fingerprint="f" * 64)
    db.add_all([pending, s, g, h, k, CardholderGroup(cardholder_id=h.id, group_id=g.id, tenant_id=a, site_id=a1)])
    db.add(DoorEvent(controller_id=out["annex"][0], seq=1, tenant_id=a, site_id=a2, occurred_at=datetime.now(timezone.utc), topic="t"))
    db.add(LinkCommand(id="cmd_x", tenant_id=a, site_id=a2, controller_id=out["annex"][0], kind="access", door="door1",
                       expires_at=datetime.now(timezone.utc) + timedelta(seconds=15)))
    db.commit()
    out.update(schedule=s.id, group=g.id, holder=h.id, credential=k.id, pending=pending.id)
    return out


def count(s, model):
    return len(s.execute(select(model)).scalars().all())


def test_pending_controllers_are_invisible_to_everyone_but_the_system(world, data):
    with as_person(world.pid("a-owner")) as s:
        assert {c.id for c in s.execute(select(Controller)).scalars()} == {data["main"][0], data["annex"][0]}
    with as_person(world.pid("staff"), platform_admin=True) as s:
        assert count(s, Controller) == 0


def test_site_limited_people_see_only_their_sites(world, data):
    with as_person(world.pid("a-viewer-s2")) as s:
        assert [d.name for d in s.execute(select(Door)).scalars()] == ["annex door"]
        assert count(s, Schedule) == 0 and count(s, DoorEvent) == 1 and count(s, LinkCommand) == 1 and count(s, Controller) == 1
    with as_person(world.pid("a-admin-s1")) as s:
        assert [d.name for d in s.execute(select(Door)).scalars()] == ["main door"] and count(s, DoorEvent) == 0
    with as_person(world.pid("b-owner")) as s:
        for model in (Door, Schedule, AccessGroup, Cardholder, Credential, Controller, DoorEvent, LinkCommand, CardholderGroup):
            assert count(s, model) == 0, model.__name__


def test_credentials_are_for_admins_only_and_cardholders_for_operators_up(world, data):
    with as_person(world.pid("a-op")) as s:
        assert count(s, Cardholder) == 1 and count(s, Credential) == 0
    with as_person(world.pid("a-viewer")) as s:
        assert count(s, Cardholder) == 0 and count(s, CardholderGroup) == 0
    with as_person(world.pid("a-admin-s1")) as s:
        assert count(s, Credential) == 1


def test_configuration_is_written_only_by_admins_at_their_sites(world, data):
    a, a1, a2 = uuid.UUID(world.a), uuid.UUID(world.a1), uuid.UUID(world.a2)
    with as_person(world.pid("a-admin-s1")) as s:
        s.add(Schedule(id=uuid.uuid4(), tenant_id=a, site_id=a1, name="ok", windows=WINDOWS))
        s.commit()
    for who, site in (("a-admin-s1", a2), ("a-op", a1), ("b-owner", a1)):
        with as_person(world.pid(who)) as s:
            s.add(Schedule(id=uuid.uuid4(), tenant_id=a, site_id=site, name="no", windows=WINDOWS))
            with pytest.raises((ProgrammingError, DBAPIError)):
                s.commit()
    with as_person(world.pid("a-admin-s1")) as s:
        # An update that would move a door to another site is refused; one of another site's doors matches nothing.
        with pytest.raises((ProgrammingError, DBAPIError)):
            s.execute(update(Door).where(Door.id == data["main"][1]).values(site_id=a2))
            s.commit()
        s.rollback()
        assert s.execute(update(Door).where(Door.id == data["annex"][1]).values(name="x")).rowcount == 0


def test_group_memberships_are_given_only_at_the_admins_sites(world, data, db):
    a, a2 = uuid.UUID(world.a), uuid.UUID(world.a2)
    other = AccessGroup(id=uuid.uuid4(), tenant_id=a, site_id=a2, name="Annex", rules=[])
    db.add(other)
    db.commit()
    with as_person(world.pid("a-admin-s1")) as s:
        s.add(CardholderGroup(cardholder_id=data["holder"], group_id=other.id, tenant_id=a, site_id=a2))
        with pytest.raises((ProgrammingError, DBAPIError)):
            s.commit()


def test_commands_only_by_operators_at_their_sites_in_their_own_name(world, data):
    a, a2 = uuid.UUID(world.a), uuid.UUID(world.a2)
    cid = data["annex"][0]

    def cmd(who, actor):
        with as_person(world.pid(who)) as s:
            s.execute(insert(LinkCommand).values(id=uuid.uuid4().hex[:20], tenant_id=a, site_id=a2, controller_id=cid, kind="access",
                                                 door="door1", actor_person_id=actor,
                                                 expires_at=datetime.now(timezone.utc) + timedelta(seconds=15)))
            s.commit()

    cmd("a-op", world.pid("a-op"))
    for who, actor in (("a-op", world.pid("a-owner")), ("a-viewer", world.pid("a-viewer")), ("a-admin-s1", world.pid("a-admin-s1"))):
        with pytest.raises((ProgrammingError, DBAPIError)):
            cmd(who, actor)


def test_the_app_cannot_write_events_or_the_links_bookkeeping(world, data):
    with as_person(world.pid("a-owner")) as s:
        with pytest.raises((ProgrammingError, DBAPIError)):
            s.execute(update(Controller).where(Controller.id == data["main"][0]).values(applied_version=99))
        s.rollback()
        with pytest.raises((ProgrammingError, DBAPIError)):
            s.execute(text("delete from door_event"))
        s.rollback()
        with pytest.raises((ProgrammingError, DBAPIError)):
            s.execute(update(LinkCommand).values(done=True))


def test_the_audit_log_is_append_only_for_everyone(world, db):
    a = uuid.UUID(world.a)
    with as_person(world.pid("a-owner")) as s:
        s.execute(insert(AuditLog).values(tenant_id=a, actor_person_id=world.pid("a-owner"), action="x"))
        s.commit()
        for stmt in ("update audit_log set action = 'y'", "delete from audit_log"):
            with pytest.raises((ProgrammingError, DBAPIError)):
                s.execute(text(stmt))
            s.rollback()
    for stmt in ("update audit_log set action = 'y'", "delete from audit_log"):
        with pytest.raises((ProgrammingError, DBAPIError)):
            db.execute(text(stmt))
        db.rollback()

"""The demo organization (docs/DEMO.md): seed and remove, run twice; refused without the directory's flag; no mail at all; the simulated mark for
staff only; the viewer linked only when asked; the history kept 45 days."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import sessionmaker

from app import demo, mail, notify
from app.db import SystemSession, owner_engine
from app.demo import keep
from app.demo import seed as demo_seed
from app.link.pgstore import PgStore
from app.link.protocol import Inventory, InventoryDoor
from app.models import (Access, AuditLog, Cardholder, Commissioning, Controller, DoorEvent, Intercom, Lockdown, Person, SettingsVersion, Site,
                        Tenant)
from tests.db.conftest import auth, pull

NOW = datetime(2026, 11, 16, 15, 0, tzinfo=timezone.utc)                 # a Monday, 10:00 in Pittsburgh


def owner_session():
    return sessionmaker(bind=owner_engine, autoflush=False, expire_on_commit=False)()


@pytest.fixture()
def demo_org(fake):
    """The directory's demo organization under its fixed IDs (id1, 2026-11-14), with Connor as owner, a viewer and Photon staff."""
    fake.add_org("Photon Demo", id=str(demo.ORG), slug="demo", demo=True)
    for s, city in zip(demo.SITES, ("Pittsburgh, PA", "Washington, PA", "Wheeling, WV")):
        fake.add_site(str(demo.ORG), s.slug, {"demo-hq": "Headquarters", "demo-warehouse": "Distribution Center", "demo-apartments": "Riverside Apartments"}[s.slug],
                      id=str(s.id), address=city)
    owner = fake.add_person("d-owner", name="Owner")
    fake.grant(owner, str(demo.ORG), "owner")
    viewer = fake.add_person("d-viewer", name="Reviewer")
    fake.grant(viewer, str(demo.ORG), "viewer")
    fake.add_person("d-staff", name="Staff", platform_admin=True)
    other = fake.add_org("Cedar Works")
    fake.add_site(other, "cw-main", "Main office")
    fake.grant(fake.add_person("c-owner", name="Cedar Owner"), other, "owner")
    assert pull(fake).ok
    return type("Demo", (), {"other": uuid.UUID(other), "fake": fake})()


class Simulators:
    """What the demo's entry-links do, enough for the seed: say hello with a claim code, report their doors once claimed, apply settings."""

    def __init__(self) -> None:
        self.store = PgStore(SystemSession)
        self.round = 0

    def hello(self) -> Dict[str, str]:
        self.round += 1
        codes = {}
        for n, key in enumerate(demo.CONTROLLERS, start=1):
            code = f"D{self.round}{n:02d}-{n:04d}"
            self.store.hello(f"k{self.round}-{key}"[:16], b"pk", code, {"model": demo.CONTROLLERS[key].model}, datetime.now(timezone.utc))
            codes[key] = code
        return codes

    def sleep(self, _s: float) -> None:
        with SystemSession() as db:
            for c in db.execute(select(Controller).where(Controller.tenant_id == demo.ORG)).scalars():
                spec = next(s for s in demo.CONTROLLERS.values() if s.name == c.name)
                if not c.inventory:
                    mac = f"0250de0000{list(demo.CONTROLLERS).index(spec.key):02d}"
                    self.store.set_inventory(str(c.id), Inventory(doors=[InventoryDoor(token=f"Axis-{mac}:door{n}", access_points=[f"Axis-{mac}:ap{n}in"])
                                                                      for n in range(1, spec.doors + 1)]))
                latest = db.execute(select(func.max(SettingsVersion.version)).where(SettingsVersion.controller_id == c.id)).scalar() or 0
                if latest and c.applied_version != latest:
                    self.store.set_applied(str(c.id), latest, "")


def run_seed(sims: Simulators, **kw) -> dict:
    with owner_session() as db:
        return demo_seed.seed(db, sims.hello(), NOW, sleep=sims.sleep, store=sims.store, timeout_s=30, **kw)


def counts() -> Dict[str, int]:
    with owner_session() as db:
        return demo_seed.summary(db)


# 134 people (130 cards, 7 PINs) and the two visitors' passes (each a cardholder with a card and a PIN).
EXPECTED = {"controller": 6, "door": 11, "cardholder": 136, "credential": 141, "intercom": 2, "commissioning": 11, "visitor_pass": 2, "door_event": 0}


def test_seed_sets_the_demo_up_and_a_second_seed_gives_the_same(client, demo_org):
    sims = Simulators()
    roster = run_seed(sims)
    assert counts() == EXPECTED
    assert [s["slug"] for s in roster["sites"]] == ["demo-hq", "demo-warehouse", "demo-apartments"]
    hq = roster["sites"][0]
    assert hq["doors"]["main_entrance"]["name"] == "Main entrance" and hq["controllers"]["hq-lobby"]["local_port"] == 18701
    assert all(p["card"] and len(p["card"]) == 8 for p in hq["people"])                       # 26 bits as the reader's hex (padded)
    assert "2026-11-26" in hq["holidays"]                                                     # Thanksgiving, from the template
    [front] = hq["intercoms"]
    # The intercom's settings file holds the web relay on the simulators' loopback, to its controller's endpoint.
    cfg = client.get(f"{front['provision_path']}{front['mac']}.cfg")
    assert cfg.status_code == 200 and "127.0.0.1:18701/v1/relay" in cfg.text
    with owner_session() as db:
        assert all(c.simulated for c in db.execute(select(Controller).where(Controller.tenant_id == demo.ORG)).scalars())
        assert all(i.simulated for i in db.execute(select(Intercom)).scalars())
        wv = db.execute(select(Commissioning).where(Commissioning.site_id == demo.APARTMENTS)).scalars().all()
        assert len(wv) == 4 and all(c.license_text.startswith("WV") and "DEMO-0001" in c.license_text for c in wv)
        assert {a.actor_label for a in db.execute(select(AuditLog).where(AuditLog.tenant_id == demo.ORG)).scalars()} == {"Demo seed"}
        first = {c.id for c in db.execute(select(Controller)).scalars()}
    # Again: the earlier demo goes first, the simulators come back with new codes, the result is the same.
    run_seed(sims)
    assert counts() == EXPECTED
    with owner_session() as db:
        assert not first & {c.id for c in db.execute(select(Controller)).scalars()}


def test_the_simulated_mark_is_for_staff_only(client, demo_org):
    run_seed(Simulators())
    for who, sees in (("d-staff", True), ("d-owner", False)):
        if who == "d-staff":
            demo_org.fake.grant(next(p for p, d in demo_org.fake.people.items() if d["sub"] == "d-staff"), str(demo.ORG), "admin", source="partner")
            assert pull(demo_org.fake).ok
        rows = client.get(f"/tenants/{demo.ORG}/controllers", headers=auth(who)).json()
        assert len(rows) == 6 and all(("simulated" in r) is sees for r in rows), who
        icom = client.get(f"/tenants/{demo.ORG}/sites/{demo.HQ}/intercoms", headers=auth(who)).json()
        assert [r.get("simulated") for r in icom] == ([True] if sees else [None])


def test_no_one_opens_a_demo_door_from_the_app(client, demo_org):
    """The operator (2026-11-14): the demo's viewer opens no doors; no cardholder is linked to anyone."""
    run_seed(Simulators())
    assert client.get(f"/tenants/{demo.ORG}/my/doors", headers=auth("d-viewer")).json() == {"linked": False, "doors": []}
    with owner_session() as db:
        assert db.execute(select(func.count()).select_from(Cardholder).where(Cardholder.person_id.is_not(None))).scalar() == 0


def test_refused_without_the_flag_and_remove_takes_only_the_demo(client, demo_org, fake):
    run_seed(Simulators())
    with owner_session() as db:
        other_before = db.execute(select(func.count()).select_from(Site).where(Site.tenant_id == demo_org.other)).scalar()
        removed = demo_seed.remove(db)
        assert removed["cardholder"] == 136 and removed["controller"] == 6 and removed["audit_log"] > 100
        assert demo_seed.summary(db) == {k: 0 for k in EXPECTED}
        # The directory's copies stay: the organization, its sites, who has access.
        assert db.get(Tenant, demo.ORG) is not None and db.get(Site, demo.HQ) is not None
        assert db.execute(select(func.count()).select_from(Access).where(Access.tenant_id == demo.ORG)).scalar() == 2
        assert db.execute(select(func.count()).select_from(Site).where(Site.tenant_id == demo_org.other)).scalar() == other_before
    fake.ref.put("organization", str(demo.ORG), {**fake.orgs[str(demo.ORG)], "demo": False})     # the directory takes the flag off
    assert pull(fake).ok
    with owner_session() as db:
        with pytest.raises(demo_seed.SeedError, match="not marked demo"):
            demo_seed.seed(db, {}, NOW)
        with pytest.raises(demo_seed.SeedError, match="not marked demo"):
            demo_seed.remove(db)
    with owner_session() as db:
        with pytest.raises(demo_seed.SeedError, match="has not sent"):
            db.execute(text("DELETE FROM tenant WHERE id = :t"), {"t": demo.ORG})
            demo_seed.check(db)


def test_the_directory_flag_reaches_the_tenant(demo_org):
    with SystemSession() as db:
        assert db.get(Tenant, demo.ORG).demo is True and db.get(Tenant, demo_org.other).demo is False


def test_missing_sites_or_claims_are_refused(demo_org):
    with owner_session() as db:
        with pytest.raises(demo_seed.SeedError, match="no claim code for"):
            demo_seed.seed(db, {"hq-lobby": "AAAA-1111"}, NOW)
        db.execute(text("UPDATE site SET status = 'removed' WHERE id = :s"), {"s": demo.WAREHOUSE})
        db.commit()
        with pytest.raises(demo_seed.SeedError, match="site demo-warehouse"):
            demo_seed.check(db)
        db.execute(text("UPDATE tenant SET status = 'suspended' WHERE id = :t"), {"t": demo.ORG})
        db.commit()
        with pytest.raises(demo_seed.SeedError, match="is suspended"):
            demo_seed.check(db)


def test_a_simulator_that_never_reports_times_the_seed_out(demo_org):
    sims = Simulators()
    with owner_session() as db, pytest.raises(demo_seed.SeedError, match="inventory"):
        demo_seed.seed(db, sims.hello(), NOW, sleep=lambda s: None, store=sims.store, timeout_s=0)


def test_no_mail_ever_for_the_demo(client, demo_org):
    sent: List[str] = []

    def send(to: str, subject: str, body: str) -> str:
        sent.append(to)
        return "id"
    run_seed(Simulators())
    # A lockdown at the demo's hq: its owner would be told; the demo is not mailed, and the notice counts as handled.
    with SystemSession() as db:
        db.add(Lockdown(id=uuid.uuid4(), tenant_id=demo.ORG, site_id=demo.HQ, whole_site=True, door_ids=[], reason="Drill",
                        started_at=datetime.now(timezone.utc), started_by_label="Owner"))
        db.commit()
        assert notify.notify_lockdowns(db, send, datetime.now(timezone.utc)) == 1
        assert sent == []
        assert mail.for_tenant(db, demo_org.other, send) is send                 # anyone else's mail goes out as before
        assert mail.for_tenant(db, demo.ORG, send)("a@example.com", "s", "b") is None
    # A visitor's pass with an address: made, not mailed.
    g = client.get(f"/tenants/{demo.ORG}/sites/{demo.HQ}/visitor-groups", headers=auth("d-owner")).json()[0]["id"]
    from app.routes import passes as passes_route
    client.app.dependency_overrides[passes_route.get_mailer] = lambda: send
    now = datetime.now(timezone.utc)
    r = client.post(f"/tenants/{demo.ORG}/sites/{demo.HQ}/passes", headers=auth("d-owner"), json={
        "visitor_name": "Vera", "visitor_email": "vera@example.com", "group_id": g, "valid_from": now.isoformat(),
        "valid_to": (now + timedelta(hours=2)).isoformat()})
    assert r.status_code == 201 and r.json()["emailed"] is False and sent == []


def test_the_demo_keeps_45_days_of_events(demo_org):
    now = datetime.now(timezone.utc)
    with SystemSession() as db:
        for tenant in (demo.ORG, demo_org.other):
            for n, age in enumerate((1, 44, 46, 90)):
                db.add(DoorEvent(controller_id=uuid.UUID(int=n + (0 if tenant == demo.ORG else 100)), seq=1, tenant_id=tenant, site_id=demo.HQ,
                                 occurred_at=now - timedelta(days=age), topic="x", source={}, data={}))
        db.commit()
        assert keep.trim(db, now) == 2
        left = db.execute(select(DoorEvent.tenant_id, func.count()).group_by(DoorEvent.tenant_id)).all()
        assert dict(left) == {demo.ORG: 2, demo_org.other: 4}


def test_the_command_line(demo_org, capsys, monkeypatch):
    import io
    from app.demo.__main__ import main
    assert main(["status"]) == 0 and '"controller": 0' in capsys.readouterr().out
    monkeypatch.setattr("sys.stdin", io.StringIO('{"hq-lobby": "AAAA-1111"}'))
    assert main(["seed", "--timeout", "1"]) == 1 and "no claim code for" in capsys.readouterr().err
    assert main(["remove"]) == 0 and "demo removed" in capsys.readouterr().err

"""Licenses and commissioning on Postgres: who records a partner's licenses, who sees them, signing and voiding a door's record, and the state rules."""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import ProgrammingError

from app.models import AuditLog, Commissioning, License
from app.routes import commissioning as route
from tests.db.conftest import as_person, auth
from tests.db.test_routes import setup_site

SP_LV = {"owner": "partner", "state": "WV", "kind": "wv_sp_lv", "holder": "Ann Lee", "number": "SPLV-12345", "expires_on": "2027-06-30"}
RECORD = {"jurisdiction": "WV", "lock_type": "strike_fail_secure", "failure_state": "fail_secure", "egress": "Lever, free egress",
          "special_locking": "none", "fire_release": "tested", "fire_tested_on": "2026-11-10", "fire_tested_by": "Bo Fire", "rex_checked": True,
          "contact_checked": True, "ahj_reference": "Permit 2026-0412", "installer": "Ann Lee"}


@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setattr(route, "_today", lambda: date(2026, 11, 14))


def lic(client, world, who="tech", org=None, **over):
    return client.post(f"/tenants/{org or world.a}/licenses", headers=auth(who), json={**SP_LV, **over})


def test_a_partners_licenses_are_its_staffs_to_record_and_its_customers_to_see(client, world, db):
    r = lic(client, world)
    assert r.status_code == 201, r.text
    assert r.json()["text"] == "WV Specialty Low-Voltage Electrician (SP-LV), State Fire Marshal SPLV-12345, Ann Lee, to 2027-06-30"
    assert lic(client, world, who="a-admin").status_code == 403                               # the customer's admin is not the partner's staff
    own = lic(client, world, who="a-admin", owner="organization", state="OH", kind="oh_ocilb_electrical", holder="Cedar Works Facilities")
    assert own.status_code == 201
    assert lic(client, world, kind="pa_hicpa").status_code == 422                             # not a WV kind
    # Every customer of the partner sees the partner's license; each sees only its own organization licenses.
    a = client.get(f"/tenants/{world.a}/licenses", headers=auth("a-viewer")).json()
    assert sorted(x["holder"] for x in a["licenses"]) == ["Ann Lee", "Cedar Works Facilities"] and a["can_manage_partner"] is False
    b = client.get(f"/tenants/{world.b}/licenses", headers=auth("b-owner")).json()
    assert [x["holder"] for x in b["licenses"]] == ["Ann Lee"]
    assert client.get(f"/tenants/{world.a}/licenses", headers=auth("tech")).json()["can_manage_partner"] is True
    # Changing and removing: the partner's by its staff only; removed ones are kept.
    pid = r.json()["id"]
    assert client.patch(f"/tenants/{world.a}/licenses/{pid}", headers=auth("a-admin"), json={"number": "X"}).status_code == 403
    changed = client.patch(f"/tenants/{world.a}/licenses/{pid}", headers=auth("tech"), json={"expires_on": "2026-12-01"}).json()
    assert changed["expiring"] is True and changed["expired"] is False
    assert client.patch(f"/tenants/{world.a}/licenses/{pid}", headers=auth("tech"), json={"holder": None}).status_code == 422
    assert client.delete(f"/tenants/{world.a}/licenses/{own.json()['id']}", headers=auth("a-admin")).status_code == 204
    assert client.delete(f"/tenants/{world.a}/licenses/{own.json()['id']}", headers=auth("a-admin")).status_code == 204   # already gone: fine
    assert [x["holder"] for x in client.get(f"/tenants/{world.a}/licenses", headers=auth("a-admin")).json()["licenses"]] == ["Ann Lee"]
    assert db.execute(select(License).where(License.removed_at.is_not(None))).scalar_one().holder == "Cedar Works Facilities"
    assert client.get(f"/tenants/{world.a}/licenses", headers=auth("stranger")).status_code == 404


def test_row_level_security_on_licenses(client, world):
    lic(client, world)
    with as_person(world.pid("a-admin")) as s:
        assert len(s.execute(select(License)).scalars().all()) == 1                          # read: the partner serves them
        assert s.execute(text("UPDATE license SET number = 'forged' RETURNING id")).all() == []
    with as_person(world.pid("stranger")) as s:
        assert s.execute(select(License)).scalars().all() == []


def test_signing_a_doors_record_and_needing_it_again(client, world, link, db):
    ids = setup_site(client, world, link, commissioned=False)
    base = f"/tenants/{world.a}/sites/{world.a1}"
    st = client.get(f"{base}/commissioning", headers=auth("a-viewer")).json()
    assert st["jurisdiction"] == "ZZ" and {d["why"] for d in st["doors"]} == {"never"}
    # West Virginia: the installer's SP-LV license is named, current, for WV.
    r = client.post(f"{base}/doors/{ids['front']}/commissioning", headers=auth("a-admin"), json=RECORD)
    assert r.status_code == 422 and "SP-LV" in r.json()["detail"]["detail"]
    sp = lic(client, world).json()
    oh = lic(client, world, state="OH", kind="oh_fire_protection", number="OH-1").json()
    assert "is for OH" in client.post(f"{base}/doors/{ids['front']}/commissioning", headers=auth("a-admin"),
                                      json={**RECORD, "license_id": oh["id"]}).json()["detail"]["detail"]
    assert client.post(f"{base}/doors/{ids['front']}/commissioning", headers=auth("a-op"), json={**RECORD, "license_id": sp["id"]}).status_code == 403
    r = client.post(f"{base}/doors/{ids['front']}/commissioning", headers=auth("tech"), json={**RECORD, "license_id": sp["id"]})
    assert r.status_code == 201, r.text
    door = r.json()
    assert door["in_service"] and door["record"]["signed_by"] == "Partner support" and door["record"]["license"].startswith("WV Specialty")
    # Everyone at the site sees it; its history keeps every record.
    seen = {d["door"]: d["in_service"] for d in client.get(f"{base}/commissioning", headers=auth("a-viewer")).json()["doors"]}
    assert seen == {"Front door": True, "Side door": False}
    # Needing it again: a reason, by an admin; the record stays.
    assert client.post(f"{base}/doors/{ids['front']}/commissioning/void", headers=auth("a-admin"), json={"reason": " "}).status_code == 422
    v = client.post(f"{base}/doors/{ids['front']}/commissioning/void", headers=auth("a-admin"), json={"reason": "New maglock fitted"})
    assert v.status_code == 200 and v.json()["why"] == "voided" and v.json()["record"]["void_reason"] == "New maglock fitted"
    assert client.post(f"{base}/doors/{ids['front']}/commissioning/void", headers=auth("a-admin"), json={"reason": "again"}).status_code == 409
    again = client.post(f"{base}/doors/{ids['front']}/commissioning", headers=auth("a-admin"), json={**RECORD, "license_id": sp["id"],
                        "lock_type": "maglock", "failure_state": "fail_safe", "special_locking": "sensor_release", "reader_ul_verified": True})
    assert again.status_code == 201 and again.json()["in_service"]
    history = client.get(f"{base}/doors/{ids['front']}/commissioning", headers=auth("a-viewer")).json()
    assert [h["lock_type"] for h in history] == ["maglock", "strike_fail_secure"] and history[1]["voided_at"]
    actions = [a.action for a in db.execute(select(AuditLog).order_by(AuditLog.id)).scalars() if a.action.startswith("door.commission")]
    assert actions == ["door.commission", "door.commission_void", "door.commission"]
    assert client.get(f"{base}/doors/{ids['front']}/commissioning", headers=auth("a-viewer-s2")).status_code == 404


def test_an_expired_license_and_a_door_moved_to_another_controller_door(client, world, link, db, monkeypatch):
    ids = setup_site(client, world, link, commissioned=False)
    base = f"/tenants/{world.a}/sites/{world.a1}"
    sp = lic(client, world, expires_on="2026-11-13").json()
    r = client.post(f"{base}/doors/{ids['front']}/commissioning", headers=auth("a-admin"), json={**RECORD, "license_id": sp["id"]})
    assert "expired on 2026-11-13" in r.json()["detail"]["detail"]
    monkeypatch.setattr(route, "_today", lambda: date(2026, 11, 12))
    assert client.post(f"{base}/doors/{ids['front']}/commissioning", headers=auth("a-admin"), json={**RECORD, "license_id": sp["id"]}).status_code == 201
    # Rewired to the controller's other door: the record no longer says anything about where the door is now.
    db.execute(text("UPDATE door SET controller_door = 'door3' WHERE id = :d"), {"d": ids["front"]})
    db.commit()
    front = next(d for d in client.get(f"{base}/commissioning", headers=auth("a-admin")).json()["doors"] if d["door"] == "Front door")
    assert (front["in_service"], front["why"]) == (False, "moved")
    assert client.post(f"{base}/doors/{ids['front']}/commissioning", headers=auth("a-admin"),
                       json={**RECORD, "license_id": "00000000-0000-4000-8000-000000000000"}).status_code == 404
    assert client.get(f"{base}/doors/00000000-0000-4000-8000-000000000000/commissioning", headers=auth("a-admin")).status_code == 404


def test_records_are_never_edited(client, world, link):
    ids = setup_site(client, world, link, commissioned=False)
    sp = lic(client, world).json()
    client.post(f"/tenants/{world.a}/sites/{world.a1}/doors/{ids['front']}/commissioning", headers=auth("a-admin"), json={**RECORD, "license_id": sp["id"]})
    with as_person(world.pid("a-admin")) as s, pytest.raises(ProgrammingError, match="permission denied"):
        s.execute(text("UPDATE commissioning SET installer = 'someone else'"))
    with as_person(world.pid("a-viewer")) as s:
        assert len(s.execute(select(Commissioning)).scalars().all()) == 1
        assert s.execute(text("UPDATE commissioning SET void_reason = 'x' RETURNING id")).all() == []


def test_a_site_with_no_doors_and_the_real_date(client, world):
    st = client.get(f"/tenants/{world.a}/sites/{world.a2}/commissioning", headers=auth("a-admin")).json()
    assert st["doors"] == [] and st["required_license"] == {"WV": "wv_sp_lv"}


def _creds(link, ids):
    return {c["IdData"][0]["Value"] for c in link.store.latest(ids["controller"])[1]["credentials"]}


def test_a_door_not_signed_off_gets_only_the_installer_test_setup_until_it_is(client, world, link, db):
    from tests.db.test_routes import add_holder
    ids = setup_site(client, world, link, commissioned=False)
    base = f"/tenants/{world.a}/sites/{world.a1}"
    test_group = client.post(f"{base}/groups", headers=auth("a-admin"), json={"name": "Installer test", "installer_test": True,
                             "rules": [{"doors": [ids["front"], ids["side"]]}]}).json()
    assert test_group["installer_test"] is True
    add_holder(client, world, ids, name="Alice Smith", number=10213)                                    # a real person, in Staff
    tech = client.post(f"/tenants/{world.a}/cardholders", headers=auth("a-admin"), json={"name": "Ina Installer"}).json()
    client.put(f"/tenants/{world.a}/cardholders/{tech['id']}/groups", headers=auth("a-admin"), json={"group_ids": [test_group["id"]]})
    client.post(f"/tenants/{world.a}/cardholders/{tech['id']}/credentials", headers=auth("a-admin"), json={"kind": "pin", "pin": "9090"})
    assert client.post(f"{base}/publish", headers=auth("a-admin")).status_code == 200
    settings = link.store.latest(ids["controller"])[1]
    assert _creds(link, ids) == {"9090"} and settings["door_schedules"] == []                          # only the installer's PIN; no unlock schedule
    # An admin's draft meanwhile (not published): it must not go out with the sign-off.
    client.post(f"{base}/schedules", headers=auth("a-admin"), json={"name": "Draft hours", "windows": [{"days": ["sa"], "start": "09:00", "end": "12:00"}]})
    sp = lic(client, world).json()
    r = client.post(f"{base}/doors/{ids['front']}/commissioning", headers=auth("a-admin"), json={**RECORD, "license_id": sp["id"]})
    assert r.status_code == 201 and r.json()["settings"] == "updated"
    after = link.store.latest(ids["controller"])[1]
    assert len(_creds(link, ids)) == 2 and after["door_schedules"][0]["token"] == f"pe-d-{ids['front']}"   # Alice's card reaches it now
    assert "Draft hours" not in str(after)
    # Needing it again takes the real settings away again, at once.
    v = client.post(f"{base}/doors/{ids['front']}/commissioning/void", headers=auth("a-admin"), json={"reason": "Lock replaced"})
    assert v.json()["settings"] == "updated" and _creds(link, ids) == {"9090"}


def test_signing_off_a_site_never_published_and_one_whose_settings_no_longer_compile(client, world, link):
    ids = setup_site(client, world, link, commissioned=False)
    base = f"/tenants/{world.a}/sites/{world.a1}"
    sp = lic(client, world).json()
    r = client.post(f"{base}/doors/{ids['front']}/commissioning", headers=auth("a-admin"), json={**RECORD, "license_id": sp["id"]})
    assert r.status_code == 201 and r.json()["settings"] == "not_published"                            # its first publish carries it
    assert client.post(f"{base}/publish", headers=auth("a-admin")).status_code == 200
    from app.link.protocol import Inventory, InventoryDoor
    link.store.set_inventory(ids["controller"], Inventory(doors=[InventoryDoor(token="door1", access_points=["ap1in"])]))   # door2 is gone
    r = client.post(f"{base}/doors/{ids['side']}/commissioning", headers=auth("a-admin"), json={**RECORD, "license_id": sp["id"]})
    assert r.status_code == 201 and r.json()["settings"] == "not_updated" and "door2" in r.json()["settings_problem"]
    assert r.json()["in_service"] is True                                                               # the record stands; the next publish carries it

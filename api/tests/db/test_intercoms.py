"""Intercoms on Postgres (BUILD-GUIDE §5): who may set them up, what is kept secret, and what reaches the controller at publish."""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import ProgrammingError

from app import crypto
from app.models import AuditLog, Intercom
from tests.db.conftest import as_person, auth
from tests.db.test_routes import setup_site

NOW = datetime(2026, 11, 16, 15, 0, tzinfo=timezone.utc)


def add(client, world, ids, who="a-admin", **over):
    body = {"name": "Front door intercom", "door_id": ids["front"], "model": "S532", "mac": "0c:11:05:aa:bb:cc", **over}
    return client.post(f"/tenants/{world.a}/sites/{world.a1}/intercoms", headers=auth(who), json=body)


def test_an_admin_sets_up_an_intercom_and_its_secrets_stay_sealed(client, world, link, db):
    ids = setup_site(client, world, link)
    r = add(client, world, ids, sip_server="vox.example", sip_user="door-101", sip_password="sip-secret")
    assert r.status_code == 201, r.text
    ic = r.json()
    assert ic["mac"] == "0C:11:05:AA:BB:CC" and ic["door"] == "Front door" and ic["sip_password_set"] and ic["relay_target"] == ""
    assert "sip-secret" not in str(ic) and "admin_password" not in ic

    row = db.get(Intercom, uuid.UUID(ic["id"]))
    for sealed in (row.relay_secret_sealed, row.admin_password_sealed, row.provision_token_sealed, row.sip_password_sealed):
        assert crypto.unseal(sealed) and crypto.unseal(sealed) not in sealed
    assert row.provision_token_hash == hashlib.sha256(crypto.unseal(row.provision_token_sealed).encode()).hexdigest()
    assert len(crypto.unseal(row.relay_secret_sealed)) == 24

    # The setup values: what the installer types in once. Seeing them is audited.
    s = client.get(f"/tenants/{world.a}/sites/{world.a1}/intercoms/{ic['id']}/setup", headers=auth("a-admin")).json()
    assert s["provision_url"].endswith(f"/provision/v1/{crypto.unseal(row.provision_token_sealed)}/")
    assert s["unlock_code"] == "#" and s["admin_user"] == "admin" and s["admin_password"] == crypto.unseal(row.admin_password_sealed)
    actions = [a.action for a in db.execute(select(AuditLog).order_by(AuditLog.id)).scalars()]
    assert actions[-2:] == ["intercom.add", "intercom.setup_view"]

    # The same MAC twice is refused; so is a door of another site, a model we do not set up, and a MAC that is not one.
    assert add(client, world, ids, mac="0C-11-05-AA-BB-CC").status_code == 409
    assert add(client, world, ids, door_id=str(uuid.uuid4())).status_code == 422
    assert add(client, world, ids, model="T49", mac="0C1105000001").status_code == 422
    assert add(client, world, ids, mac="0C1105").status_code == 422


def test_only_admins_at_the_site_see_or_touch_intercoms(client, world, link):
    ids = setup_site(client, world, link)
    ic = add(client, world, ids).json()
    base = f"/tenants/{world.a}/sites/{world.a1}/intercoms"
    for who in ("a-op", "a-viewer"):
        assert client.get(base, headers=auth(who)).status_code == 403
        assert client.get(f"{base}/{ic['id']}/setup", headers=auth(who)).status_code == 403
        assert add(client, world, ids, who=who, mac="0C1105000002").status_code == 403
    assert client.get(base, headers=auth("a-viewer-s2")).status_code == 404               # not their site
    assert client.get(f"/tenants/{world.b}/sites/{world.a1}/intercoms", headers=auth("b-owner")).status_code == 404
    assert [i["id"] for i in client.get(base, headers=auth("tech")).json()] == [ic["id"]]   # the partner's technician is an admin

    # Row-level security says the same, whatever the route asks for.
    with as_person(world.pid("a-op")) as s:
        assert s.execute(select(Intercom)).scalars().all() == []
    with as_person(world.pid("b-owner")) as s:
        assert s.execute(text("UPDATE intercom SET name = 'x' RETURNING id")).all() == []
    with as_person(world.pid("a-admin")) as s:
        assert len(s.execute(select(Intercom)).scalars().all()) == 1
    with as_person(world.pid("a-admin")) as s:
        # The fetch bookkeeping is the provisioning server's (the system's), never an admin's.
        with pytest.raises(ProgrammingError, match="permission denied"):
            s.execute(text("UPDATE intercom SET last_fetch_ip = '1.2.3.4'"))


def test_change_and_remove(client, world, link, db):
    ids = setup_site(client, world, link)
    ic = add(client, world, ids, sip_password="one").json()
    base = f"/tenants/{world.a}/sites/{world.a1}/intercoms/{ic['id']}"
    r = client.patch(base, headers=auth("a-admin"), json={"door_id": ids["side"], "relay_address": "10.152.0.20:8742", "sip_password": ""})
    assert r.status_code == 200, r.text
    assert r.json()["door"] == "Side door" and r.json()["relay_target"] == "10.152.0.20:8742" and not r.json()["sip_password_set"]
    assert client.patch(base, headers=auth("a-admin"), json={"name": None}).status_code == 422
    assert client.patch(base, headers=auth("a-admin"), json={"relay_address": "not an address"}).status_code == 422
    # A door with an intercom cannot be removed until the intercom moves or goes.
    client.put(f"/tenants/{world.a}/sites/{world.a1}/groups/{ids['staff']}", headers=auth("a-admin"),
               json={"name": "Staff", "rules": [{"doors": [ids["front"]]}]})
    r = client.delete(f"/tenants/{world.a}/sites/{world.a1}/doors/{ids['side']}", headers=auth("a-admin"))
    assert r.status_code == 409 and "Intercom" in r.json()["detail"]["detail"]
    assert client.delete(base, headers=auth("a-admin")).status_code == 204
    assert client.delete(base, headers=auth("a-admin")).status_code == 404
    assert client.delete(f"/tenants/{world.a}/sites/{world.a1}/doors/{ids['side']}", headers=auth("a-admin")).status_code == 204


def test_the_controller_reports_where_intercoms_reach_it(client, world, link):
    ids = setup_site(client, world, link)
    ic = add(client, world, ids).json()
    link.store.seen(ids["controller"], NOW, {"uptime_s": 5, "local_endpoint": "10.152.0.20:8742"})
    got = client.get(f"/tenants/{world.a}/sites/{world.a1}/intercoms", headers=auth("a-admin")).json()
    assert got[0]["id"] == ic["id"] and got[0]["relay_target"] == "10.152.0.20:8742" and got[0]["relay_address"] == ""


def test_publish_sends_the_controller_only_the_hash_of_each_relay_password(client, world, link, db):
    ids = setup_site(client, world, link)
    ic = add(client, world, ids).json()
    r = client.post(f"/tenants/{world.a}/sites/{world.a1}/publish", headers=auth("a-admin"))
    assert r.status_code == 200, r.text
    settings = link.store.latest(ids["controller"])[1]
    secret = crypto.unseal(db.get(Intercom, uuid.UUID(ic["id"])).relay_secret_sealed)
    assert settings["intercoms"] == [{"id": ic["id"], "name": "Front door intercom", "door": "door1",
                                      "secret_sha256": hashlib.sha256(secret.encode()).hexdigest()}]
    assert secret not in str(settings)


def test_the_intercom_fetches_its_own_settings_and_nothing_else(client, world, link, db):
    from app.routes.provision import provision_throttle
    provision_throttle.hits.clear()
    ids = setup_site(client, world, link)
    ic = add(client, world, ids, sip_server="vox.example", sip_user="door-101", sip_password="sip-secret").json()
    link.store.seen(ids["controller"], NOW, {"local_endpoint": "10.152.0.20:8742"})
    url = client.get(f"/tenants/{world.a}/sites/{world.a1}/intercoms/{ic['id']}/setup", headers=auth("a-admin")).json()["provision_url"]
    path = "/" + url.split("/", 3)[3]                                  # /provision/v1/<token>/

    general = client.get(path + "r000000000532.cfg")
    assert general.status_code == 200 and general.text.startswith("#") and general.headers["cache-control"] == "no-store"
    r = client.get(path + "0c1105aabbcc.cfg")                          # either case
    assert r.status_code == 200, r.text
    row = db.get(Intercom, uuid.UUID(ic["id"]))
    db.refresh(row)
    secret = crypto.unseal(row.relay_secret_sealed)
    assert f"Config.DoorSetting.WEBRELAY.WebRelay_Action_1 = http://10.152.0.20:8742/v1/relay?intercom={ic['id']}&key={secret}" in r.text
    assert "Config.Account1.GENERAL.Pwd = sip-secret" in r.text and f"Config.Autoprovision.GENERAL.Url = {url}" in r.text
    assert row.last_fetch_at is not None and row.last_fetch_ip == "testclient"

    # Another MAC with this token, an unknown token, another file: the same 404.
    for p in (path + "0C1105000001.cfg", "/provision/v1/not-a-token/0C1105AABBCC.cfg", path + "../x", path + "boot.rom",
              "/provision/v1/" + "x" * 65 + "/0C1105AABBCC.cfg"):
        assert client.get(p).status_code == 404, p
    listed = client.get(f"/tenants/{world.a}/sites/{world.a1}/intercoms", headers=auth("a-admin")).json()
    assert listed[0]["last_fetch_at"] is not None


def test_provisioning_is_limited_per_address(client, world, link):
    from app.routes.provision import provision_throttle
    provision_throttle.hits.clear()
    codes = [client.get("/provision/v1/guess/0C1105AABBCC.cfg").status_code for _ in range(31)]
    assert codes[:30] == [404] * 30 and codes[30] == 429
    provision_throttle.hits.clear()

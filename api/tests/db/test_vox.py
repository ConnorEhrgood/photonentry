"""PhotonVox on Postgres (docs/VOX.md): connecting it, door stations on intercoms, their SIP accounts kept current, and who answered a door's call."""
from __future__ import annotations

import json
import pathlib
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import jsonschema
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import ProgrammingError

from app import crypto, vox
from app.db import SystemSession
from app.link.protocol import Event
from app.models import AuditLog, CallMatch, Intercom, VoxLink
from app.routes.integrations import get_vox_fetch
from tests.db.conftest import as_person, auth
from tests.db.test_routes import setup_site

CONTRACT = pathlib.Path(__file__).resolve().parents[3] / "contract" / "vox"
SCHEMAS = {n: json.loads((CONTRACT / f"{n}.schema.json").read_text()) for n in ("door-stations", "door-call")}
TOKEN = "pvx_entry_token_0123456789abcdef"


class FakeVox:
    """PhotonVox's two endpoints as the contract says, for one organization; every answer is checked against the schemas before it is sent."""

    def __init__(self, org: str) -> None:
        self.org, self.down, self.status = org, False, 200
        self.stations = {"ds-1": self.station("ds-1", "Front door", "901", "pw-one-0123456789")}
        self.calls: list = []                 # (station, start, end, answered_by)
        self.asked: list = []

    @staticmethod
    def station(id, name, ext, password):
        return {"id": id, "name": name, "site_id": None, "extension": ext, "updated_at": "2026-11-14T15:00:00Z",
                "sip": {"server": "cedar.pbx.photonind.com", "port": 5061, "transport": "tls", "username": f"{ext}-k3v9", "password": password}}

    def __call__(self, url, token, params):
        self.asked.append((url.rsplit("/", 1)[-1], params))
        if self.down:
            raise httpx.ConnectError("down")
        if token != TOKEN:
            return 401, None
        if self.status != 200:
            return self.status, None
        if url.endswith("/door-stations"):
            body = {"organization_id": self.org, "stations": list(self.stations.values())}
            jsonschema.validate(body, SCHEMAS["door-stations"])
            return 200, body
        if params["station"] not in self.stations:
            return 404, None
        at = datetime.fromisoformat(params["at"])
        call = next(({"id": f"c{n}", "started_at": s.isoformat(), "answered_at": s.isoformat(), "ended_at": e.isoformat() if e else None,
                      "answered_by": who} for n, (st, s, e, who) in enumerate(self.calls)
                     if st == params["station"] and s <= at and (e is None or e >= at - timedelta(seconds=int(params["window_s"])))), None)
        body = {"organization_id": self.org, "station_id": params["station"], "call": call}
        jsonschema.validate(body, SCHEMAS["door-call"])
        return 200, body


@pytest.fixture()
def fake_vox(client, world):
    f = FakeVox(world.a)
    client.app.dependency_overrides[get_vox_fetch] = lambda: f
    yield f
    client.app.dependency_overrides.pop(get_vox_fetch, None)


def connect(client, world, token=TOKEN, who="a-admin"):
    return client.put(f"/tenants/{world.a}/integrations/vox", headers=auth(who), json={"token": token})


def intercom(client, world, ids, **over):
    body = {"name": "Front door intercom", "door_id": ids["front"], "model": "S532", "mac": "0C1105AABBCC", **over}
    return client.post(f"/tenants/{world.a}/sites/{world.a1}/intercoms", headers=auth("a-admin"), json=body)


def test_connecting_checks_the_token_with_photonvox_first(client, world, link, fake_vox, db):
    r = connect(client, world, token="pvx_wrong_token_0123456789abcdef")
    assert r.status_code == 422 and "refused the token" in r.json()["detail"]["detail"]
    fake_vox.org = str(uuid.uuid4())
    r = connect(client, world)
    assert r.status_code == 422 and "another organization" in r.json()["detail"]["detail"]
    fake_vox.org = world.a
    r = connect(client, world)
    assert r.status_code == 200 and r.json()["connected"] and r.json()["token_hint"] == "…cdef"
    assert TOKEN not in str(r.json()) and crypto.unseal(db.get(VoxLink, uuid.UUID(world.a)).token_sealed) == TOKEN
    # The stations, to choose from: never their passwords.
    st = client.get(f"/tenants/{world.a}/integrations/vox/stations", headers=auth("a-admin")).json()
    assert st == [{"id": "ds-1", "name": "Front door", "site_id": None, "extension": "901"}]
    fake_vox.down = True
    r = client.get(f"/tenants/{world.a}/integrations/vox/stations", headers=auth("a-admin"))
    assert r.status_code == 502 and "could not be reached" in r.json()["detail"]["detail"]
    for who in ("a-op", "a-viewer"):
        assert client.get(f"/tenants/{world.a}/integrations/vox", headers=auth(who)).status_code == 403
    assert client.delete(f"/tenants/{world.a}/integrations/vox", headers=auth("a-admin")).status_code == 204
    assert client.delete(f"/tenants/{world.a}/integrations/vox", headers=auth("a-admin")).status_code == 404
    assert client.get(f"/tenants/{world.a}/integrations/vox/stations", headers=auth("a-admin")).status_code == 404
    actions = [a.action for a in db.execute(select(AuditLog).order_by(AuditLog.id)).scalars()]
    assert "vox.connect" in actions and actions[-1] == "vox.disconnect"


def test_an_intercom_takes_its_door_stations_sip_account(client, world, link, fake_vox, db):
    ids = setup_site(client, world, link)
    assert intercom(client, world, ids, vox_station_id="ds-1").json()["detail"]["code"] == "vox_not_connected"
    connect(client, world)
    assert intercom(client, world, ids, vox_station_id="ds-9").json()["detail"]["code"] == "no_such_station"
    r = intercom(client, world, ids, vox_station_id="ds-1", sip_server="typed.example")
    assert r.status_code == 201, r.text
    ic = r.json()
    assert (ic["vox_station_id"], ic["sip_server"], ic["sip_user"], ic["sip_password_set"]) == ("ds-1", "cedar.pbx.photonind.com", "901-k3v9", True)
    row = db.get(Intercom, uuid.UUID(ic["id"]))
    assert crypto.unseal(row.sip_password_sealed) == "pw-one-0123456789"
    base = f"/tenants/{world.a}/sites/{world.a1}/intercoms/{ic['id']}"
    # Let go of the station: the SIP account stays as it is, typed in from now on.
    r = client.patch(base, headers=auth("a-admin"), json={"vox_station_id": ""})
    assert r.json()["vox_station_id"] == "" and r.json()["sip_user"] == "901-k3v9"
    fake_vox.down = True
    r = client.patch(base, headers=auth("a-admin"), json={"vox_station_id": "ds-1"})
    assert r.status_code == 502 and "could not be reached" in r.json()["detail"]["detail"]
    fake_vox.down = False
    assert client.patch(base, headers=auth("a-admin"), json={"vox_station_id": "ds-1"}).json()["vox_station_id"] == "ds-1"


def test_the_worker_keeps_sip_accounts_current_and_says_when_a_station_is_gone(client, world, link, fake_vox):
    ids = setup_site(client, world, link)
    connect(client, world)
    ic = intercom(client, world, ids, vox_station_id="ds-1").json()
    now = datetime.now(timezone.utc)
    fake_vox.stations["ds-1"]["sip"]["password"] = "pw-two-0123456789"       # PhotonVox rotated it
    with SystemSession() as s:
        assert vox.run_all(s, fake_vox, now, sync=True) == (1, 0)
        assert vox.run_all(s, fake_vox, now, sync=True) == (0, 0)
        assert crypto.unseal(s.get(Intercom, uuid.UUID(ic["id"])).sip_password_sealed) == "pw-two-0123456789"
    del fake_vox.stations["ds-1"]
    with SystemSession() as s:
        vox.run_all(s, fake_vox, now, sync=True)
    view = client.get(f"/tenants/{world.a}/integrations/vox", headers=auth("a-admin")).json()
    assert "no longer has the door station of Front door intercom" in view["last_error"] and view["intercoms"] == 1
    fake_vox.down = True
    with SystemSession() as s:
        assert vox.run_all(s, fake_vox, now, sync=True) == (0, 0)
    assert "could not be reached" in client.get(f"/tenants/{world.a}/integrations/vox", headers=auth("a-admin")).json()["last_error"]


def unlock(link, cid, seq, at, intercom_id, result="ok"):
    link.store.add_events(cid, [Event(seq=seq, occurred_at=at, topic=vox.UNLOCK, source={"DoorToken": "door1", "IntercomId": intercom_id},
                                      data={"Result": result}, ref="")], at)


def test_who_answered_the_call_a_door_was_opened_from(client, world, link, fake_vox, db):
    ids = setup_site(client, world, link)
    connect(client, world)
    ic = intercom(client, world, ids, vox_station_id="ds-1").json()
    now = datetime.now(timezone.utc)
    ann = {"extension": "101", "name": "Ann Lee", "person_id": world.people["a-admin"]}
    fake_vox.calls.append(("ds-1", now - timedelta(minutes=5), now - timedelta(minutes=4), ann))
    unlock(link, ids["controller"], 1, now - timedelta(minutes=4, seconds=30), ic["id"])        # during the call
    unlock(link, ids["controller"], 2, now - timedelta(seconds=40), ic["id"])                   # no call in PhotonVox (yet)
    unlock(link, ids["controller"], 3, now - timedelta(seconds=5), ic["id"])                    # too fresh: not asked yet
    unlock(link, ids["controller"], 4, now - timedelta(minutes=3), ic["id"], result="failed")   # the door did not open: nobody to name
    unlock(link, ids["controller"], 5, now - timedelta(minutes=2), str(uuid.uuid4()))           # an intercom PhotonEntry no longer has
    with SystemSession() as s:
        assert vox.run_all(s, fake_vox, now, sync=False) == (0, 3)
        assert vox.run_all(s, fake_vox, now, sync=False) == (0, 0)                             # seq 2 waits; nothing asked twice that is settled
        assert {m.seq: m.state for m in s.execute(select(CallMatch)).scalars()} == {1: "found", 4: "none", 5: "none"}
        assert vox.run_all(s, fake_vox, now + timedelta(minutes=11), sync=False) == (0, 2)      # seq 2 given up on, seq 3 asked
    events = client.get(f"/tenants/{world.a}/sites/{world.a1}/events", headers=auth("a-viewer")).json()
    opened = {e["seq"]: e for e in events if e["topic"] == vox.UNLOCK}
    assert opened[1]["answered_by"] == "Ann Lee (101)" and opened[1]["label"] == "Opened from the intercom"
    assert opened[2]["answered_by"] is None


def test_photonvox_away_leaves_the_calls_for_the_next_round(client, world, link, fake_vox):
    ids = setup_site(client, world, link)
    connect(client, world)
    ic = intercom(client, world, ids, vox_station_id="ds-1").json()
    now = datetime.now(timezone.utc)
    unlock(link, ids["controller"], 1, now - timedelta(minutes=1), ic["id"])
    fake_vox.down = True
    with SystemSession() as s:
        assert vox.run_all(s, fake_vox, now, sync=False) == (0, 0)
        assert s.execute(select(CallMatch)).scalars().all() == []
    fake_vox.down = False
    fake_vox.stations.clear()                                                    # and a station PhotonVox no longer has: nothing to name
    with SystemSession() as s:
        assert vox.run_all(s, fake_vox, now + timedelta(minutes=11), sync=False) == (0, 1)


def test_who_may_see_and_change_it(client, world, link, fake_vox):
    ids = setup_site(client, world, link)
    connect(client, world)
    with as_person(world.pid("a-viewer")) as s:
        assert s.execute(select(VoxLink)).scalars().all() == []                 # the token is admins' only
        assert s.execute(select(CallMatch)).scalars().all() == []
    with as_person(world.pid("a-viewer")) as s, pytest.raises(ProgrammingError, match="permission denied"):
        s.execute(text("INSERT INTO call_match (controller_id, seq, tenant_id, state) VALUES (gen_random_uuid(), 1, gen_random_uuid(), 'found')"))
    with as_person(world.pid("b-owner")) as s:
        assert s.execute(text("DELETE FROM vox_link RETURNING tenant_id")).all() == []
    assert connect(client, world, who="a-op").status_code == 403

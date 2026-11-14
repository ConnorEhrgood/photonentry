"""PhotonEntry against a running development PhotonVox (docs/VOX.md), end to end through PhotonEntry's own API and worker. Skipped unless
VOX_DEV_URL, VOX_DEV_TOKEN_FILE and VOX_DEV_ORG name one (never production): connecting, a door station on an intercom, and the real call behind
a door opened from it, named in the door's events."""
from __future__ import annotations

import os
import pathlib
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app import vox
from app.config import settings
from app.db import SystemSession
from app.link.protocol import Event
from app.models import CallMatch
from tests.db.conftest import auth, pull
from tests.db.test_routes import INVENTORY, hello

URL, TOKEN_FILE, ORG = os.environ.get("VOX_DEV_URL"), os.environ.get("VOX_DEV_TOKEN_FILE"), os.environ.get("VOX_DEV_ORG")
pytestmark = pytest.mark.skipif(not (URL and TOKEN_FILE and ORG), reason="no development PhotonVox named (VOX_DEV_URL, VOX_DEV_TOKEN_FILE, VOX_DEV_ORG)")


def test_the_whole_path_against_the_development_photonvox(client, fake, link, monkeypatch):
    assert "photonind.com" not in URL
    monkeypatch.setattr(settings, "vox_api_url", URL)
    token = pathlib.Path(TOKEN_FILE).read_text().strip()
    org = fake.add_org("PhotonEntry test (dev)", id=ORG)
    site = fake.add_site(org, "entry-dev", "Dev site")
    admin = fake.add_person("dev-admin", "Dev Admin")
    fake.grant(admin, org, "admin")
    assert pull(fake).ok
    h = auth("dev-admin")
    kid = hello(link)
    cid = client.post(f"/tenants/{org}/controllers/claim", json={"code": "abcdefgh", "site_id": site, "name": "Front desk"}, headers=h).json()["id"]
    link.store.set_inventory(link.store.by_key(kid).id, INVENTORY)
    front = client.post(f"/tenants/{org}/sites/{site}/doors", headers=h, json={"controller_id": cid, "controller_door": "door1", "name": "Front door"}).json()
    # Connect with the real token; PhotonVox's stations, to choose from.
    r = client.put(f"/tenants/{org}/integrations/vox", headers=h, json={"token": token})
    assert r.status_code == 200, r.text
    stations = client.get(f"/tenants/{org}/integrations/vox/stations", headers=h).json()
    assert {s["id"] for s in stations} >= {"front", "side"}
    ic = client.post(f"/tenants/{org}/sites/{site}/intercoms", headers=h, json={"name": "Front intercom", "door_id": front["id"], "model": "S532",
                     "mac": "0C1105DE0001", "vox_station_id": "front"}).json()
    assert (ic["sip_server"], ic["sip_user"], ic["sip_outbound_proxy"]) == ("entry.vox.test", "150", "10.10.0.60:5060")
    # The door opened from the real call PhotonVox has from "front" (found by asking back over the last day).
    now = datetime.now(timezone.utc)
    call = next((c for m in (1, 5, 15, 60, 240, 1440) if (c := vox.door_call(vox.http_get, token, uuid.UUID(org), "front",
                                                                                  now - timedelta(minutes=m)))), None)
    assert call is not None and call.answered_by is not None, "PhotonVox has no answered call from 'front' in the last day"
    opened = call.answered_at + timedelta(seconds=2)
    link.store.add_events(cid, [Event(seq=1, occurred_at=opened, topic=vox.UNLOCK, source={"DoorToken": "door1", "IntercomId": ic["id"]},
                                      data={"Result": "ok"}, ref="")], now)
    with SystemSession() as s:
        changed, matched = vox.run_all(s, vox.http_get, now, sync=True)
        assert matched == 1
        m = s.query(CallMatch).one()
        assert (m.state, m.call_id, m.extension) == ("found", call.id, call.answered_by.extension)
    events = client.get(f"/tenants/{org}/sites/{site}/events", headers=auth("dev-admin")).json()
    named = next(e for e in events if e["topic"] == vox.UNLOCK)
    assert named["answered_by"] == f"{call.answered_by.name} ({call.answered_by.extension})"

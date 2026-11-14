"""GET /v1/summary (the suite's home dashboard): the contract, the counts, the cache, who may ask, and the one-route rule for other apps' tokens."""
from __future__ import annotations

import json
import pathlib
from datetime import datetime, timedelta, timezone

import jsonschema

from app import summary
from app.link.protocol import Event
from tests.db.conftest import token_for
from tests.db.test_routes import setup_site

SCHEMA = json.loads((pathlib.Path(__file__).resolve().parents[3] / "contract" / "directory" / "summary.schema.json").read_text())
ACCOUNT = "https://account.photonind.com"


def ask(client, world, sub="a-admin", org=None, **claims):
    org = world.a if org is None else org
    q = f"?organization={org}" if org else ""
    return client.get(f"/v1/summary{q}", headers={"Authorization": f"Bearer {token_for(sub, **claims)}"})


def fresh():
    summary.cache._items.clear()


def test_doors_online_per_organization_and_site(client, world, link):
    fresh()
    ids = setup_site(client, world, link)
    r = ask(client, world)
    assert r.status_code == 200, r.text
    body = r.json()
    jsonschema.validate(body, SCHEMA)
    assert r.headers["cache-control"] == "private, max-age=30"
    assert (body["state"], body["summary"]) == ("ok", "2 of 2 doors online")              # its hello a moment ago
    assert body["sites"] == [{"site_id": world.a1, "state": "ok", "summary": "2 of 2 doors online"}]

    fresh()
    link.store.add_events(ids["controller"], [Event(seq=1, occurred_at=datetime.now(timezone.utc), topic="Door/State/DoorAlarm",
                                                    source={"DoorToken": "door2"}, data={"State": "DoorOpenTooLong"}, ref="t1")],
                          datetime.now(timezone.utc))
    body = ask(client, world).json()
    assert (body["state"], body["summary"]) == ("attention", "2 of 2 doors online · 1 forced or held open")
    jsonschema.validate(body, SCHEMA)

    fresh()
    link.store.seen(ids["controller"], datetime.now(timezone.utc) - timedelta(minutes=10), {"uptime_s": 9})
    body = ask(client, world).json()
    assert (body["state"], body["summary"]) == ("down", "0 of 2 doors online · 1 forced or held open")      # silent for ten minutes

    # Without an organization: every organization the person reaches, added up (the dashboard's app tile).
    fresh()
    across = client.get("/v1/summary", headers={"Authorization": f"Bearer {token_for('tech')}"}).json()
    jsonschema.validate(across, SCHEMA)
    assert across["organization_id"] is None and across["sites"] == [] and across["summary"].startswith("0 of 2")


def test_an_organization_with_no_doors_and_a_viewer_of_one_site(client, world, link):
    fresh()
    assert ask(client, world).json()["summary"] == "No doors yet"
    setup_site(client, world, link)
    fresh()
    assert ask(client, world, "a-admin").json()["summary"] == "2 of 2 doors online"
    # The cache is per scope: a viewer of the annex never gets the whole organization's answer.
    s2 = ask(client, world, "a-viewer-s2").json()
    assert (s2["summary"], s2["sites"]) == ("No doors yet", [])


def test_the_cache_holds_an_answer_for_thirty_seconds():
    clock = [0.0]
    c = summary.Cache(clock=lambda: clock[0])
    made = []
    make = lambda: made.append(1) or {"n": len(made)}      # noqa: E731
    assert c.get("k", make) == {"n": 1} and c.get("k", make) == {"n": 1}
    clock[0] = 29.9
    assert c.get("k", make) == {"n": 1}
    clock[0] = 30.0
    assert c.get("k", make) == {"n": 2} and c.get("other", make) == {"n": 3}
    c._items.update({i: (0.0, {}) for i in range(10_001)})
    clock[0] = 100.0
    c.get("again", make)
    assert len(c._items) == 1                               # stale answers are dropped when there are too many


def test_who_may_ask(client, world, link):
    fresh()
    assert ask(client, world, "b-owner").status_code == 403                              # another customer
    assert ask(client, world, "stranger").status_code == 403
    assert ask(client, world, org="00000000-0000-4000-8000-000000000000").status_code == 403
    assert ask(client, world, "tech").status_code == 200                                 # the partner's technician
    assert client.get(f"/v1/summary?organization={world.a}").status_code == 401


def test_another_apps_token_is_accepted_here_only(client, world):
    fresh()
    # The account app's token: our audience, its own client id.
    assert ask(client, world, client_id="account-app").status_code == 200
    assert client.get("/me", headers={"Authorization": f"Bearer {token_for('a-admin', client_id='account-app')}"}).status_code == 401
    assert client.get("/me", headers={"Authorization": f"Bearer {token_for('a-admin', azp='account-app')}"}).status_code == 401
    assert client.get("/me", headers={"Authorization": f"Bearer {token_for('a-admin', client_id='entry-web')}"}).status_code == 200
    # Without our audience it is no token of ours at all, here too.
    assert ask(client, world, aud="someone-else", client_id="account-app").status_code == 401


def test_cors_for_the_account_app_on_this_route_only(client, world):
    fresh()
    pre = client.options("/v1/summary", headers={"Origin": ACCOUNT, "Access-Control-Request-Method": "GET"})
    assert pre.status_code == 204 and pre.headers["access-control-allow-origin"] == ACCOUNT
    assert pre.headers["access-control-allow-headers"] == "Authorization"
    got = client.get(f"/v1/summary?organization={world.a}", headers={"Origin": ACCOUNT, "Authorization": f"Bearer {token_for('a-admin')}"})
    assert got.status_code == 200 and got.headers["access-control-allow-origin"] == ACCOUNT
    other = client.get(f"/v1/summary?organization={world.a}", headers={"Origin": "https://evil.example", "Authorization": f"Bearer {token_for('a-admin')}"})
    assert "access-control-allow-origin" not in other.headers
    me = client.get("/me", headers={"Origin": ACCOUNT, "Authorization": f"Bearer {token_for('a-admin')}"})
    assert "access-control-allow-origin" not in me.headers

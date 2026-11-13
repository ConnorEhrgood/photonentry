"""PhotonGuard and PhotonConsole, on Postgres: what is sent to Guard and when, and what Console's feed shows, to whom."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select, text

from app import guard, rls
from app.db import SessionLocal, SystemSession
from app.link.protocol import Event
from app.models import Controller, DoorAlarm, GuardCursor, GuardLink
from app.routes.integrations import get_guard_post
from tests.db.conftest import auth
from tests.db.test_routes import add_holder, setup_site

NOW = datetime(2026, 11, 16, 15, 0, tzinfo=timezone.utc)


class FakeGuard:
    """Guard's ingest as PhotonEntry sees it: records what it accepted; can refuse or be unreachable."""

    def __init__(self) -> None:
        self.got: list = []
        self.status = 202
        self.down = False

    def __call__(self, url, token, payload):
        if self.down:
            raise httpx.ConnectError("down")
        if self.status < 300:
            self.got.append((url, token, payload))
        return self.status


def events(link, cid, start, specs):
    link.store.add_events(cid, [Event(seq=start + i, occurred_at=NOW + timedelta(seconds=i), topic=t, source=s, data=d, ref=f"tok-{start + i}")
                                for i, (t, s, d) in enumerate(specs)], NOW)


def connect(client, world, token="guard_ingest_token_0123456789"):
    r = client.put(f"/tenants/{world.a}/integrations/guard", headers=auth("a-admin"), json={"token": token})
    assert r.status_code == 200, r.text
    return r.json()


def forward(fake):
    with SystemSession() as s:
        return guard.forward_all(s, fake, NOW)


def test_door_events_reach_guard_once_in_order(client, world, link, db):
    ids = setup_site(client, world, link)
    holder, _ = add_holder(client, world, ids)
    connect(client, world)
    events(link, ids["controller"], 1, [
        ("AccessControl/AccessGranted/Credential", {"AccessPointToken": "ap1in"}, {"CredentialHolderName": f"pe-u-{holder}"}),
        ("Door/State/DoorMode", {"DoorToken": "door1"}, {"State": "Accessed"}),                         # not for Guard
        ("AccessControl/AccessGranted/Anonymous", {"AccessPointToken": "ap1in"}, {}),                   # the exit button: not for Guard
        ("AccessControl/Denied/Credential", {"AccessPointToken": "ap2in"}, {"Reason": "NotPermittedAtThisTime"}),
        ("AccessControl/AccessGranted/Credential", {"AccessPointToken": "unknown-ap"}, {}),             # no door: not for Guard
    ])
    fake = FakeGuard()
    assert [r.sent for r in forward(fake)] == [2]
    url, token, first = fake.got[0]
    assert url == "https://api.guard.photonind.com/ingest/v1/events" and token == "guard_ingest_token_0123456789"
    assert first["label"] == "Access granted: Alice Smith at Front door" and first["targets"] == {"binding": f"entry-door-{ids['front']}"}
    assert fake.got[1][2]["label"] == "Denied: outside its schedule at Side door"
    assert db.get(GuardCursor, uuid.UUID(ids["controller"])).seq == 5
    assert forward(fake)[0].sent == 0 and len(fake.got) == 2                                              # nothing is sent twice
    view = client.get(f"/tenants/{world.a}/integrations/guard", headers=auth("a-admin")).json()
    assert view["sent"] == 2 and view["last_error"] == "" and view["last_ok_at"]
    assert {b["door"]: b["binding"] for b in view["bindings"]}["Front door"] == f"entry-door-{ids['front']}"


def test_a_refusal_or_an_outage_stops_and_resumes_where_it_stopped(client, world, link, db):
    ids = setup_site(client, world, link)
    connect(client, world)
    grant = ("AccessControl/AccessGranted/Credential", {"AccessPointToken": "ap1in"}, {})
    events(link, ids["controller"], 1, [grant, grant, grant])
    fake = FakeGuard()
    fake.status = 401
    assert forward(fake)[0].stopped == "Guard refused an event (HTTP 401)"
    assert db.get(GuardCursor, uuid.UUID(ids["controller"])).seq == 0
    fake.status, fake.down = 202, True
    assert "could not be reached" in forward(fake)[0].stopped
    assert "could not be reached" in client.get(f"/tenants/{world.a}/integrations/guard", headers=auth("a-admin")).json()["last_error"]
    fake.down = False
    assert forward(fake)[0].sent == 3
    assert [p["dedup_key"].split(":")[-1] for _, _, p in fake.got] == ["tok-1", "tok-2", "tok-3"]


def test_a_forced_door_is_one_alarm_until_it_clears(client, world, link, db):
    ids = setup_site(client, world, link)
    connect(client, world)
    door = {"DoorToken": "door2"}
    events(link, ids["controller"], 1, [("Door/State/DoorAlarm", door, {"State": "DoorForcedOpen"}),
                                        ("Door/State/DoorAlarm", door, {"State": "DoorOpenTooLong"}),
                                        ("Door/State/DoorTamper", door, {"State": "TamperDetected"})])
    fake = FakeGuard()
    forward(fake)
    assert [(p["state"], p["attributes"]["entry_kind"]) for _, _, p in fake.got] == [("started", "forced"), ("started", "tamper")]
    assert {a.kind for a in db.execute(select(DoorAlarm)).scalars()} == {"alarm", "tamper"}
    events(link, ids["controller"], 4, [("Door/State/DoorAlarm", door, {"State": "Normal"}), ("Door/State/DoorTamper", door, {"State": "NotInTamper"})])
    forward(fake)
    ends = [p for _, _, p in fake.got[2:]]
    assert [p["state"] for p in ends] == ["ended", "ended"] and ends[0]["dedup_key"] == fake.got[0][2]["dedup_key"]
    assert db.execute(select(DoorAlarm)).first() is None


def test_paused_or_disconnected_sends_nothing(client, world, link):
    ids = setup_site(client, world, link)
    connect(client, world)
    events(link, ids["controller"], 1, [("AccessControl/AccessGranted/Credential", {"AccessPointToken": "ap1in"}, {})])
    assert client.patch(f"/tenants/{world.a}/integrations/guard", headers=auth("a-admin"), json={"enabled": False}).json()["enabled"] is False
    fake = FakeGuard()
    assert forward(fake) == [] and fake.got == []
    client.patch(f"/tenants/{world.a}/integrations/guard", headers=auth("a-admin"), json={"enabled": True})
    assert forward(fake)[0].sent == 1
    assert client.delete(f"/tenants/{world.a}/integrations/guard", headers=auth("a-admin")).status_code == 204
    assert client.get(f"/tenants/{world.a}/integrations/guard", headers=auth("a-admin")).json()["connected"] is False
    assert client.delete(f"/tenants/{world.a}/integrations/guard", headers=auth("a-admin")).status_code == 404
    assert client.patch(f"/tenants/{world.a}/integrations/guard", headers=auth("a-admin"), json={"enabled": True}).status_code == 404


def test_the_token_is_sealed_and_the_test_says_what_happened(client, world, link, db):
    fake = FakeGuard()
    client.app.dependency_overrides[get_guard_post] = lambda: fake
    assert client.post(f"/tenants/{world.a}/integrations/guard/test", headers=auth("a-admin")).status_code == 404
    connect(client, world, "guard_ingest_token_abcdefghij")
    row = db.get(GuardLink, uuid.UUID(world.a))
    assert "abcdefghij" not in row.token_sealed and row.token_hint == "…ghij"
    r = client.post(f"/tenants/{world.a}/integrations/guard/test", headers=auth("a-admin")).json()
    assert r["ok"] is True and fake.got[0][2]["targets"] == {"binding": "entry-connection-test"}
    fake.status = 401
    assert "refused the token" in client.post(f"/tenants/{world.a}/integrations/guard/test", headers=auth("a-admin")).json()["detail"]
    fake.status = 500
    assert "HTTP 500" in client.post(f"/tenants/{world.a}/integrations/guard/test", headers=auth("a-admin")).json()["detail"]
    fake.down = True
    assert "could not be reached" in client.post(f"/tenants/{world.a}/integrations/guard/test", headers=auth("a-admin")).json()["detail"]
    connect(client, world, "guard_ingest_token_replaced00")                       # pasting a new token replaces the old
    db.expire_all()
    assert db.get(GuardLink, uuid.UUID(world.a)).token_hint == "…ed00"
    assert client.put(f"/tenants/{world.a}/integrations/guard", headers=auth("a-op"), json={"token": "x" * 30}).status_code == 403
    assert client.put(f"/tenants/{world.a}/integrations/guard", headers=auth("a-admin"), json={"token": "has spaces in it 0123456789"}).status_code == 422


def test_console_feed_tokens_and_what_the_feed_shows(client, world, link, db):
    ids = setup_site(client, world, link)
    h = auth("a-admin")
    console = str(uuid.uuid4())
    made = client.post(f"/tenants/{world.a}/integrations/console/tokens", headers=h, json={"name": "Console", "console_tenant_id": console}).json()
    secret = made["token"]
    assert secret.startswith("pent_") and made["feed_url"] == "/integrations/console/v1/doors"
    assert "token" not in client.get(f"/tenants/{world.a}/integrations/console/tokens", headers=h).json()[0]
    # The controller is online; door 2 was forced and is still in alarm; door 1 is locked down; one grant, two denials today.
    link.store.seen(ids["controller"], datetime.now(timezone.utc), {"queued_events": 1500, "uptime_s": 60})
    events(link, ids["controller"], 1, [
        ("Door/State/DoorAlarm", {"DoorToken": "door2"}, {"State": "DoorForcedOpen"}),
        ("Door/State/DoorMode", {"DoorToken": "door1"}, {"State": "LockedDown"}),
        ("Door/State/DoorPhysicalState", {"DoorToken": "door2"}, {"State": "Open"}),
        ("AccessControl/AccessGranted/Credential", {"AccessPointToken": "ap1in"}, {}),
        ("AccessControl/Denied/Credential", {"AccessPointToken": "ap2in"}, {"Reason": "CredentialExpired"}),
        ("AccessControl/Denied/CredentialNotFound/Card", {"AccessPointToken": "ap2in"}, {"Card": "01"}),
    ])
    with SystemSession() as s:
        s.execute(text("update door_event set occurred_at = now()"))
        s.commit()
    r = client.get("/integrations/console/v1/doors", headers={"Authorization": f"Bearer {secret}"})
    assert r.status_code == 200, r.text
    feed = r.json()
    assert feed["organization"] == {"id": world.a, "name": "Cedar Works", "consoleTenantId": console}
    doors = {d["name"]: d for d in feed["doors"]}
    assert doors["Side door"]["alarm"] == "forced" and doors["Side door"]["open"] is True and doors["Side door"]["alertWorst"] == "critical"
    assert doors["Front door"]["lockedDown"] is True and doors["Front door"]["alerts"][0]["code"] == "locked_down" and doors["Front door"]["open"] is None
    assert doors["Front door"]["counts24h"]["granted"] == 1 and doors["Side door"]["counts24h"]["denied"] == 2
    [c] = feed["controllers"]
    assert c["online"] is True and c["queuedEvents"] == 1500 and [a["code"] for a in c["alerts"]] == ["events_backlog"]
    assert feed["totals"] == {"doors": 2, "controllers": 1, "online": 1, "offline": 0, "withAlerts": 3}
    # Revoked, malformed or missing: 401 with WWW-Authenticate, never a redirect.
    tid = made["id"]
    assert client.delete(f"/tenants/{world.a}/integrations/console/tokens/{tid}", headers=h).status_code == 204
    assert client.delete(f"/tenants/{world.a}/integrations/console/tokens/{tid}", headers=h).status_code == 404
    for header in ({"Authorization": f"Bearer {secret}"}, {"Authorization": "Bearer pent_short"}, {}, {"Authorization": "Basic x"}):
        bad = client.get("/integrations/console/v1/doors", headers=header, follow_redirects=False)
        assert bad.status_code == 401 and bad.headers["www-authenticate"] == "Bearer" and "location" not in bad.headers


def test_controller_alerts_in_the_feed(client, world, link, db):
    from app.consolefeed import controller_alerts
    now = datetime.now(timezone.utc)
    c = Controller(state="claimed", last_seen=None, apply_error="", health={})
    assert [a["code"] for a in controller_alerts(c, now)] == ["never_connected"]
    c.last_seen, c.apply_error = now - timedelta(minutes=5), "capacity"
    assert [a["code"] for a in controller_alerts(c, now)] == ["offline", "settings_refused"]
    c.state = "disabled"
    assert [a["code"] for a in controller_alerts(c, now)][0] == "out_of_service"


def test_the_feed_sees_one_organization_whatever_it_asks(client, world, link, db):
    ids = setup_site(client, world, link)
    with SessionLocal() as s:
        rls.as_feed(s, uuid.UUID(world.b))                         # Birch Co's feed asks for everything
        assert s.execute(text("select count(*) from door")).scalar() == 0
        assert s.execute(text("select count(*) from controller")).scalar() == 0
        assert s.execute(text("select count(*) from credential")).scalar() == 0
        assert [str(t) for t in s.execute(text("select id from tenant")).scalars()] == [world.b]
    with SessionLocal() as s:
        rls.as_feed(s, uuid.UUID(world.a))
        assert s.execute(text("select count(*) from door")).scalar() == 2
        assert s.execute(text("select count(*) from cardholder")).scalar() == 0          # people are never in the feed
    assert ids
    # A removed organization's token stops working.
    secret = client.post(f"/tenants/{world.a}/integrations/console/tokens", headers=auth("a-admin"), json={"name": "C"}).json()["token"]
    with SystemSession() as s:
        s.execute(text("update tenant set status = 'removed' where id = :a"), {"a": world.a})
        s.commit()
    assert client.get("/integrations/console/v1/doors", headers={"Authorization": f"Bearer {secret}"}).status_code == 401


def test_events_carry_their_kind(client, world, link):
    ids = setup_site(client, world, link)
    events(link, ids["controller"], 1, [("Door/State/DoorAlarm", {"DoorToken": "door1"}, {"State": "DoorOpenTooLong"})])
    [e] = client.get(f"/tenants/{world.a}/sites/{world.a1}/events", headers=auth("a-op")).json()
    assert (e["kind"], e["label"], e["severity"]) == ("held_open", "Door held open", "critical")


@pytest.mark.parametrize("method,path", [("GET", "guard"), ("PUT", "guard"), ("PATCH", "guard"), ("DELETE", "guard"), ("POST", "guard/test"),
                                         ("GET", "console/tokens"), ("POST", "console/tokens")])
def test_integration_routes_are_admins_own(client, world, method, path):
    body = {"token": "x" * 30} if method == "PUT" else {"enabled": True} if method == "PATCH" else {"name": "x"}
    for who in ("a-op", "b-owner", "stranger"):
        r = client.request(method, f"/tenants/{world.a}/integrations/{path}", headers=auth(who), json=body)
        assert r.status_code in (403, 404), f"{who} {method} {path}: {r.status_code}"


def test_feed_mode_applies_to_a_transaction_already_open(world):
    with SessionLocal() as s:
        s.execute(text("select 1"))                                   # a transaction is open
        rls.as_feed(s, uuid.UUID(world.b))
        assert [str(t) for t in s.execute(text("select id from tenant")).scalars()] == [world.b]


def test_door_index_edges():
    from app.doorindex import DoorIndex, cardholder_id
    from app.models import Door
    c = Controller(id=uuid.uuid4(), inventory={"doors": [{"token": "mapped", "access_points": ["a"]}, {"token": "unmapped", "access_points": ["b"]}]})
    d = Door(id=uuid.uuid4(), controller_id=c.id, controller_door="mapped")
    idx = DoorIndex([d], [c])
    assert idx.door_of(c.id, {"AccessPointToken": "a"}) is d and idx.door_of(c.id, {"AccessPointToken": "b"}) is None
    assert cardholder_id({"CredentialHolderName": "pe-u-not-a-uuid"}) is None and cardholder_id({"CredentialHolderName": "someone"}) is None


def test_the_real_sender_posts_json_with_the_token(monkeypatch):
    seen = {}

    class R:
        status_code = 202

    def fake_post(url, json, headers, timeout, follow_redirects):
        seen.update(url=url, json=json, headers=headers, follow=follow_redirects)
        return R()
    monkeypatch.setattr(httpx, "post", fake_post)
    assert guard.http_post("https://g/ingest/v1/events", "tok", {"a": 1}) == 202
    assert seen == {"url": "https://g/ingest/v1/events", "json": {"a": 1}, "headers": {"Authorization": "Bearer tok"}, "follow": False}


def test_the_feed_shows_held_open_and_tamper_and_skips_what_it_cannot_place(client, world, link):
    ids = setup_site(client, world, link)
    secret = client.post(f"/tenants/{world.a}/integrations/console/tokens", headers=auth("a-admin"), json={"name": "C"}).json()["token"]
    events(link, ids["controller"], 1, [
        ("Door/State/DoorAlarm", {"DoorToken": "door1"}, {"State": "DoorOpenTooLong"}),
        ("Door/State/DoorTamper", {"DoorToken": "door1"}, {"State": "TamperDetected"}),
        ("AccessControl/AccessGranted/Credential", {"AccessPointToken": "nowhere"}, {}),
        ("AccessControl/Denied/Credential", {"AccessPointToken": "ap1in"}, {"Reason": "CredentialExpired"}),
    ])
    with SystemSession() as s:
        s.execute(text("update door_event set occurred_at = now()"))
        s.commit()
    hdr = {"Authorization": f"Bearer {secret}"}
    first = client.get("/integrations/console/v1/doors", headers=hdr).json()
    front = next(d for d in first["doors"] if d["name"] == "Front door")
    assert [a["code"] for a in front["alerts"]] == ["held_open", "tamper"] and front["alarm"] == "held_open"
    assert front["counts24h"] == {"granted": 0, "denied": 1, "forced": 0, "heldOpen": 1}
    assert client.get("/integrations/console/v1/doors", headers=hdr).status_code == 200      # a second poll within a minute: not touched again

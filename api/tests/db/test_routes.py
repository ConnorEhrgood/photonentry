"""The integrator's API on Postgres, through PhotonID tokens and row-level security: a site set up from a claimed controller to a published,
working door, and what each role may do on the way."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from sqlalchemy import select, text

from app import crypto
from app.compiler.wiegand import card_data
from app.document import Card
from app.link import signing
from app.link.protocol import Inventory, InventoryDoor
from app.models import AuditLog, Controller, Credential, SettingsVersion
from tests.db.conftest import auth, commission_site

DEVICE = {"model": "AXIS A1610", "serial": "B8A44F000001", "firmware": "12.6.1", "app_version": "0.1.0"}
INVENTORY = Inventory(doors=[InventoryDoor(token="door1", name="Door 1", access_points=["ap1in", "ap1out"]),
                             InventoryDoor(token="door2", name="Door 2", access_points=["ap2in"])])


def hello(link, code="ABCD-EFGH"):
    """A controller says hello (as entry-link would) and reports its doors once claimed."""
    key = Ed25519PrivateKey.generate()
    pub = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    link.store.hello(signing.key_id(pub), pub, code, DEVICE, datetime.now(timezone.utc))
    return signing.key_id(pub)


def setup_site(client, world, link, who="a-admin", commissioned=True):
    """Claim a controller at site a1, map its two doors, add office hours, a holiday, a staff group; returns the ids."""
    h = auth(who)
    kid = hello(link)
    t, s = world.a, world.a1
    c = client.post(f"/tenants/{t}/controllers/claim", json={"code": "abcdefgh", "site_id": s, "name": "Front desk"}, headers=h)
    assert c.status_code == 201, c.text
    cid = c.json()["id"]
    link.store.set_inventory(link.store.by_key(kid).id, INVENTORY)
    office = client.post(f"/tenants/{t}/sites/{s}/schedules", headers=h, json={
        "name": "Office hours", "windows": [{"days": ["mo", "tu", "we", "th", "fr"], "start": "08:00", "end": "18:00"}]}).json()
    front = client.post(f"/tenants/{t}/sites/{s}/doors", headers=h, json={
        "controller_id": cid, "controller_door": "door1", "name": "Front door", "unlock_schedule_id": office["id"]}).json()
    side = client.post(f"/tenants/{t}/sites/{s}/doors", headers=h, json={"controller_id": cid, "controller_door": "door2", "name": "Side door"}).json()
    client.put(f"/tenants/{t}/sites/{s}/holidays", headers=h, json={"days": [{"day": "2026-12-25", "name": "Christmas"}]})
    staff = client.post(f"/tenants/{t}/sites/{s}/groups", headers=h, json={
        "name": "Staff", "rules": [{"doors": [front["id"], side["id"]], "schedule_id": office["id"]}]}).json()
    if commissioned:
        commission_site(s)                       # signed off, so the customer's real settings reach them (decision 27)
    return {"controller": cid, "kid": kid, "office": office["id"], "front": front["id"], "side": side["id"], "staff": staff["id"]}


def add_holder(client, world, ids, name="Alice Smith", number=10213, who="a-admin"):
    h = auth(who)
    holder = client.post(f"/tenants/{world.a}/cardholders", headers=h, json={"name": name}).json()
    client.put(f"/tenants/{world.a}/cardholders/{holder['id']}/groups", headers=h, json={"group_ids": [ids["staff"]]})
    r = client.post(f"/tenants/{world.a}/cardholders/{holder['id']}/credentials", headers=h,
                    json={"kind": "card", "card": {"format": "h10301", "facility": 7, "number": number}})
    assert r.status_code == 201, r.text
    return holder["id"], r.json()["id"]


def test_me_lists_roles_and_capabilities(client, world):
    me = client.get("/me", headers=auth("tech")).json()
    assert {t["name"]: t["role"] for t in me["tenants"]} == {"Birch Co": "admin", "Cedar Works": "admin"}
    assert all(t["source"] == "partner" for t in me["tenants"])
    viewer = client.get("/me", headers=auth("a-viewer")).json()["tenants"][0]
    assert viewer["capabilities"] == ["entry.events.view", "entry.unlock.own", "entry.view"]
    assert client.get("/me", headers=auth("staff")).json()["is_platform_admin"] is True


def test_the_whole_setup_and_publish(client, world, link, db):
    ids = setup_site(client, world, link)
    holder, cred = add_holder(client, world, ids)
    pin = client.post(f"/tenants/{world.a}/cardholders/{holder}/credentials", headers=auth("a-admin"), json={"kind": "pin", "pin": "4821"}).json()
    r = client.post(f"/tenants/{world.a}/sites/{world.a1}/publish", headers=auth("a-admin"))
    assert r.status_code == 200, r.text
    assert r.json()["controllers"] == [{"controller_id": ids["controller"], "version": 1, "changed": True}]
    settings = link.store.latest(ids["controller"])[1]
    assert sorted(c["token"] for c in settings["credentials"]) == sorted([f"pe-c-{cred}", f"pe-c-{pin['id']}"])
    assert {"Name": "PIN", "Value": "4821"} in [c["IdData"][0] for c in settings["credentials"]]
    assert {"Name": "Card", "Value": card_data(Card(format="h10301", facility=7, number=10213))} in [c["IdData"][0] for c in settings["credentials"]]
    assert settings["doors"][0]["DoorScheduleConfiguration"] == f"pe-d-{ids['front']}"
    assert "20261225" in settings["schedules"][0]["ExceptionScheduleDefinition"]
    # Publishing again with nothing changed stores nothing new.
    again = client.post(f"/tenants/{world.a}/sites/{world.a1}/publish", headers=auth("a-admin")).json()
    assert again["controllers"][0] == {"controller_id": ids["controller"], "version": 1, "changed": False}
    view = client.get(f"/tenants/{world.a}/controllers/{ids['controller']}", headers=auth("a-viewer")).json()
    assert view["settings"] == {"latest": 1, "applied": 0, "error": "", "current": False} and view["name"] == "Front desk"
    # The card number is sealed and fingerprinted, never stored in clear.
    row = db.get(Credential, uuid.UUID(cred))
    assert "10213" not in row.value_sealed and crypto.unseal(row.value_sealed) == "10213" and row.hint == "…213"
    actions = [a.action for a in db.execute(select(AuditLog).order_by(AuditLog.id)).scalars()]
    assert actions[:2] == ["controller.claim", "schedule.add"] and actions[-1] == "site.publish"


def test_publish_refuses_a_site_that_does_not_compile(client, world, link):
    ids = setup_site(client, world, link)
    link.store.set_inventory(ids["controller"], Inventory(doors=[InventoryDoor(token="door1", access_points=["ap1in"])]))   # door2 is gone
    r = client.post(f"/tenants/{world.a}/sites/{world.a1}/publish", headers=auth("a-admin"))
    assert r.status_code == 422 and "has no door door2" in r.json()["detail"]["problems"][0]
    assert link.store.latest(ids["controller"]) is None


def test_claim_codes(client, world, link):
    hello(link, "WXYZ-2345")
    h = auth("a-admin")
    assert client.post(f"/tenants/{world.a}/controllers/claim", json={"code": "QQQQ-QQQQ", "site_id": world.a1}, headers=h).status_code == 404
    assert client.post(f"/tenants/{world.a}/controllers/claim", json={"code": "WXYZ2345", "site_id": world.b1}, headers=h).status_code == 404
    # A site-limited admin cannot even see another site (404, so site ids cannot be probed); a viewer may not claim at all.
    assert client.post(f"/tenants/{world.a}/controllers/claim", json={"code": "WXYZ2345", "site_id": world.a2},
                       headers=auth("a-admin-s1")).status_code == 404
    assert client.post(f"/tenants/{world.a}/controllers/claim", json={"code": "WXYZ2345", "site_id": world.a1},
                       headers=auth("a-viewer")).status_code == 403
    assert client.post(f"/tenants/{world.a}/controllers/claim", json={"code": "wxyz-2345", "site_id": world.a1}, headers=h).status_code == 201


def test_controllers_can_be_taken_out_of_service(client, world, link):
    ids = setup_site(client, world, link)
    r = client.patch(f"/tenants/{world.a}/controllers/{ids['controller']}", json={"in_service": False, "name": "Old"}, headers=auth("a-admin"))
    assert r.json()["state"] == "disabled" and r.json()["name"] == "Old"
    assert link.store.get(ids["controller"]).state == "disabled"
    assert client.patch(f"/tenants/{world.a}/controllers/{ids['controller']}", json={"in_service": True},
                        headers=auth("a-op")).status_code == 403
    client.patch(f"/tenants/{world.a}/controllers/{ids['controller']}", json={"in_service": True}, headers=auth("a-admin"))
    assert link.store.get(ids["controller"]).state == "claimed"
    assert [c["id"] for c in client.get(f"/tenants/{world.a}/controllers", headers=auth("a-viewer-s2")).json()] == []


def test_doors_schedules_groups_validation(client, world, link):
    ids = setup_site(client, world, link)
    h, base = auth("a-admin"), f"/tenants/{world.a}/sites/{world.a1}"
    assert client.post(f"{base}/doors", headers=h, json={"controller_id": ids["controller"], "controller_door": "door9", "name": "X"}).status_code == 422
    assert client.post(f"{base}/doors", headers=h, json={"controller_id": ids["controller"], "controller_door": "door1", "name": "X"}).status_code == 409
    assert client.post(f"{base}/groups", headers=h, json={"name": "G", "rules": [{"doors": [str(uuid.uuid4())]}]}).status_code == 422
    assert client.post(f"{base}/groups", headers=h, json={"name": "G", "rules": [{"doors": [ids["side"]], "schedule_id": str(uuid.uuid4())}]}).status_code == 422
    assert client.delete(f"{base}/schedules/{ids['office']}", headers=h).status_code == 409          # in use
    assert client.delete(f"{base}/doors/{ids['side']}", headers=h).status_code == 409                # in a group
    r = client.patch(f"{base}/doors/{ids['front']}", headers=h, json={"access_time_s": 4, "clear_unlock_schedule": True})
    assert r.json()["access_time_s"] == 4 and r.json()["unlock_schedule_id"] is None
    r = client.put(f"{base}/groups/{ids['staff']}", headers=h, json={"name": "Staff", "rules": [{"doors": [ids["front"]]}]})
    assert r.json()["rules"] == [{"doors": [ids["front"]], "schedule_id": None}]
    assert client.delete(f"{base}/doors/{ids['side']}", headers=h).status_code == 204
    put = client.put(f"{base}/schedules/{ids['office']}", headers=h, json={"name": "Hours", "windows": [{"days": ["sa"], "start": "09:00", "end": "12:00"}]})
    assert put.json()["name"] == "Hours"
    assert client.delete(f"{base}/groups/{ids['staff']}", headers=h).status_code == 204
    assert client.delete(f"{base}/schedules/{ids['office']}", headers=h).status_code == 204
    assert client.get(f"{base}/holidays", headers=auth("a-viewer")).json()["days"] == [{"day": "2026-12-25", "name": "Christmas"}]


def test_site_limited_people_see_and_change_only_their_sites(client, world, link):
    ids = setup_site(client, world, link)
    a2 = f"/tenants/{world.a}/sites/{world.a2}"
    assert client.get(f"/tenants/{world.a}/sites/{world.a1}/doors", headers=auth("a-viewer-s2")).status_code == 404
    assert client.get(f"{a2}/doors", headers=auth("a-viewer-s2")).json() == []
    assert client.post(f"{a2}/schedules", headers=auth("a-admin-s1"), json={
        "name": "X", "windows": [{"days": ["mo"], "start": "08:00", "end": "09:00"}]}).status_code == 404
    assert client.post(f"/tenants/{world.a}/sites/{world.a1}/schedules", headers=auth("a-viewer"), json={
        "name": "X", "windows": [{"days": ["mo"], "start": "08:00", "end": "09:00"}]}).status_code == 403
    # A site-limited admin may give a cardholder their own site's groups, never another site's.
    annex = client.post(f"{a2}/groups", headers=auth("a-admin"), json={"name": "Annex", "rules": [{"doors": []}]})
    assert annex.status_code == 422                                     # a rule needs a door
    holder = client.post(f"/tenants/{world.a}/cardholders", headers=auth("a-admin-s1"), json={"name": "Bob"}).json()
    assert client.put(f"/tenants/{world.a}/cardholders/{holder['id']}/groups", headers=auth("a-admin-s1"),
                      json={"group_ids": [ids["staff"]]}).status_code == 200


def test_cardholders_and_credentials(client, world, link):
    ids = setup_site(client, world, link)
    holder, cred = add_holder(client, world, ids)
    h, base = auth("a-admin"), f"/tenants/{world.a}/cardholders"
    other = client.post(base, headers=h, json={"name": "Eve", "ref": "E-1"}).json()
    assert client.post(base, headers=h, json={"name": "Eve 2", "ref": "E-1"}).status_code == 409
    dup = client.post(f"{base}/{other['id']}/credentials", headers=h, json={"kind": "card", "card": {"format": "h10301", "facility": 7, "number": 10213}})
    assert dup.status_code == 409                                         # Alice holds that card
    assert client.post(f"{base}/{other['id']}/credentials", headers=h, json={"kind": "pin", "pin": "12"}).status_code == 422
    pin = client.post(f"{base}/{other['id']}/credentials", headers=h, json={"kind": "pin", "pin": "4821"}).json()
    assert pin["hint"] == "" and "4821" not in str(pin)
    assert [c["id"] for c in client.get(f"{base}/{holder}/credentials", headers=h).json()] == [cred]
    assert client.get(f"{base}/{holder}/credentials", headers=auth("a-op")).status_code == 403   # operators never see credentials
    assert [c["name"] for c in client.get(base, headers=auth("a-op")).json()] == ["Alice Smith", "Eve"]
    assert client.get(base, headers=auth("a-viewer")).status_code == 403
    r = client.patch(f"{base}/{holder}/credentials/{cred}", headers=h, json={"enabled": False})
    assert r.json()["enabled"] is False
    assert client.patch(f"{base}/{holder}", headers=h, json={"suspended": True, "ref": "A-1"}).json()["suspended"] is True
    assert client.patch(f"{base}/{other['id']}", headers=h, json={"ref": "A-1"}).status_code == 409
    assert client.patch(f"{base}/{holder}", headers=h, json={"valid_from": "2027-01-01T00:00:00Z", "valid_to": "2026-01-01T00:00:00Z"}).status_code == 422
    assert client.delete(f"{base}/{holder}/credentials/{cred}", headers=h).status_code == 204
    assert client.delete(f"{base}/{holder}", headers=h).status_code == 204
    assert client.get(f"{base}/{holder}", headers=h).status_code == 404


def test_import(client, world, link):
    ids = setup_site(client, world, link)
    h = auth("a-admin")
    csv = "name,ref,card_format,card_facility,card_number,pin,groups\nAlice,E-1,h10301,7,100,,Staff\nBob,E-2,,,,4444,staff\nCarol,,w34,,123456789,,\n"
    dry = client.post(f"/tenants/{world.a}/cardholders/import", headers=h, json={"site_id": world.a1, "csv": csv})
    assert dry.json() == {"dry_run": True, "rows": 3, "new": 3, "updated": 0, "credentials": 3}
    assert client.get(f"/tenants/{world.a}/cardholders", headers=h).json() == []
    done = client.post(f"/tenants/{world.a}/cardholders/import", headers=h, json={"site_id": world.a1, "csv": csv, "dry_run": False}).json()
    assert done["new"] == 3
    holders = {x["name"]: x for x in client.get(f"/tenants/{world.a}/cardholders", headers=h).json()}
    assert holders["Alice"]["groups"] == [ids["staff"]] and holders["Carol"]["groups"] == []
    again = client.post(f"/tenants/{world.a}/cardholders/import", headers=h,
                        json={"site_id": world.a1, "csv": "name,ref\nAlice Jones,E-1\n", "dry_run": False}).json()
    assert again["updated"] == 1
    bad = client.post(f"/tenants/{world.a}/cardholders/import", headers=h, json={"site_id": world.a1, "csv": (
        "name,ref,card_number,pin,groups\n,X,,,\nDan,E-9,100,,\nEd,E-9,,12,\nFay,,,,Nope\nGus,,abc,,\n")})
    assert bad.status_code == 422
    problems = bad.json()["detail"]["problems"]
    assert [p.split(":")[0] for p in problems] == ["line 2", "line 3", "line 4", "line 5", "line 6"]
    assert client.post(f"/tenants/{world.a}/cardholders/import", headers=h, json={"site_id": world.a1, "csv": "who,what\n"}).status_code == 422


def test_remote_actions_lockdown_events_and_audit(client, world, link, db):
    ids = setup_site(client, world, link)
    r = client.post(f"/tenants/{world.a}/doors/{ids['front']}/action", headers=auth("a-op"), json={"action": "access"})
    assert r.status_code == 202, r.text
    due = link.store.due_commands(ids["controller"], datetime.now(timezone.utc))
    assert [(c.kind, c.door) for c in due] == [("access", "door1")] and due[0].actor == "A Op"
    assert client.post(f"/tenants/{world.a}/doors/{ids['front']}/action", headers=auth("a-viewer"), json={}).status_code == 403
    lock = client.post(f"/tenants/{world.a}/sites/{world.a1}/lockdown", headers=auth("tech"), json={"on": True, "reason": "Drill"}).json()
    assert sorted(c["kind"] for c in lock["commands"]) == ["lockdown", "lockdown"]
    assert client.post(f"/tenants/{world.a}/sites/{world.a1}/lockdown", headers=auth("a-op"),
                       json={"on": True, "reason": "x", "door_ids": [str(uuid.uuid4())]}).status_code == 409   # already locked down: one at a time
    state = client.get(f"/tenants/{world.a}/commands/{r.json()['id']}", headers=auth("a-viewer")).json()
    assert state["delivered"] is True and state["done"] is False
    # Events, as the link stores them, shown with their door and cardholder.
    holder, cred = add_holder(client, world, ids)
    from app.link.protocol import Event
    link.store.add_events(ids["controller"], [
        Event(seq=1, occurred_at=datetime(2026, 11, 16, 15, 0, tzinfo=timezone.utc), topic="AccessControl/AccessGranted/Credential",
              source={"AccessPointToken": "ap1in"}, data={"CredentialToken": f"pe-c-{cred}", "CredentialHolderName": f"pe-u-{holder}"}),
        Event(seq=2, occurred_at=datetime(2026, 11, 16, 15, 1, tzinfo=timezone.utc), topic="Door/State/DoorAlarm",
              source={"DoorToken": "door2"}, data={"State": "DoorForcedOpen"}),
    ], datetime.now(timezone.utc))
    ev = client.get(f"/tenants/{world.a}/sites/{world.a1}/events", headers=auth("a-op")).json()
    assert [(e["door"], e["cardholder"], e["state"]) for e in ev] == [("Side door", None, "DoorForcedOpen"), ("Front door", "Alice Smith", None)]
    viewer = client.get(f"/tenants/{world.a}/sites/{world.a1}/events", headers=auth("a-viewer")).json()
    assert viewer[1]["cardholder"] is None                              # viewers do not see cardholders' names
    assert len(client.get(f"/tenants/{world.a}/sites/{world.a1}/events?before=2026-11-16T15:00:30Z", headers=auth("a-op")).json()) == 1
    trail = client.get(f"/tenants/{world.a}/audit", headers=auth("a-owner")).json()
    assert trail[0]["action"] == "credential.issue" and any(t["action"] == "site.lockdown" and t["actor"] == "Partner support" for t in trail)
    assert client.get(f"/tenants/{world.a}/audit", headers=auth("a-admin")).status_code == 403


def test_commands_need_a_controller_in_service(client, world, link):
    ids = setup_site(client, world, link)
    link.store.disable(ids["controller"])
    assert client.post(f"/tenants/{world.a}/doors/{ids['front']}/action", headers=auth("a-op"), json={}).status_code == 409


ROUTES = [
    ("GET", "/tenants/{t}"), ("GET", "/tenants/{t}/sites"), ("GET", "/tenants/{t}/members"), ("GET", "/tenants/{t}/controllers"),
    ("POST", "/tenants/{t}/controllers/claim"), ("GET", "/tenants/{t}/controllers/{c}"), ("PATCH", "/tenants/{t}/controllers/{c}"),
    ("GET", "/tenants/{t}/sites/{s}/doors"), ("POST", "/tenants/{t}/sites/{s}/doors"), ("PATCH", "/tenants/{t}/sites/{s}/doors/{d}"),
    ("DELETE", "/tenants/{t}/sites/{s}/doors/{d}"), ("GET", "/tenants/{t}/sites/{s}/schedules"), ("POST", "/tenants/{t}/sites/{s}/schedules"),
    ("PUT", "/tenants/{t}/sites/{s}/schedules/{sch}"), ("DELETE", "/tenants/{t}/sites/{s}/schedules/{sch}"),
    ("GET", "/tenants/{t}/sites/{s}/holidays"), ("PUT", "/tenants/{t}/sites/{s}/holidays"), ("GET", "/tenants/{t}/sites/{s}/groups"),
    ("POST", "/tenants/{t}/sites/{s}/groups"), ("PUT", "/tenants/{t}/sites/{s}/groups/{g}"), ("DELETE", "/tenants/{t}/sites/{s}/groups/{g}"),
    ("POST", "/tenants/{t}/sites/{s}/publish"), ("GET", "/tenants/{t}/cardholders"), ("POST", "/tenants/{t}/cardholders"),
    ("GET", "/tenants/{t}/cardholders/{h}"), ("PATCH", "/tenants/{t}/cardholders/{h}"), ("DELETE", "/tenants/{t}/cardholders/{h}"),
    ("PUT", "/tenants/{t}/cardholders/{h}/groups"), ("GET", "/tenants/{t}/cardholders/{h}/credentials"),
    ("POST", "/tenants/{t}/cardholders/{h}/credentials"), ("PATCH", "/tenants/{t}/cardholders/{h}/credentials/{k}"),
    ("DELETE", "/tenants/{t}/cardholders/{h}/credentials/{k}"), ("POST", "/tenants/{t}/cardholders/import"),
    ("POST", "/tenants/{t}/doors/{d}/action"), ("POST", "/tenants/{t}/sites/{s}/lockdown"), ("GET", "/tenants/{t}/commands/{cmd}"),
    ("GET", "/tenants/{t}/sites/{s}/events"), ("GET", "/tenants/{t}/audit"), ("POST", "/tenants/{t}/sites/{s}/templates/office/apply"),
]
BODIES = {
    "/tenants/{t}/controllers/claim": {"code": "ABCD-EFGH", "site_id": "{s}"},
    "/tenants/{t}/sites/{s}/doors": {"controller_id": "{c}", "controller_door": "door1", "name": "X"},
    "/tenants/{t}/sites/{s}/schedules": {"name": "X", "windows": [{"days": ["mo"], "start": "08:00", "end": "09:00"}]},
    "/tenants/{t}/sites/{s}/schedules/{sch}": {"name": "X", "windows": [{"days": ["mo"], "start": "08:00", "end": "09:00"}]},
    "/tenants/{t}/sites/{s}/holidays": {"days": []}, "/tenants/{t}/sites/{s}/groups": {"name": "X", "rules": [{"doors": ["{d}"]}]},
    "/tenants/{t}/sites/{s}/groups/{g}": {"name": "X", "rules": [{"doors": ["{d}"]}]}, "/tenants/{t}/cardholders": {"name": "X"},
    "/tenants/{t}/cardholders/{h}/groups": {"group_ids": []}, "/tenants/{t}/cardholders/{h}/credentials": {"kind": "pin", "pin": "9999"},
    "/tenants/{t}/cardholders/import": {"site_id": "{s}", "csv": "name\nX\n"}, "/tenants/{t}/sites/{s}/lockdown": {"on": True, "reason": "Drill"},
    "/tenants/{t}/doors/{d}/action": {}, "/tenants/{t}/sites/{s}/templates/office/apply": {"doors": {"main_entrance": {"controller_id": "{c}", "controller_door": "door1"}}}, "/tenants/{t}/controllers/{c}": {}, "/tenants/{t}/sites/{s}/doors/{d}": {},
    "/tenants/{t}/cardholders/{h}": {}, "/tenants/{t}/cardholders/{h}/credentials/{k}": {},
}


@pytest.mark.parametrize("method,path", ROUTES)
def test_every_route_is_closed_to_other_organizations_and_strangers(client, world, link, method, path):
    """Cedar Works' ids, asked for by Birch Co's owner (another organization of the same partner) and by a person with no access: nothing is
    found, nothing changes."""
    ids = setup_site(client, world, link)
    holder, cred = add_holder(client, world, ids)
    cmd = client.post(f"/tenants/{world.a}/doors/{ids['front']}/action", headers=auth("a-op"), json={}).json()["id"]
    values = {"t": world.a, "s": world.a1, "c": ids["controller"], "d": ids["front"], "sch": ids["office"], "g": ids["staff"], "h": holder,
              "k": cred, "cmd": cmd}

    def fill(x):
        if isinstance(x, str):
            for k, v in values.items():
                x = x.replace("{" + k + "}", v)
            return x
        if isinstance(x, list):
            return [fill(i) for i in x]
        if isinstance(x, dict):
            return {k: fill(v) for k, v in x.items()}
        return x

    url, body = fill(path), fill(BODIES.get(path))
    for who in ("b-owner", "stranger"):
        r = client.request(method, url, headers=auth(who), json=body)
        assert r.status_code in (403, 404), f"{who} {method} {url}: {r.status_code} {r.text}"
    # And Birch Co's owner, naming Cedar Works' objects under Birch Co's own organization: whatever works there is Birch Co's own business,
    # but nothing of Cedar Works is found, shown or changed.
    values["t"] = world.b
    r = client.request(method, fill(path), headers=auth("b-owner"), json=fill(BODIES.get(path)))
    if r.status_code < 400:
        for secret in (ids["controller"], holder, cred, ids["front"], ids["office"], ids["staff"], world.a1):
            assert secret not in r.text, f"{method} {path} under Birch Co shows a Cedar Works id"
    with link.store.sessions() as s:
        assert s.execute(text("select count(*) from controller where tenant_id = :b"), {"b": world.b}).scalar() == 0
        assert s.execute(select(SettingsVersion)).first() is None
        assert s.execute(select(Controller.name).where(Controller.id == uuid.UUID(ids["controller"]))).scalar() == "Front desk"
        assert s.execute(text("select count(*) from credential where id = :k"), {"k": cred}).scalar() == 1
        assert s.execute(text("select count(*) from door where tenant_id = :a"), {"a": world.a}).scalar() == 2


def test_an_office_from_its_template_to_published_settings(client, world, link):
    h, base = auth("a-admin"), f"/tenants/{world.a}/sites/{world.a1}"
    kid = hello(link)
    cid = client.post(f"/tenants/{world.a}/controllers/claim", json={"code": "ABCD-EFGH", "site_id": world.a1}, headers=h).json()["id"]
    link.store.set_inventory(link.store.by_key(kid).id, INVENTORY)
    assert [t["key"] for t in client.get("/templates", headers=h).json()] == ["office", "school", "multifamily", "gate"]
    body = {"doors": {"main_entrance": {"controller_id": cid, "controller_door": "door1"},
                      "server_room": {"controller_id": cid, "controller_door": "door2", "name": "IT closet"}},
            "options": {"unlock_main": True}, "years": [2026]}
    r = client.post(f"{base}/templates/office/apply", headers=h, json=body)
    assert r.status_code == 201, r.text
    made = r.json()
    assert set(made["doors"]) == {"main_entrance", "server_room"} and set(made["groups"]) == {"staff", "managers", "it", "cleaning"}
    assert made["holidays_added"] == 7
    doors = {d["name"]: d for d in client.get(f"{base}/doors", headers=h).json()}
    assert doors["Main entrance"]["unlock_schedule_id"] == made["schedules"]["business"] and doors["IT closet"]["open_too_long_s"] == 60
    # Applying again: the controller's doors are already doors.
    assert client.post(f"{base}/templates/office/apply", headers=h, json=body).status_code == 409
    # Holidays already in the calendar are not added twice.
    again = client.post(f"/tenants/{world.a}/sites/{world.a2}/templates/office/apply", headers=h, json={**body, "doors": {}})
    assert again.status_code == 422                                     # the main entrance is required
    # Someone in the staff group, published to the controller.
    holder = client.post(f"/tenants/{world.a}/cardholders", headers=h, json={"name": "Ann"}).json()
    client.put(f"/tenants/{world.a}/cardholders/{holder['id']}/groups", headers=h, json={"group_ids": [made["groups"]["staff"], made["groups"]["it"]]})
    client.post(f"/tenants/{world.a}/cardholders/{holder['id']}/credentials", headers=h, json={"kind": "pin", "pin": "2468"})
    commission_site(world.a1)
    pub = client.post(f"{base}/publish", headers=h)
    assert pub.status_code == 200, pub.text
    settings = link.store.latest(cid)[1]
    assert len(settings["access_profiles"]) == 4 and len(settings["credentials"]) == 1
    assert "20260703" in next(s for s in settings["schedules"] if s["Name"] == "Business hours")["ExceptionScheduleDefinition"]


def test_template_errors(client, world, link):
    h, base = auth("a-admin"), f"/tenants/{world.a}/sites/{world.a1}"
    kid = hello(link)
    cid = client.post(f"/tenants/{world.a}/controllers/claim", json={"code": "ABCD-EFGH", "site_id": world.a1}, headers=h).json()["id"]
    link.store.set_inventory(link.store.by_key(kid).id, INVENTORY)
    door = {"main_entrance": {"controller_id": cid, "controller_door": "door1"}}
    assert client.post(f"{base}/templates/office/apply", headers=h, json={"doors": door, "years": [1999]}).status_code == 422
    assert client.post(f"{base}/templates/castle/apply", headers=h, json={"doors": door}).status_code == 422
    assert client.post(f"{base}/templates/office/apply", headers=h,
                       json={"doors": {"main_entrance": {"controller_id": cid, "controller_door": "door9"}}}).status_code == 422
    assert client.post(f"{base}/templates/office/apply", headers=h,
                       json={"doors": {"main_entrance": {"controller_id": str(uuid.uuid4()), "controller_door": "door1"}}}).status_code == 422
    assert client.post(f"{base}/templates/office/apply", headers=auth("a-op"), json={"doors": door}).status_code == 403
    assert client.post(f"{base}/templates/office/apply", headers=h, json={"doors": door}).status_code == 201   # this year and next by default


@pytest.mark.parametrize("key,slots", [
    ("school", {"main_entrance": "door1", "gym_entrance": "door2"}),
    ("multifamily", {"lobby": "door1", "leasing_office": "door2"}),
    ("gate", {"vehicle_gate": "door1", "pedestrian_gate": "door2"}),
])
def test_every_template_applies_and_publishes(client, world, link, key, slots):
    h, base = auth("a-admin"), f"/tenants/{world.a}/sites/{world.a1}"
    kid = hello(link)
    cid = client.post(f"/tenants/{world.a}/controllers/claim", json={"code": "ABCD-EFGH", "site_id": world.a1}, headers=h).json()["id"]
    link.store.set_inventory(link.store.by_key(kid).id, INVENTORY)
    template = next(t for t in client.get("/templates", headers=h).json() if t["key"] == key)
    options = {o["key"]: True for o in template["options"]}
    r = client.post(f"{base}/templates/{key}/apply", headers=h, json={
        "doors": {s: {"controller_id": cid, "controller_door": d} for s, d in slots.items()}, "options": options})
    assert r.status_code == 201, r.text
    made = r.json()
    holder = client.post(f"/tenants/{world.a}/cardholders", headers=h, json={"name": "Someone"}).json()
    client.put(f"/tenants/{world.a}/cardholders/{holder['id']}/groups", headers=h, json={"group_ids": list(made["groups"].values())})
    client.post(f"/tenants/{world.a}/cardholders/{holder['id']}/credentials", headers=h, json={"kind": "pin", "pin": "1357"})
    commission_site(world.a1)
    pub = client.post(f"{base}/publish", headers=h)
    assert pub.status_code == 200, pub.text
    settings = link.store.latest(cid)[1]
    assert len(settings["access_profiles"]) == len(made["groups"]) and len(settings["doors"]) == 2
    assert any(d["DoorScheduleConfiguration"] for d in settings["doors"])          # an option that unlocks a door on a schedule


def test_holiday_lists(client, world):
    got = client.get("/holidays/us-business/2027", headers=auth("a-viewer")).json()
    assert got[0] == {"day": "2027-01-01", "name": "New Year's Day"} and len(got) == 7
    assert len(client.get("/holidays/us-federal/2027", headers=auth("a-viewer")).json()) == 11
    assert client.get("/holidays/us-other/2027", headers=auth("a-viewer")).status_code == 404
    assert client.get("/holidays/us-business/1999", headers=auth("a-viewer")).status_code == 404

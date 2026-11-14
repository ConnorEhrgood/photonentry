"""Visitors' passes on Postgres: who issues them, for which groups, what reaches the controller (and what does not), the visitor's page, revoking."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import ProgrammingError

from app import passes
from app.db import SystemSession
from app.models import AuditLog, Cardholder, Credential, VisitorPass
from app.routes import passes as route
from tests.db.conftest import as_person, auth
from tests.db.test_routes import setup_site


class Mailer:
    def __init__(self):
        self.sent = []

    def __call__(self, to, subject, body):
        self.sent.append((to, subject, body))
        return "msg-1"


@pytest.fixture()
def mailer(client):
    m = Mailer()
    client.app.dependency_overrides[route.get_mailer] = lambda: m
    route.pass_throttle.hits.clear()
    yield m
    client.app.dependency_overrides.pop(route.get_mailer, None)


def visitors_group(client, world, ids):
    r = client.post(f"/tenants/{world.a}/sites/{world.a1}/groups", headers=auth("a-admin"),
                    json={"name": "Visitors", "rules": [{"doors": [ids["front"]], "schedule_id": ids["office"]}], "for_visitors": True})
    assert r.status_code == 201 and r.json()["for_visitors"] is True
    return r.json()["id"]


def publish(client, world):
    r = client.post(f"/tenants/{world.a}/sites/{world.a1}/publish", headers=auth("a-admin"))
    assert r.status_code == 200, r.text


def issue(client, world, group, who="a-op", hours=(0, 8), **over):
    now = datetime.now(timezone.utc)
    body = {"visitor_name": "Vera Visitor", "group_id": group, "valid_from": (now + timedelta(hours=hours[0])).isoformat(),
            "valid_to": (now + timedelta(hours=hours[1])).isoformat(), **over}
    return client.post(f"/tenants/{world.a}/sites/{world.a1}/passes", headers=auth(who), json=body)


def latest(link, ids):
    return link.store.latest(ids["controller"])[1]


def test_an_operator_issues_a_pass_that_reaches_the_controller_without_the_admins_drafts(client, world, link, mailer, db):
    ids = setup_site(client, world, link)
    group = visitors_group(client, world, ids)
    assert issue(client, world, group).json()["detail"]["code"] == "not_published"            # never published: nothing to build on
    publish(client, world)
    version = link.store.latest(ids["controller"])[0]
    # An admin's draft (a new schedule, unpublished) must not go out with a pass.
    client.post(f"/tenants/{world.a}/sites/{world.a1}/schedules", headers=auth("a-admin"),
                json={"name": "Draft hours", "windows": [{"days": ["sa"], "start": "09:00", "end": "12:00"}]})
    client.put(f"/tenants/{world.a}/sites/{world.a1}/groups/{group}", headers=auth("a-admin"),
               json={"name": "Visitors", "rules": [{"doors": [ids["front"], ids["side"]]}], "for_visitors": True})       # also a draft
    r = issue(client, world, group, visitor_email="vera@example.com")
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["state"] == "active" and p["host"] == "A Op" and p["emailed"] is True and len(p["pin"]) == 6 and p["link"].endswith("/pass/" + p["link"].rsplit("/", 1)[1])
    settings = latest(link, ids)
    assert link.store.latest(ids["controller"])[0] == version + 1
    assert {"Name": "PIN", "Value": p["pin"]} in [c["IdData"][0] for c in settings["credentials"]]
    assert "Draft hours" not in str(settings)                                                    # the draft schedule stayed a draft
    visitors = next(x for x in settings["access_profiles"] if x["Name"] == "Visitors")
    assert {ap["AccessPoint"] for ap in visitors["AccessPolicy"]} <= {"ap1in", "ap1out"}          # the published rule (front only), not the draft
    to, subject, body = mailer.sent[0]
    assert to == "vera@example.com" and subject == "Your pass for Main office" and p["link"] in body
    # The visitor's own page: no sign-in, the PIN while it is good.
    token = p["link"].rsplit("/", 1)[1]
    page = client.get(f"/passes/v1/{token}").json()
    assert (page["visitor_name"], page["site"], page["state"], page["pin"]) == ("Vera Visitor", "Main office", "active", p["pin"])
    # The QR code carries the pass's card number (what the controller holds as its 34-bit card).
    assert page["qr"].startswith("data:image/svg+xml") and p["qr"] == page["qr"]
    from app.passes import qr_data_uri
    assert page["qr"] == qr_data_uri(page["card_number"]) and page["card_number"].isdigit()
    import segno
    assert segno.make(page["card_number"], error="m", micro=False).mode == "numeric"
    assert client.get("/passes/v1/not-a-token").status_code == 404 and client.get("/passes/v1/" + "x" * 65).status_code == 404
    # In the operator's list; audited in the operator's name.
    assert [x["visitor_name"] for x in client.get(f"/tenants/{world.a}/sites/{world.a1}/passes", headers=auth("a-op")).json()] == ["Vera Visitor"]
    assert db.execute(select(AuditLog).where(AuditLog.action == "pass.issue")).scalar_one().actor_label == "A Op"


def test_revoking_a_pass_refuses_it_at_once(client, world, link, mailer):
    ids = setup_site(client, world, link)
    group = visitors_group(client, world, ids)
    publish(client, world)
    p = issue(client, world, group).json()
    r = client.post(f"/tenants/{world.a}/sites/{world.a1}/passes/{p['id']}/revoke", headers=auth("a-op"))
    assert r.status_code == 200 and r.json()["state"] == "revoked" and r.json()["revoked_by"] == "A Op"
    pin = next(c for c in latest(link, ids)["credentials"] if c["IdData"][0] == {"Name": "PIN", "Value": p["pin"]})
    assert pin["Enabled"] is False
    page = client.get(f"/passes/v1/{p['link'].rsplit('/', 1)[1]}").json()
    assert page["state"] == "revoked" and page["pin"] is None and page["qr"] is None
    assert client.post(f"/tenants/{world.a}/sites/{world.a1}/passes/{p['id']}/revoke", headers=auth("a-op")).status_code == 200   # again: no change
    assert client.post(f"/tenants/{world.a}/sites/{world.a1}/passes/{uuid.uuid4()}/revoke", headers=auth("a-op")).status_code == 404


def test_what_a_pass_may_be(client, world, link, mailer):
    ids = setup_site(client, world, link)
    group = visitors_group(client, world, ids)
    publish(client, world)
    assert issue(client, world, ids["staff"]).json()["detail"]["code"] == "group_not_for_visitors"   # a group admins did not open to visitors
    assert issue(client, world, str(uuid.uuid4())).json()["detail"]["code"] == "group_not_for_visitors"
    assert issue(client, world, group, hours=(5, 4)).json()["detail"]["detail"] == "A pass ends after it starts"
    assert issue(client, world, group, hours=(-5, -1)).json()["detail"]["detail"] == "That pass would be over already"
    assert issue(client, world, group, hours=(-3, 4)).json()["detail"]["detail"] == "A pass cannot start in the past"
    assert "at most 31 days" in issue(client, world, group, hours=(0, 24 * 32)).json()["detail"]["detail"]
    assert issue(client, world, group, visitor_name="  ").json()["detail"]["detail"] == "Give the visitor's name"
    assert issue(client, world, group, visitor_email="not an address").status_code == 422
    assert issue(client, world, group, who="a-viewer").status_code == 403
    assert issue(client, world, group, hours=(2, 6)).json()["state"] == "upcoming"
    assert [g["name"] for g in client.get(f"/tenants/{world.a}/sites/{world.a1}/visitor-groups", headers=auth("a-op")).json()] == ["Visitors"]
    assert client.get(f"/tenants/{world.a}/sites/{world.a1}/visitor-groups", headers=auth("a-viewer")).status_code == 403


def test_a_pass_that_ended_over_a_day_ago_is_no_longer_sent(client, world, link, mailer, db):
    ids = setup_site(client, world, link)
    group = visitors_group(client, world, ids)
    publish(client, world)
    p = issue(client, world, group).json()
    db.execute(text("UPDATE visitor_pass SET valid_from = now() - interval '3 days', valid_to = now() - interval '2 days' WHERE id = :p"), {"p": p["id"]})
    db.commit()
    publish(client, world)                                                        # an admin's publish drops it
    assert p["pin"] not in str(latest(link, ids))
    with SystemSession() as s:                                                    # so does a pass's
        assert passes.ended_ids(s, uuid.UUID(world.a1), datetime.now(timezone.utc)) == {s.get(VisitorPass, uuid.UUID(p["id"])).cardholder_id}
    q = issue(client, world, group).json()
    assert q["pin"] in str(latest(link, ids)) and p["pin"] not in str(latest(link, ids))
    assert client.get(f"/passes/v1/{p['link'].rsplit('/', 1)[1]}").json()["state"] == "over"


def test_a_site_whose_published_settings_no_longer_compile_and_mail_that_fails(client, world, link, mailer, monkeypatch):
    ids = setup_site(client, world, link)
    group = visitors_group(client, world, ids)
    publish(client, world)
    from app.link.protocol import Inventory, InventoryDoor
    link.store.set_inventory(ids["controller"], Inventory(doors=[InventoryDoor(token="door1", access_points=["ap1in"])]))   # door2 is gone
    r = issue(client, world, group)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "cannot_publish"
    import httpx

    def broken(to, subject, body):
        raise httpx.ConnectError("down")
    client.app.dependency_overrides[route.get_mailer] = lambda: broken
    from tests.db.test_routes import INVENTORY
    link.store.set_inventory(ids["controller"], INVENTORY)
    r = issue(client, world, group, visitor_email="vera@example.com")
    assert r.status_code == 201 and r.json()["emailed"] is False                  # the pass stands; the host shares its link


def test_who_reads_passes_and_that_nobody_writes_them_directly(client, world, link, mailer):
    ids = setup_site(client, world, link)
    group = visitors_group(client, world, ids)
    publish(client, world)
    issue(client, world, group)
    with as_person(world.pid("a-op")) as s:
        assert len(s.execute(select(VisitorPass)).scalars().all()) == 1
    with as_person(world.pid("a-viewer")) as s:
        assert s.execute(select(VisitorPass)).scalars().all() == []
    with as_person(world.pid("a-admin")) as s, pytest.raises(ProgrammingError, match="permission denied"):
        s.execute(text("UPDATE visitor_pass SET valid_to = now() + interval '1 year'"))
    with as_person(world.pid("a-op")) as s:
        assert s.execute(select(Credential)).scalars().all() == []                 # an operator never reads a PIN from the database
        assert [h.name for h in s.execute(select(Cardholder)).scalars()] == ["Vera Visitor"]
    assert client.get(f"/tenants/{world.a}/sites/{world.a1}/passes", headers=auth("a-viewer-s2")).status_code == 404


def test_the_visitor_page_is_limited_per_address(client, mailer):
    codes = [client.get("/passes/v1/guess").status_code for _ in range(31)]
    assert codes[:30] == [404] * 30 and codes[30] == 429


def test_no_free_number_mail_not_configured_another_sites_pass_and_a_revoke_that_cannot_publish(client, world, link, mailer):
    ids = setup_site(client, world, link)
    group = visitors_group(client, world, ids)
    publish(client, world)
    now = datetime.now(timezone.utc)
    from app.models import Site
    with SystemSession() as s:                                     # every number already taken: a clear refusal, not a loop
        site = s.get(Site, uuid.UUID(world.a1))
        passes.issue(s, site=site, group_id=uuid.UUID(group), visitor_name="A", visitor_email="", valid_from=now, valid_to=now + timedelta(hours=1),
                     host_id=world.pid("a-op"), host_label="A Op", actor_source="direct", now=now, rnd=lambda n: 7)
        with pytest.raises(passes.PassError, match="free PIN"):
            passes.issue(s, site=site, group_id=uuid.UUID(group), visitor_name="B", visitor_email="", valid_from=now,
                         valid_to=now + timedelta(hours=1), host_id=world.pid("a-op"), host_label="A Op", actor_source="direct", now=now,
                         rnd=lambda n: 7)
        s.rollback()
    client.app.dependency_overrides[route.get_mailer] = lambda: (lambda to, subject, body: None)       # no mail configured
    p = issue(client, world, group, visitor_email="vera@example.com").json()
    assert p["emailed"] is False
    assert client.post(f"/tenants/{world.a}/sites/{world.a2}/passes/{p['id']}/revoke", headers=auth("a-op")).status_code == 404
    from app.link.protocol import Inventory, InventoryDoor
    link.store.set_inventory(ids["controller"], Inventory(doors=[InventoryDoor(token="door1", access_points=["ap1in"])]))
    r = client.post(f"/tenants/{world.a}/sites/{world.a1}/passes/{p['id']}/revoke", headers=auth("a-op"))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "cannot_publish"
    assert route.get_mailer() is route.mail.send


def test_a_controller_with_no_doors_gets_nothing(client, world, link):
    ids = setup_site(client, world, link)
    from tests.db.test_routes import hello
    hello(link, "WXYZ-2345")
    r = client.post(f"/tenants/{world.a}/controllers/claim", json={"code": "WXYZ2345", "site_id": world.a1, "name": "Spare"}, headers=auth("a-admin"))
    assert r.status_code == 201
    out = client.post(f"/tenants/{world.a}/sites/{world.a1}/publish", headers=auth("a-admin")).json()["controllers"]
    assert [c["controller_id"] for c in out] == [ids["controller"]]

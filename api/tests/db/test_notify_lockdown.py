"""Lockdown notices by email (app/notify.py): to whom, once, from the worker, never late, and what happens when mail fails or is off."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import text

from app import notify
from app.db import SystemSession
from tests.db.conftest import auth
from tests.db.test_routes import setup_site


class Outbox:
    def __init__(self, result="msg"):
        self.sent, self.result, self.fail = [], result, False

    def __call__(self, to, subject, body):
        if self.fail:
            raise httpx.ConnectError("down")
        self.sent.append((to, subject, body))
        return self.result


def emails(db, world):
    for sub in ("a-owner", "a-admin", "a-admin-s1", "a-op", "a-viewer", "a-viewer-s2", "b-owner", "tech"):
        db.execute(text("UPDATE person SET email = :e WHERE id = :p"), {"e": f"{sub}@example.com", "p": world.pid(sub)})
    db.execute(text("UPDATE person SET active = false WHERE id = :p"), {"p": world.pid("a-admin-s1")})
    db.commit()


def run(box, now=None):
    with SystemSession() as s:
        return notify.notify_lockdowns(s, box, now or datetime.now(timezone.utc))


def lock(client, world, on=True, reason="Threat reported"):
    r = client.post(f"/tenants/{world.a}/sites/{world.a1}/lockdown", headers=auth("a-op"), json={"on": on, "reason": reason})
    assert r.status_code == 202, r.text


def test_admins_and_operators_at_the_site_are_told_once_when_it_starts_and_when_it_ends(client, world, link, db):
    setup_site(client, world, link)
    emails(db, world)
    lock(client, world)
    box = Outbox()
    assert run(box) == 1
    to = sorted(t for t, _, _ in box.sent)
    # Operators, admins and owners at the site (partner staff included); never viewers, an inactive person, or another customer's people.
    assert to == ["a-admin@example.com", "a-op@example.com", "a-owner@example.com", "tech@example.com"]
    _, subject, body = box.sent[0]
    assert subject == "Locked down: Main office" and "Threat reported" in body and "every door" in body and "exits and fire release" in body
    assert run(box) == 0 and len(box.sent) == 4                                  # once
    lock(client, world, on=False, reason="All clear")
    assert run(box) == 1
    assert {s for _, s, _ in box.sent[4:]} == {"Lockdown ended: Main office"} and "All clear" in box.sent[4][2]


def test_mail_that_fails_is_tried_again_and_mail_that_is_off_is_not_kept_for_later(client, world, link, db):
    setup_site(client, world, link)
    emails(db, world)
    lock(client, world)
    box = Outbox()
    box.fail = True
    assert run(box) == 0                                                          # failed: not marked
    box.fail = False
    assert run(box) == 1 and len(box.sent) == 4
    lock(client, world, on=False, reason="All clear")
    off = Outbox(result=None)                                                     # no Postmark token: nothing sent, but marked
    assert run(off) == 1 and len(off.sent) == 1                                   # it stops at the first "not configured"
    assert run(Outbox()) == 0


def test_a_notice_over_an_hour_late_is_dropped(client, world, link, db):
    setup_site(client, world, link)
    emails(db, world)
    lock(client, world)
    box = Outbox()
    assert run(box, datetime.now(timezone.utc) + timedelta(hours=2)) == 1 and box.sent == []
    assert run(box) == 0


def test_a_site_with_some_doors_locked_down_names_them(client, world, link, db):
    ids = setup_site(client, world, link)
    emails(db, world)
    r = client.post(f"/tenants/{world.a}/sites/{world.a1}/lockdown", headers=auth("a-op"),
                    json={"on": True, "reason": "Drill", "door_ids": [ids["side"]]})
    assert r.status_code == 202
    box = Outbox()
    run(box)
    assert "(Side door)" in box.sent[0][2]

"""A small office used across the tests: two controllers, three doors, office hours, a holiday, staff and a cleaner.

Controller `ctl-a` (an A1610) has doors `door-a1` (front, two readers) and `door-a2` (side); `ctl-b` (an A1210) has `door-b1` (server room).
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone
from uuid import UUID

from app.document import SiteDocument
from app.link.protocol import Inventory, InventoryDoor

INVENTORY_A = Inventory(doors=[InventoryDoor(token="door-a1", name="Door 1", access_points=["ap-a1-in", "ap-a1-out"]),
                               InventoryDoor(token="door-a2", name="Door 2", access_points=["ap-a2-in"])])
INVENTORY_B = Inventory(doors=[InventoryDoor(token="door-b1", name="Door 1", access_points=["ap-b1-in"])])


INTERCOM_SECRET = "front-intercom-secret"
INTERCOM_SHA256 = hashlib.sha256(INTERCOM_SECRET.encode()).hexdigest()


def site(**over) -> SiteDocument:
    doc = {
        "site_id": "cw-main",
        "timezone": "America/New_York",
        "holiday_calendar_id": "us",
        "holiday_calendars": [{"id": "us", "name": "US holidays", "days": [{"day": "2026-12-25", "name": "Christmas"}]}],
        "schedules": [
            {"id": "office", "name": "Office hours", "windows": [{"days": ["mo", "tu", "we", "th", "fr"], "start": "08:00", "end": "18:00"}]},
            {"id": "evenings", "name": "Evenings", "on_holidays": "normal",
             "windows": [{"days": ["mo", "tu", "we", "th", "fr"], "start": "18:00", "end": "24:00"}]},
            {"id": "unused", "name": "Unused", "windows": [{"days": ["sa"], "start": "00:00", "end": "24:00"}]},
        ],
        "doors": [
            {"id": "front", "name": "Front door", "controller_id": "ctl-a", "controller_door": "door-a1", "unlock_schedule_id": "office"},
            {"id": "side", "name": "Side door", "controller_id": "ctl-a", "controller_door": "door-a2", "access_time_s": 5},
            {"id": "server", "name": "Server room", "controller_id": "ctl-b", "controller_door": "door-b1"},
        ],
        "access_groups": [
            {"id": "staff", "name": "Staff", "rules": [{"doors": ["front", "side"], "schedule_id": "office"}]},
            {"id": "it", "name": "IT", "rules": [{"doors": ["server", "front"]}]},
            {"id": "cleaners", "name": "Cleaners", "rules": [{"doors": ["side"], "schedule_id": "evenings"}]},
        ],
        "cardholders": [
            {"id": "alice", "name": "Alice Smith", "person_id": str(UUID(int=1)), "groups": ["staff", "it"],
             "credentials": [{"id": "alice-card", "kind": "card", "card": {"format": "h10301", "facility": 0, "number": 10213}},
                             {"id": "alice-pin", "kind": "pin", "pin": "4821"}]},
            {"id": "bob", "name": "Bob Jones", "groups": ["staff"], "valid_to": datetime(2027, 1, 1, tzinfo=timezone.utc),
             "credentials": [{"id": "bob-card", "kind": "card", "card": {"format": "w34", "number": 3735928559},
                              "valid_from": datetime(2026, 1, 1, tzinfo=timezone.utc)}]},
            {"id": "carol", "name": "Carol Cleaner", "groups": ["cleaners"], "suspended": True,
             "credentials": [{"id": "carol-card", "kind": "card", "card": {"format": "raw", "number": 0xABCDEF}}]},
            {"id": "dave", "name": "Dave Visitor", "groups": [], "credentials": [{"id": "dave-pin", "kind": "pin", "pin": "1111"}]},
        ],
        # The front door's intercom; its relay password is "front-intercom-secret" (INTERCOM_SECRET).
        "intercoms": [{"id": "ic-front", "name": "Front door intercom", "door_id": "front", "secret_sha256": INTERCOM_SHA256}],
    }
    doc.update(over)
    return SiteDocument.model_validate(doc)


CHRISTMAS = date(2026, 12, 25)

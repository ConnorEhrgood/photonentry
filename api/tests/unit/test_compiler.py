from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

import jsonschema
import pytest
from pydantic import ValidationError

from app.compiler import ical
from app.compiler.axis import FORMAT, CompileError, compile_controller
from app.compiler.wiegand import card_data
from app.document import Card, SiteDocument
from tests.fixtures.site import INVENTORY_A, INVENTORY_B, site

ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "..")


def _schema():
    with open(os.path.join(ROOT, "contract", "settings", "axis-settings.schema.json")) as f:
        return json.load(f)


def test_controller_a_gets_its_doors_groups_people_and_schedules():
    out = compile_controller(site(), "ctl-a", INVENTORY_A)
    assert out["format"] == FORMAT and out["timezone"] == "America/New_York"
    assert [s["token"] for s in out["schedules"]] == ["pe-s-evenings", "pe-s-office"]          # "unused" is not sent
    assert [p["token"] for p in out["access_profiles"]] == ["pe-g-cleaners", "pe-g-it", "pe-g-staff"]
    staff = next(p for p in out["access_profiles"] if p["token"] == "pe-g-staff")
    assert [(p["AccessPoint"], p["Schedule"]) for p in staff["AccessPolicy"]] == [
        ("ap-a1-in", ["pe-s-office"]), ("ap-a1-out", ["pe-s-office"]), ("ap-a2-in", ["pe-s-office"])]
    it = next(p for p in out["access_profiles"] if p["token"] == "pe-g-it")
    assert [(p["AccessPoint"], p["Schedule"]) for p in it["AccessPolicy"]] == [("ap-a1-in", ["standard_always"]), ("ap-a1-out", ["standard_always"])]
    assert [u["token"] for u in out["users"]] == ["pe-u-alice", "pe-u-bob", "pe-u-carol"]           # dave has no group
    jsonschema.validate(out, _schema())


def test_controller_b_gets_only_the_server_room():
    out = compile_controller(site(), "ctl-b", INVENTORY_B)
    assert [p["token"] for p in out["access_profiles"]] == ["pe-g-it"]
    assert [u["token"] for u in out["users"]] == ["pe-u-alice"]
    assert out["schedules"] == [] and out["door_schedules"] == []
    assert [d["token"] for d in out["doors"]] == ["door-b1"]


def test_credentials():
    creds = {c["token"]: c for c in compile_controller(site(), "ctl-a", INVENTORY_A)["credentials"]}
    alice = creds["pe-c-alice-card"]
    assert alice["IdData"] == [{"Name": "Card", "Value": "02004fcb"}] and alice["Enabled"] and alice["Status"] == "Enabled"
    assert [p["AccessProfile"] for p in alice["CredentialAccessProfile"]] == ["pe-g-it", "pe-g-staff"]
    assert creds["pe-c-alice-pin"]["IdData"] == [{"Name": "PIN", "Value": "4821"}]
    bob = creds["pe-c-bob-card"]
    assert bob["ValidFrom"] == "2026-01-01T00:00:00Z" and bob["ValidTo"] == "2027-01-01T00:00:00Z"
    carol = creds["pe-c-carol-card"]
    assert carol["Enabled"] is False and carol["Status"] == "Disabled"                      # suspended cardholder
    assert carol["IdData"] == [{"Name": "Card", "Value": "00abcdef"}]
    assert "pe-c-dave-pin" not in creds


def test_doors_and_unlock_schedules():
    out = compile_controller(site(), "ctl-a", INVENTORY_A)
    front, side = out["doors"]
    assert front == {"token": "door-a1", "Name": "Front door", "AccessTime": "PT7S", "OpenTooLongTime": "PT30S", "PreAlarmTime": "PT5S",
                     "DoorScheduleConfiguration": "pe-d-front"}
    assert side["AccessTime"] == "PT5S" and side["DoorScheduleConfiguration"] == ""
    assert out["door_schedules"] == [{"token": "pe-d-front", "Name": "Front door unlock schedule", "Description": "", "DoorSchedule": [
        {"ScheduledState": [{"ScheduleToken": ["pe-s-office"], "EnterAction": "Unlock"}, {"ScheduleToken": ["standard_always"], "EnterAction": "Lock"}]}]}]


def test_schedules_and_holidays():
    out = {s["token"]: s for s in compile_controller(site(), "ctl-a", INVENTORY_A)["schedules"]}
    office = out["pe-s-office"]
    assert "DTSTART:20000103T080000\r\nDTEND:20000103T180000\r\nRRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR" in office["ScheduleDefinition"]
    assert "DTSTART;VALUE=DATE:20261225" in office["ExceptionScheduleDefinition"]
    evenings = out["pe-s-evenings"]
    assert "DTEND:20000104T000000" in evenings["ScheduleDefinition"] and evenings["ExceptionScheduleDefinition"] == ""


def test_no_holiday_calendar_means_no_exceptions():
    out = compile_controller(site(holiday_calendar_id=None), "ctl-a", INVENTORY_A)
    assert all(s["ExceptionScheduleDefinition"] == "" for s in out["schedules"])


def test_ical_building_blocks():
    assert ical.whole_days([]) == ""
    text = ical.whole_days([datetime(2026, 7, 4).date(), datetime(2026, 7, 4).date()])
    assert text.count("BEGIN:VEVENT") == 1 and text.endswith("END:VCALENDAR\r\n")
    sat = SiteDocument.model_validate({"site_id": "x", "schedules": [{"id": "s", "name": "S", "windows": [
        {"days": ["su", "sa"], "start": "09:30", "end": "10:00"}]}]}).schedules[0]
    assert "DTSTART:20000108T093000\r\nDTEND:20000108T100000\r\nRRULE:FREQ=WEEKLY;BYDAY=SA,SU" in ical.weekly(sat.windows)


@pytest.mark.parametrize("card,expected", [
    (Card(format="h10301", facility=0, number=10213), "02004fcb"),      # Axis's own example
    (Card(format="h10301", facility=255, number=65535), "01ffffff"),
    (Card(format="w34", number=0), "0000000001"),
    (Card(format="w34", number=0xFFFFFFFF), "01ffffffff"),
    (Card(format="raw", number=1), "00000001"),
])
def test_card_data(card, expected):
    assert card_data(card) == expected


def test_compile_refuses_problems_and_unknown_doors():
    with pytest.raises(CompileError, match="does not exist"):
        compile_controller(site(access_groups=[{"id": "g", "name": "G", "rules": [{"doors": ["nope"]}]}]), "ctl-a", INVENTORY_A)
    with pytest.raises(CompileError, match="not reported"):
        compile_controller(site(), "ctl-a", None)
    with pytest.raises(CompileError, match="has no door door-a1"):
        compile_controller(site(), "ctl-a", INVENTORY_B)
    from app.link.protocol import Inventory, InventoryDoor
    bare = Inventory(doors=[InventoryDoor(token="door-a1"), InventoryDoor(token="door-a2", access_points=["x"])])
    with pytest.raises(CompileError, match="no access points"):
        compile_controller(site(), "ctl-a", bare)


def test_compile_refuses_naive_times():
    doc = site(cardholders=[{"id": "x", "name": "X", "groups": ["staff"], "valid_to": datetime(2027, 1, 1),
                             "credentials": [{"id": "xc", "kind": "pin", "pin": "9999"}]}])
    with pytest.raises(CompileError, match="time zone"):
        compile_controller(doc, "ctl-a", INVENTORY_A)


def test_capacity(monkeypatch):
    monkeypatch.setattr("app.compiler.axis.MAX_CREDENTIALS", 2)
    with pytest.raises(CompileError, match="more than"):
        compile_controller(site(), "ctl-a", INVENTORY_A)


def test_document_problems():
    doc = site(
        holiday_calendar_id="nope",
        schedules=[{"id": "s", "name": "S", "windows": [{"days": ["mo"], "start": "08:00", "end": "09:00"}]}] * 2,
        doors=[{"id": "d", "name": "D", "controller_id": "c", "controller_door": "x", "unlock_schedule_id": "zzz"},
               {"id": "e", "name": "E", "controller_id": "c", "controller_door": "x"}],
        access_groups=[{"id": "g", "name": "G", "rules": [{"doors": ["d"], "schedule_id": "zzz"}]}],
        cardholders=[
            {"id": "a", "name": "A", "groups": ["nope"], "credentials": [
                {"id": "k1", "kind": "card", "card": {"format": "raw", "number": 5}}, {"id": "k2", "kind": "pin", "pin": "1234"}]},
            {"id": "b", "name": "B", "credentials": [
                {"id": "k1", "kind": "card", "card": {"format": "raw", "number": 5}}, {"id": "k3", "kind": "pin", "pin": "1234"}]},
        ])
    p = "\n".join(doc.problems())
    for expected in ("schedule s: the id is used 2 times", "holiday calendar nope does not exist", "door x: mapped to more than one door",
                     "door d: unlock schedule zzz does not exist", "rule 1: schedule zzz does not exist", "access group nope does not exist",
                     "credential k1: the id is used 2 times", "card k1 is also held by cardholder a", "PIN k3 is the same as a PIN of cardholder a"):
        assert expected in p


@pytest.mark.parametrize("bad", [
    {"windows": [{"days": ["mo"], "start": "9:00", "end": "10:00"}]},
    {"windows": [{"days": ["mo"], "start": "10:00", "end": "09:00"}]},
    {"windows": [{"days": ["mo", "mo"], "start": "08:00", "end": "09:00"}]},
    {"windows": []},
    {"id": "has space"},
])
def test_bad_schedules(bad):
    s = {"id": "s", "name": "S", "windows": [{"days": ["mo"], "start": "08:00", "end": "09:00"}], **bad}
    with pytest.raises(ValidationError):
        SiteDocument.model_validate({"site_id": "x", "schedules": [s]})


@pytest.mark.parametrize("cred", [
    {"kind": "card"},
    {"kind": "card", "card": {"format": "raw", "number": 1}, "pin": "1234"},
    {"kind": "pin"},
    {"kind": "pin", "pin": "12"},
    {"kind": "pin", "pin": "1234", "card": {"format": "raw", "number": 1}},
    {"kind": "card", "card": {"format": "h10301", "number": 1}},
    {"kind": "card", "card": {"format": "w34", "facility": 1, "number": 1}},
    {"kind": "card", "card": {"format": "h10301", "facility": 1, "number": 70000}},
    {"kind": "pin", "pin": "1234", "valid_from": "2026-01-02T00:00:00Z", "valid_to": "2026-01-01T00:00:00Z"},
])
def test_bad_credentials(cred):
    with pytest.raises(ValidationError):
        SiteDocument.model_validate({"site_id": "x", "cardholders": [{"id": "a", "name": "A", "credentials": [{"id": "k", **cred}]}]})


def test_the_sample_settings_match_the_compiler():
    """contract/settings/sample.json is what the C side's tests apply; regenerate it with scripts/contract.py when the compiler changes."""
    with open(os.path.join(ROOT, "contract", "settings", "sample.json")) as f:
        assert json.load(f) == compile_controller(site(), "ctl-a", INVENTORY_A)

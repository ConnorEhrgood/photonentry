from datetime import date

import pytest

from app import templates
from app.document import SiteDocument
from app.templates import TemplateError, holidays, plan

A = {"controller_id": "c1", "controller_door": "door1"}
B = {"controller_id": "c1", "controller_door": "door2"}


def test_us_business_holidays_2026_with_weekend_observance():
    assert holidays("us-business", 2026) == [
        (date(2026, 1, 1), "New Year's Day"), (date(2026, 5, 25), "Memorial Day"), (date(2026, 7, 3), "Independence Day"),
        (date(2026, 9, 7), "Labor Day"), (date(2026, 11, 26), "Thanksgiving"), (date(2026, 11, 27), "Day after Thanksgiving"),
        (date(2026, 12, 25), "Christmas Day")]


def test_us_federal_holidays_2027():
    got = dict((n, d) for d, n in holidays("us-federal", 2027))
    assert got["Martin Luther King Jr. Day"] == date(2027, 1, 18) and got["Presidents' Day"] == date(2027, 2, 15)
    assert got["Juneteenth"] == date(2027, 6, 18)                 # a Saturday: observed Friday
    assert got["Independence Day"] == date(2027, 7, 5)            # a Sunday: observed Monday
    assert got["Columbus Day"] == date(2027, 10, 11) and got["Veterans Day"] == date(2027, 11, 11)
    assert "Day after Thanksgiving" not in got and len(got) == 11


def test_an_office_with_only_its_main_entrance():
    p = plan("office", {"main_entrance": A}, {}, [2026])
    assert [d[0].key for d in p.doors] == ["main_entrance"] and p.doors[0][4] is None             # not unlocked unless asked
    assert [g.key for g, _ in p.groups] == ["staff", "managers", "cleaning"]                      # IT has no server room here
    assert [s.key for s in p.schedules] == ["extended", "cleaning"]                                # business hours unused
    assert len(p.holidays) == 7


def test_an_office_with_every_door_and_the_main_entrance_unlocked():
    p = plan("office", {"main_entrance": {**A, "name": "Lobby"}, "staff_entrance": B, "server_room": {"controller_id": "c2", "controller_door": "d"}},
             {"unlock_main": True}, [2026, 2027])
    assert p.doors[0][3] == "Lobby" and p.doors[0][4] == "business"
    assert {s.key for s in p.schedules} == {"business", "extended", "cleaning"}
    it = dict((g.key, rules) for g, rules in p.groups)["it"]
    assert it == [(["server_room"], None)] and len(p.holidays) == 14


@pytest.mark.parametrize("doors,options,word", [
    ({}, {}, "choose a door for: Main entrance"),
    ({"main_entrance": A, "lobby": B}, {}, "no door lobby"),
    ({"main_entrance": A}, {"nope": True}, "no option nope"),
    ({"main_entrance": A, "staff_entrance": A}, {}, "two slots"),
])
def test_bad_plans(doors, options, word):
    with pytest.raises(TemplateError, match=word):
        plan("office", doors, options, [2026])
    with pytest.raises(TemplateError, match="no template"):
        plan("castle", {}, {}, [2026])


def test_the_catalog_names_every_template_and_validates_as_documents():
    cat = templates.catalog()
    assert [t["key"] for t in cat] == list(templates.TEMPLATES)
    for t in cat:
        assert any(s["required"] for s in t["slots"])
        # Every template's schedules are valid schedules of a site document.
        SiteDocument.model_validate({"site_id": "x", "schedules": [{"id": s["key"], "name": s["name"], "windows": s["windows"],
                                                                    "on_holidays": s["on_holidays"]} for s in t["schedules"]]})


def test_a_school_with_every_door_and_both_options():
    doors = {k: {"controller_id": "c", "controller_door": k} for k in ("main_entrance", "staff_entrance", "side_door", "gym_entrance", "office_door")}
    p = plan("school", doors, {"unlock_arrival": True, "unlock_gym_events": True}, [2026])
    unlock = {d[0].key: d[4] for d in p.doors}
    assert unlock == {"main_entrance": "arrival", "staff_entrance": None, "side_door": None, "gym_entrance": "after_school", "office_door": None}
    assert [g.key for g, _ in p.groups] == ["staff", "administrators", "office", "custodians", "programs"]
    assert len(p.holidays) == 11                                   # the federal holidays
    assert templates.TEMPLATES["school"].note


def test_a_school_without_a_gym_has_no_after_school_group():
    p = plan("school", {"main_entrance": A}, {}, [2026])
    assert "programs" not in [g.key for g, _ in p.groups] and "after_school" not in [s.key for s in p.schedules]


def test_multifamily_residents_combine_rules():
    p = plan("multifamily", {"lobby": A, "package_room": B, "amenity": {"controller_id": "c1", "controller_door": "door3"}}, {}, [2026])
    residents = dict((g.key, r) for g, r in p.groups)["residents"]
    assert residents == [(["lobby"], None), (["package_room"], "package_hours"), (["amenity"], "amenity_hours")]
    assert {s.key for s in p.schedules} == {"package_hours", "amenity_hours", "vendor_hours"}    # no leasing office: no office hours


def test_a_gate_kept_open_in_business_hours():
    p = plan("gate", {"vehicle_gate": A}, {"open_vehicle_gate": True}, [2026])
    slot, *_, unlock = p.doors[0]
    assert unlock == "business" and slot.access_time_s == 20 and slot.open_too_long_s == 300
    assert [g.key for g, _ in p.groups] == ["users", "deliveries"]

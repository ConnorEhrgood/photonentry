"""The commissioning rules (app/commissioning.py): what a record needs before it may be signed, by state, and when a door is in service."""
from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from app import commissioning as c

TODAY = date(2026, 11, 14)
GOOD = c.Record(jurisdiction="PA", lock_type="strike_fail_secure", failure_state="fail_secure", special_locking="none", fire_release="none_present",
                fire_tested_on=None, fire_tested_by="", rex_checked=True, contact_checked=True, reader_ul_verified=False,
                ahj_reference="Permit 2026-0412", installer="Ann Lee", egress="Lever, free egress")
SP_LV = c.LicenseFacts("WV", "wv_sp_lv", date(2027, 6, 30), False)


@pytest.mark.parametrize("address,state", [
    ("1 Mill Road, Pittsburgh PA 15212", "PA"), ("200 Main St, Columbus, OH 43215-1234", "OH"), ("5 Capitol St, Charleston, WV", "WV"),
    ("9 River Rd, Wheeling, West Virginia 26003, USA", "WV"), ("12 Lake Ave, Toledo, Ohio", "OH"), ("1 Broad St, Philadelphia, Pennsylvania 19107", "PA"),
    ("10 Elm St, Paris, France", None), ("", None), ("44 Park Ave, New York NY 10016", None),
])
def test_the_state_from_a_sites_address(address, state):
    assert c.state_of(address) == state


def test_a_complete_record_in_pennsylvania_needs_no_license():
    assert c.problems(GOOD, None, TODAY) == []


@pytest.mark.parametrize("change,words", [
    ({"lock_type": "rope"}, "lock type"), ({"failure_state": "maybe"}, "fail-secure or fail-safe"),
    ({"lock_type": "maglock", "failure_state": "fail_secure", "special_locking": "sensor_release", "reader_ul_verified": True}, "magnetic lock is fail-safe"),
    ({"lock_type": "maglock", "failure_state": "fail_safe"}, "needs sensor release"),
    ({"special_locking": "lockout"}, "special locking applies"),
    ({"special_locking": "delayed_egress"}, "UL-verified reader"),
    ({"fire_release": "tested"}, "when the fire release was tested"),
    ({"fire_release": "tested", "fire_tested_on": date(2026, 12, 1), "fire_tested_by": "Bo"}, "in the future"),
    ({"fire_release": "skipped"}, "none at this door"),
    ({"rex_checked": False}, "request-to-exit"), ({"contact_checked": False}, "door contact"),
    ({"egress": " "}, "egress hardware"), ({"ahj_reference": ""}, "AHJ reference"), ({"installer": ""}, "the installer"),
    ({"jurisdiction": "NY"}, "PA, OH, WV"),
])
def test_each_missing_part_is_named(change, words):
    found = c.problems(replace(GOOD, **change), None, TODAY)
    assert any(words in p for p in found), found


def test_a_tested_fire_release_and_special_locking_done_right():
    r = replace(GOOD, lock_type="maglock", failure_state="fail_safe", special_locking="sensor_release", reader_ul_verified=True,
                fire_release="tested", fire_tested_on=TODAY, fire_tested_by="Bo Fire")
    assert c.problems(r, None, TODAY) == []


def test_west_virginia_needs_a_current_sp_lv_license_for_the_state():
    wv = replace(GOOD, jurisdiction="WV")
    assert "SP-LV" in c.problems(wv, None, TODAY)[0]
    assert c.problems(wv, SP_LV, TODAY) == []
    assert "the installer's Specialty" in c.problems(wv, replace(SP_LV, kind="wv_contractor"), TODAY)[0]
    assert "expired on 2026-11-13" in c.problems(wv, replace(SP_LV, expires_on=date(2026, 11, 13)), TODAY)[0]
    assert c.problems(wv, replace(SP_LV, expires_on=TODAY), TODAY) == []                      # good through its last day
    assert "removed" in c.problems(wv, replace(SP_LV, removed=True), TODAY)[0]
    assert "is for WV; the site is in OH" in c.problems(replace(GOOD, jurisdiction="OH"), SP_LV, TODAY)[0]
    assert c.problems(replace(GOOD, jurisdiction="ZZ"), None, TODAY) == []                     # elsewhere: no state rule here


def test_when_a_door_is_in_service():
    assert c.status(None, False, "door1") == c.Status(False, "never")
    assert c.status("door1", True, "door1") == c.Status(False, "voided")
    assert c.status("door1", False, "door2") == c.Status(False, "moved")
    assert c.status("door1", False, "door1") == c.Status(True, "")


def test_expiring_within_thirty_days():
    assert c.expiring(date(2026, 12, 14), TODAY) and not c.expiring(date(2026, 12, 15), TODAY) and not c.expiring(None, TODAY)


def test_the_routes_today_is_the_utc_date():
    from datetime import datetime, timezone
    from app.routes import commissioning as route
    assert route._today() == datetime.now(timezone.utc).date()

"""The compiler's output, applied to the simulated controller, opens the right doors at the right times: the meaning of the settings is tested
end to end in Python before the C side applies them (tests/e2e)."""
from __future__ import annotations

import pytest

from app.compiler.axis import compile_controller
from app.compiler.wiegand import card_data
from app.document import Card
from app.link.protocol import Inventory, InventoryDoor
from axis_sim.testing import DOOR1, DOOR2, R1IN, R1OUT, R2IN, Sim, apply_settings, inventory
from tests.fixtures.site import site

ALICE = card_data(Card(format="h10301", facility=0, number=10213))
BOB = card_data(Card(format="w34", number=3735928559))
CAROL = card_data(Card(format="raw", number=0xABCDEF))


@pytest.fixture()
def office(sim: Sim) -> Sim:
    doors = [
        {"id": "front", "name": "Front door", "controller_id": "ctl-a", "controller_door": DOOR1, "unlock_schedule_id": "office"},
        {"id": "side", "name": "Side door", "controller_id": "ctl-a", "controller_door": DOOR2, "access_time_s": 5, "open_too_long_s": 20,
         "pre_alarm_s": 5},
        {"id": "server", "name": "Server room", "controller_id": "ctl-b", "controller_door": "elsewhere"},
    ]
    inv = Inventory(doors=[InventoryDoor(token=t, access_points=aps) for t, aps in inventory(sim).items()])
    apply_settings(sim, compile_controller(site(doors=doors), "ctl-a", inv))
    return sim


def test_staff_in_office_hours_only(office):
    office.at("2026-11-16 10:00")                    # Monday
    assert office.card(R2IN, BOB) == {"granted": True, "reason": "Granted"}
    office.at("2026-11-15 10:00")                    # Sunday
    assert office.card(R2IN, BOB) == {"granted": False, "reason": "NotPermittedAtThisTime"}
    office.at("2026-11-16 18:30")
    assert office.card(R2IN, BOB)["granted"] is False


def test_holidays_close_office_hours_but_not_evenings(office):
    office.at("2026-12-25 10:00")                    # Christmas, a Friday
    assert office.card(R2IN, BOB) == {"granted": False, "reason": "NotPermittedAtThisTime"}
    office.at("2026-12-24 10:00")
    assert office.card(R2IN, BOB)["granted"] is True


def test_it_has_the_front_door_at_all_times_and_both_readers(office):
    office.at("2026-11-15 03:00")
    assert office.card(R1IN, ALICE)["granted"] is True
    assert office.card(R1OUT, ALICE)["granted"] is True
    assert office.card(R2IN, ALICE)["granted"] is False          # the side door is staff hours only


def test_pins_suspensions_and_unknown_cards(office):
    office.at("2026-11-16 10:00")
    assert office.pin(R2IN, "4821")["granted"] is True
    assert office.card(R2IN, CAROL) == {"granted": False, "reason": "CredentialNotEnabled"}
    assert office.card(R2IN, "00000001") == {"granted": False, "reason": "InvalidCredential"}
    assert office.pin(R2IN, "1111") == {"granted": False, "reason": "InvalidCredential"}  # dave has no access, so is not on the controller


def test_validity_windows(office):
    office.at("2027-01-02 10:00")                    # Bob's cardholder record ended 2027-01-01
    assert office.card(R2IN, BOB) == {"granted": False, "reason": "CredentialExpired"}
    office.at("2025-12-31 10:00")                    # his card starts 2026-01-01
    assert office.card(R2IN, BOB) == {"granted": False, "reason": "CredentialNotActive"}


def test_the_front_door_unlocks_in_office_hours(office):
    office.at("2026-11-16 10:00")
    assert office.state(DOOR1)["mode"] == "Unlocked"
    office.at("2026-11-16 19:00")
    assert office.state(DOOR1)["mode"] == "Locked"
    office.at("2026-12-25 10:00")
    assert office.state(DOOR1)["mode"] == "Locked"


def test_access_taken_forced_and_held_open(office):
    office.at("2026-11-16 10:00")
    office.card(R2IN, BOB)
    assert office.state(DOOR2)["mode"] == "Accessed"
    office.door(DOOR2, "Open")
    office.door(DOOR2, "Closed")
    assert office.state(DOOR2)["mode"] == "Locked"
    assert office.topics()[-6:] == ["AccessControl/AccessGranted/Credential", "Door/State/DoorMode", "Door/State/DoorPhysicalState",
                                    "AccessControl/AccessTaken/Credential", "Door/State/DoorPhysicalState", "Door/State/DoorMode"]

    office.door(DOOR2, "Open")                       # nobody presented anything: forced
    assert office.state(DOOR2)["alarm"] == "DoorForcedOpen"
    office.door(DOOR2, "Closed")
    assert office.state(DOOR2)["alarm"] == "Normal"

    office.card(R2IN, BOB)
    office.door(DOOR2, "Open")
    office.at("2026-11-16 10:00:30")                 # access time (5 s) is over, the door has been open 30 s (limit 20)
    assert office.state(DOOR2)["alarm"] == "DoorOpenTooLong"
    assert "Door/State/DoorWarning" in office.topics()


def test_access_not_taken(office):
    office.at("2026-11-16 10:00")
    office.card(R2IN, BOB)
    office.at("2026-11-16 10:00:06")
    assert office.state(DOOR2)["mode"] == "Locked"
    assert office.topics()[-2:] == ["AccessControl/AccessNotTaken/Credential", "Door/State/DoorMode"]


def test_lockdown_keeps_the_door_locked_until_released(office):
    office.at("2026-11-16 19:00")
    office.call("doorcontrol", "tdc:LockDownDoor", {"Token": DOOR2})
    assert office.card(R2IN, ALICE)["granted"] is False
    office.card(R2IN, BOB)
    assert office.state(DOOR2)["mode"] == "LockedDown"
    assert office.call("doorcontrol", "tdc:UnlockDoor", {"Token": DOOR2}, status=500)["FaultSubCode"] == "ter:Failure"
    office.call("doorcontrol", "tdc:LockDownReleaseDoor", {"Token": DOOR2})
    assert office.state(DOOR2)["mode"] == "Locked"
    assert office.call("doorcontrol", "tdc:LockDownReleaseDoor", {"Token": DOOR2}, status=500)["FaultSubCode"] == "ter:Failure"


def test_remote_actions(office):
    office.at("2026-11-16 19:00")
    office.call("doorcontrol", "tdc:AccessDoor", {"Token": DOOR2, "AccessTime": "PT3S"})
    assert office.state(DOOR2)["mode"] == "Accessed"
    office.call("doorcontrol", "tdc:UnlockDoor", {"Token": DOOR2})
    office.call("doorcontrol", "tdc:BlockDoor", {"Token": DOOR2})
    assert office.call("doorcontrol", "tdc:AccessDoor", {"Token": DOOR2}, status=500)["FaultSubCode"] == "ter:Failure"
    office.call("doorcontrol", "tdc:LockOpenDoor", {"Token": DOOR2})
    assert office.state(DOOR2)["mode"] == "LockedOpen"
    office.call("doorcontrol", "tdc:LockDownDoor", {"Token": DOOR2})     # lockdown wins over locked open
    assert office.state(DOOR2)["mode"] == "LockedDown"


def test_rex_and_remote_card_activities(office):
    office.at("2026-11-16 19:00")
    office.call("idpoint", "axtid:IndicateRemoteActivities", {"Token": R2IN, "Activities": [{"Type": "Card", "Params": [{"Name": "Card", "Value": BOB}]}]})
    assert office.topics()[-1] == "AccessControl/Denied/Credential"
    ap = office.call("pacs", "pacsaxis:GetAccessPoint", {"Token": [f"Axis-{office.device.mac}:ap2in"]})["AccessPoint"][0]
    office.call("pacs", "pacsaxis:SetAccessPoint", {"AccessPoint": [{**ap, "AuthenticationProfile": ["REXOnly"]}]})
    office.call("idpoint", "axtid:IndicateRemoteActivities", {"Token": R2IN, "Activities": [{"Type": "REX"}]})
    assert "AccessControl/AccessGranted/Anonymous" in office.topics()[-3:]
    office.call("pacs", "tac:DisableAccessPoint", {"Token": ap["token"]})
    assert office.card(R2IN, BOB) == {"granted": False, "reason": "Unauthorized"}

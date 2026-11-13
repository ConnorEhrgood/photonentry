import json
import os
import uuid
from datetime import datetime, timezone

import jsonschema
import pytest

from app.events import normalize
from app.guard import binding, message, test_message
from app.models import Door, DoorEvent

ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "..")
SCHEMA = json.load(open(os.path.join(ROOT, "contract", "guard", "ingest-event.schema.json")))


@pytest.mark.parametrize("topic,data,kind,severity,label", [
    ("AccessControl/AccessGranted/Credential", {}, "granted", "info", "Access granted"),
    ("AccessControl/AccessGranted/Anonymous", {}, "granted", "info", "Exit button"),
    ("AccessControl/AccessTaken/Credential", {}, "access_taken", "info", "Door opened after access"),
    ("AccessControl/AccessNotTaken/Anonymous", {}, "access_not_taken", "info", "Access not used"),
    ("AccessControl/Denied/CredentialNotFound/Card", {"Card": "01"}, "denied", "warning", "Denied: unknown card or PIN"),
    ("AccessControl/Denied/Credential", {"Reason": "NotPermittedAtThisTime"}, "denied", "warning", "Denied: outside its schedule"),
    ("AccessControl/Denied/Credential", {"Reason": "SomethingNew"}, "denied", "warning", "Denied: refused"),
    ("Door/State/DoorAlarm", {"State": "DoorForcedOpen"}, "forced", "critical", "Door forced open"),
    ("Door/State/DoorAlarm", {"State": "DoorOpenTooLong"}, "held_open", "critical", "Door held open"),
    ("Door/State/DoorAlarm", {"State": "Normal"}, "alarm_cleared", "info", "Door alarm cleared"),
    ("Door/State/DoorWarning", {"State": "DoorOpenTooLongWarn"}, "held_warning", "warning", "Door open too long soon"),
    ("Door/State/DoorWarning", {"State": "Normal"}, "other", "info", "Door warning cleared"),
    ("Door/State/DoorTamper", {"State": "TamperDetected"}, "tamper", "critical", "Door tampered with"),
    ("Door/State/DoorTamper", {"State": "NotInTamper"}, "tamper_cleared", "info", "Door tamper cleared"),
    ("Door/State/DoorPhysicalState", {"State": "Open"}, "opened", "info", "Door opened"),
    ("Door/State/DoorPhysicalState", {"State": "Closed"}, "closed", "info", "Door closed"),
    ("Door/State/DoorMode", {"State": "LockedDown"}, "mode", "warning", "Door locked down"),
    ("Door/State/DoorMode", {"State": "Accessed"}, "mode", "info", "Door unlocked for access"),
    ("Door/State/DoorMode", {"State": "Weird"}, "mode", "info", "Door weird"),
    ("Door/State/DoorMode", {}, "mode", "info", "Door changed"),
    ("IdPoint/Activity", {"Reason": "CardPresented"}, "other", "info", "Activity"),
    ("", {}, "other", "info", "Event"),
])
def test_normalize(topic, data, kind, severity, label):
    n = normalize(topic, data)
    assert (n.kind, n.severity, n.label) == (kind, severity, label)


DOOR = Door(id=uuid.UUID(int=7), site_id=uuid.UUID(int=8), name="Side door")


def ev(seq, topic, data=None, ref="r"):
    return DoorEvent(controller_id=uuid.UUID(int=9), seq=seq, occurred_at=datetime(2026, 11, 16, 15, tzinfo=timezone.utc), topic=topic, source={},
                     data=data or {}, ref=ref)


def msg(e, alarms=None, holder=None):
    return message(e, normalize(e.topic, e.data), DOOR, holder, alarms or {})


def test_grants_and_denials_are_instant_with_a_clip():
    m = msg(ev(1, "AccessControl/AccessGranted/Credential", ref="tok-1"), holder="Ann")
    assert m.payload["state"] == "instant" and m.payload["label"] == "Access granted: Ann at Side door" and m.payload["record"] == {"pre_s": 10, "post_s": 20}
    assert m.payload["dedup_key"] == f"entry:{uuid.UUID(int=9)}:tok-1" and m.payload["targets"] == {"binding": binding(DOOR)}
    assert msg(ev(2, "AccessControl/Denied/Credential", {"Reason": "CredentialExpired"}, ref="")).payload["dedup_key"].endswith(":2")
    jsonschema.validate(m.payload, SCHEMA)


def test_the_exit_button_and_door_bookkeeping_are_not_sent():
    for topic, data in (("AccessControl/AccessGranted/Anonymous", {}), ("Door/State/DoorMode", {"State": "Locked"}),
                        ("Door/State/DoorPhysicalState", {"State": "Open"}), ("AccessControl/AccessTaken/Credential", {})):
        assert msg(ev(1, topic, data)) is None


def test_an_alarm_starts_once_and_ends_under_its_key():
    start = msg(ev(3, "Door/State/DoorAlarm", {"State": "DoorForcedOpen"}))
    assert start.payload["state"] == "started" and start.opens == ("alarm", start.payload["dedup_key"]) and start.payload["severity"] == "critical"
    assert msg(ev(4, "Door/State/DoorAlarm", {"State": "DoorOpenTooLong"}), {"alarm": "entry:alarm:k"}) is None        # already open
    end = msg(ev(5, "Door/State/DoorAlarm", {"State": "Normal"}), {"alarm": "entry:alarm:k"})
    assert end.payload["dedup_key"] == "entry:alarm:k" and end.payload["state"] == "ended" and end.payload["record"] is False and end.closes == "alarm"
    assert msg(ev(6, "Door/State/DoorAlarm", {"State": "Normal"})) is None                                  # nothing open: nothing to end
    tamper = msg(ev(7, "Door/State/DoorTamper", {"State": "TamperDetected"}), {"alarm": "entry:alarm:k"})
    assert tamper.opens[0] == "tamper"                                                                    # a tamper is its own alarm
    for p in (start.payload, end.payload, tamper.payload, test_message("x")):
        jsonschema.validate(p, SCHEMA)

"""Door events in PhotonEntry's own words (ARCHITECTURE §6.3), from what a controller reported (its topic, source and data; contract/link).

One function, used by the API's event list, the Guard sender (app/guard.py) and the PhotonConsole feed (app/consolefeed.py), so that "forced"
or "denied: outside its schedule" means the same thing everywhere. A topic this build does not know becomes `other` with the topic kept, never
an error: a firmware update can add topics.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

# Axis and ONVIF denial reasons, in PhotonEntry's words (sim/reference/AXIS-PACS.md §8.2).
REASONS: Dict[str, str] = {
    "NotPermittedAtThisTime": "outside_schedule", "CredentialNotEnabled": "credential_off", "CredentialExpired": "expired",
    "CredentialNotActive": "not_yet_valid", "InvalidAccessProfile": "no_access", "Unauthorized": "no_access", "InvalidPIN": "wrong_pin",
    "AntiPassbackViolation": "anti_passback", "InvalidCredential": "unknown_credential",
}
REASON_WORDS: Dict[str, str] = {
    "outside_schedule": "outside its schedule", "credential_off": "credential turned off", "expired": "credential expired",
    "not_yet_valid": "credential not active yet", "no_access": "no access here", "wrong_pin": "wrong PIN", "anti_passback": "anti-passback",
    "unknown_credential": "unknown card or PIN", "other": "refused",
}


@dataclass(frozen=True)
class Normal:
    kind: str                       # granted | denied | access_taken | access_not_taken | opened | closed | forced | held_open | alarm_cleared |
                                    # held_warning | tamper | tamper_cleared | mode | intercom_tamper | intercom_call | intercom_refused | other
    severity: str                   # info | warning | critical
    label: str                      # a few words for people
    reason: Optional[str] = None    # for a denial: one of REASON_WORDS
    method: Optional[str] = None    # credential | rex | intercom
    state: Optional[str] = None     # the controller's own state word, for mode events


def normalize(topic: str, data: Dict[str, str]) -> Normal:
    state = data.get("State")
    if topic.startswith("PhotonEntry/Intercom/"):
        return _intercom(topic, data)
    if topic == "AccessControl/AccessGranted/Credential":
        return Normal("granted", "info", "Access granted", method="credential")
    if topic == "AccessControl/AccessGranted/Anonymous":
        return Normal("granted", "info", "Exit button", method="rex")
    if topic.startswith("AccessControl/AccessTaken/"):
        return Normal("access_taken", "info", "Door opened after access")
    if topic.startswith("AccessControl/AccessNotTaken/"):
        return Normal("access_not_taken", "info", "Access not used")
    if topic.startswith("AccessControl/Denied/CredentialNotFound"):
        return Normal("denied", "warning", "Denied: unknown card or PIN", reason="unknown_credential")
    if topic.startswith("AccessControl/Denied/"):
        reason = REASONS.get(data.get("Reason", ""), "other")
        return Normal("denied", "warning", f"Denied: {REASON_WORDS[reason]}", reason=reason)
    if topic == "Door/State/DoorAlarm":
        if state == "DoorForcedOpen":
            return Normal("forced", "critical", "Door forced open")
        if state == "DoorOpenTooLong":
            return Normal("held_open", "critical", "Door held open")
        return Normal("alarm_cleared", "info", "Door alarm cleared")
    if topic == "Door/State/DoorWarning":
        if state == "DoorOpenTooLongWarn":
            return Normal("held_warning", "warning", "Door open too long soon")
        return Normal("other", "info", "Door warning cleared", state=state)
    if topic == "Door/State/DoorTamper":
        if state == "TamperDetected":
            return Normal("tamper", "critical", "Door tampered with")
        return Normal("tamper_cleared", "info", "Door tamper cleared")
    if topic == "Door/State/DoorPhysicalState":
        return Normal("opened", "info", "Door opened") if state == "Open" else Normal("closed", "info", "Door closed")
    if topic == "Door/State/DoorMode":
        words = {"Locked": "locked", "Unlocked": "unlocked", "Accessed": "unlocked for access", "LockedDown": "locked down",
                 "LockedOpen": "held open", "Blocked": "blocked", "DoubleLocked": "double locked"}
        return Normal("mode", "warning" if state == "LockedDown" else "info", f"Door {words.get(state or '', (state or 'changed').lower())}", state=state)
    return Normal("other", "info", topic.split("/")[-1] or "Event", state=state)


def _intercom(topic: str, data: Dict[str, str]) -> Normal:
    """Events `entry-link` records itself for the intercoms at its doors (acap/entry-link/app/link.c, local_handle)."""
    what = topic.rsplit("/", 1)[-1]
    if what == "Unlock":
        if data.get("Result") == "ok":
            return Normal("granted", "info", "Opened from the intercom", method="intercom")
        return Normal("other", "warning", "Intercom unlock failed: the controller did not open the door")
    if what == "Tamper":
        return Normal("intercom_tamper", "critical", "Intercom tampered with")
    if what == "CallStarted":
        return Normal("intercom_call", "info", "Intercom call")
    if what == "CallEnded":
        return Normal("intercom_call", "info", "Intercom call ended", state="ended")
    if what == "Refused":
        return Normal("intercom_refused", "warning", "Intercom request refused: wrong key")
    return Normal("other", "info", what or "Event")

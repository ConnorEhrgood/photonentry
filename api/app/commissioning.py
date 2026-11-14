"""Commissioning (ARCHITECTURE §7.2, decision 16; licensing §7.7). CRITICAL: it decides whether a door counts as in service, and what an
installer must have recorded, and with which license, before it does.

A door is **in service** when its newest commissioning record is not voided and was signed for the controller door it is on now. A record needs
everything §7.2 lists; in West Virginia, a current Specialty Low-Voltage (SP-LV) license, the only state of the three that licenses this work
statewide. Any license named must be for the state the site is in, current on the day it is signed, and not removed. Not legal advice: §7.7.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional

STATES = ("PA", "OH", "WV")
# The licenses §7.7 found, per state (plus "other", e.g. a city's).
LICENSE_KINDS: Dict[str, Dict[str, str]] = {
    "WV": {"wv_sp_lv": "Specialty Low-Voltage Electrician (SP-LV), State Fire Marshal", "wv_contractor": "WV Contractor Licensing Board",
           "other": "Other"},
    "OH": {"oh_ocilb_electrical": "OCILB electrical contractor", "oh_fire_protection": "State Fire Marshal fire protection certification",
           "other": "Other (e.g. a city registration)"},
    "PA": {"pa_philadelphia_electrical": "Philadelphia electrical contractor", "pa_pittsburgh_electrical": "Pittsburgh electrical trade license",
           "pa_hicpa": "Home Improvement Contractor (HICPA)", "other": "Other"},
}
REQUIRED = {"WV": "wv_sp_lv"}       # the license a record must name, by state
LOCK_TYPES = {
    "strike_fail_secure": "Electric strike, fail-secure", "strike_fail_safe": "Electric strike, fail-safe", "maglock": "Magnetic lock",
    "lever_fail_secure": "Electrified lever or mortise, fail-secure", "lever_fail_safe": "Electrified lever or mortise, fail-safe",
    "exit_device": "Electrified exit device (panic bar)", "gate_operator": "Gate operator", "other": "Other",
}
SPECIAL = {"none": "None", "delayed_egress": "Delayed egress", "controlled_egress": "Controlled egress", "sensor_release": "Sensor release (maglock)"}
_STATE_IN_ADDRESS = re.compile(r"(?:^|[\s,])(PA|OH|WV|Pennsylvania|Ohio|West Virginia)(?:[\s,]+\d{5}(?:-\d{4})?)?\s*(?:,\s*(?:USA|US|United States))?\s*$",
                               re.IGNORECASE)
_NAMES = {"pennsylvania": "PA", "ohio": "OH", "west virginia": "WV"}


def state_of(address: str) -> Optional[str]:
    """PA, OH or WV from the end of a site's address ("1 Mill Road, Pittsburgh PA 15212"), or None."""
    m = _STATE_IN_ADDRESS.search(address.strip())
    if not m:
        return None
    word = m.group(1)
    return _NAMES.get(word.lower(), word.upper())


@dataclass(frozen=True)
class LicenseFacts:
    state: str
    kind: str
    expires_on: Optional[date]
    removed: bool


@dataclass(frozen=True)
class Record:
    jurisdiction: str            # PA | OH | WV | ZZ
    lock_type: str
    failure_state: str
    special_locking: str
    fire_release: str            # tested | none_present
    fire_tested_on: Optional[date]
    fire_tested_by: str
    rex_checked: bool
    contact_checked: bool
    reader_ul_verified: bool
    ahj_reference: str
    installer: str
    egress: str


def problems(r: Record, lic: Optional[LicenseFacts], today: date) -> List[str]:
    """What keeps the record from being signed, in sentences. Empty: it may be signed."""
    out: List[str] = []
    if r.jurisdiction not in STATES + ("ZZ",):
        out.append("The state is PA, OH, WV, or elsewhere")
    if r.lock_type not in LOCK_TYPES:
        out.append("Choose the lock type")
    if r.failure_state not in ("fail_secure", "fail_safe"):
        out.append("Say whether the lock is fail-secure or fail-safe")
    if r.lock_type == "maglock" and r.failure_state != "fail_safe":
        out.append("A magnetic lock is fail-safe")
    if r.special_locking not in SPECIAL:
        out.append("Say which special locking applies, or none")
    if r.lock_type == "maglock" and r.special_locking == "none":
        out.append("A magnetic lock on an egress door needs sensor release (or delayed or controlled egress): say which")
    if r.special_locking != "none" and not r.reader_ul_verified:
        out.append("Special locking needs a UL-verified reader on the controller")
    if r.fire_release == "tested":
        if r.fire_tested_on is None or not r.fire_tested_by.strip():
            out.append("Say when the fire release was tested, and by whom")
        elif r.fire_tested_on > today:
            out.append("The fire release test date is in the future")
    elif r.fire_release != "none_present":
        out.append("Say whether the fire release was tested, or that there is none at this door")
    if not r.rex_checked:
        out.append("Check the request-to-exit")
    if not r.contact_checked:
        out.append("Check the door contact")
    for value, what in ((r.egress, "the egress hardware"), (r.ahj_reference, "the AHJ reference or permit number"), (r.installer, "the installer")):
        if not value.strip():
            out.append(f"Record {what}")
    needed = REQUIRED.get(r.jurisdiction)
    if lic is None:
        if needed:
            out.append(f"In {r.jurisdiction}, name the installer's {LICENSE_KINDS[r.jurisdiction][needed]} license")
        return out
    if lic.removed:
        out.append("That license was removed")
    if lic.state != r.jurisdiction:
        out.append(f"That license is for {lic.state}; the site is in {r.jurisdiction}")
    elif needed and lic.kind != needed:
        out.append(f"In {r.jurisdiction}, the license named is the installer's {LICENSE_KINDS[r.jurisdiction][needed]}")
    if lic.expires_on is not None and lic.expires_on < today:
        out.append(f"That license expired on {lic.expires_on.isoformat()}")
    return out


@dataclass(frozen=True)
class Status:
    in_service: bool
    why: str                     # "" when in service; else: never | voided | moved


def status(latest_controller_door: Optional[str], voided: bool, door_controller_door: str) -> Status:
    """A door's state from its newest record (None: never commissioned)."""
    if latest_controller_door is None:
        return Status(False, "never")
    if voided:
        return Status(False, "voided")
    if latest_controller_door != door_controller_door:
        return Status(False, "moved")
    return Status(True, "")


def expiring(expires_on: Optional[date], today: date, within_days: int = 30) -> bool:
    return expires_on is not None and (expires_on - today).days <= within_days

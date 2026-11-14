"""The demo organization's PhotonEntry part (docs/DEMO.md; photon-suite DEMO.md): what it holds, worked out from fixed seeds so every seed
gives the same people, cards and doors.

Everything here is fictional: names from two short lists, addresses on `example.com`, no phone numbers. The directory holds the organization and
its sites under fixed IDs (id1, 2026-11-14), the same in development and production.
"""
from __future__ import annotations

import random
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

ORG = uuid.UUID("3560c835-5885-442d-bf55-6e250e4b5190")
HQ = uuid.UUID("72a17302-e998-4a17-9459-dbc61c4ea410")
WAREHOUSE = uuid.UUID("736b1e29-7f84-40a8-b06b-1495902f7d2f")
APARTMENTS = uuid.UUID("e8088684-45b6-45f3-aebc-5e0efc638a3c")
# Who the audit trail names for what the seed does. A fixed id that is no person's.
SEED_ACTOR = uuid.UUID("00000000-0000-4000-8000-00000000de30")
INSTALLER = "Demo Integrations LLC (fictional)"
HISTORY_DAYS = 30
KEEP_EVENTS_DAYS = 45


@dataclass(frozen=True)
class ControllerSpec:
    key: str                  # how the simulators and the seed name it
    name: str
    model: str                # what entry-link reports (ENTRY_LINK_MODEL)
    doors: int                # A1610: 2, A1210: 1
    local_port: int           # entry-link's endpoint for the intercoms, on the simulators' own loopback


@dataclass(frozen=True)
class DoorSpec:
    slot: str                 # the template's door slot, also the driver's name for the door
    controller: str
    door: int                 # the controller's door 1 or 2
    name: str
    lock_type: str
    egress: str


@dataclass(frozen=True)
class IntercomSpec:
    name: str
    door: str                 # slot
    model: str
    mac: str                  # locally administered (02:...): never a real device's


@dataclass(frozen=True)
class PeopleSpec:
    tag: str                  # what the driver does with them
    count: int
    groups: Tuple[str, ...]   # template group keys
    pin: bool = False         # a PIN as well as a card
    card: bool = True
    ref: str = "employee"     # employee | unit | vendor


@dataclass(frozen=True)
class SiteSpec:
    slug: str                 # the directory's (permanent, unique across the suite)
    prefix: str               # employees' references start with it
    id: uuid.UUID
    state: str                # for the commissioning records
    facility: int             # the site's 26-bit card facility code
    controllers: Tuple[ControllerSpec, ...]
    templates: Tuple[Tuple[str, Tuple[str, ...], Dict[str, bool]], ...]   # (template, its door slots, options)
    doors: Tuple[DoorSpec, ...]
    intercoms: Tuple[IntercomSpec, ...]
    people: Tuple[PeopleSpec, ...]
    visitors_door: Optional[str] = None      # a visitors' group on this door in business hours, with passes


A1610, A1210 = "AXIS A1610", "AXIS A1210"
EXIT = "Panic bar, free egress"
LEVER = "Lever handle, free egress"

SITES: Tuple[SiteSpec, ...] = (
    SiteSpec(
        "demo-hq", "HQ", HQ, "PA", 41,
        controllers=(ControllerSpec("hq-lobby", "HQ lobby", A1610, 2, 18701), ControllerSpec("hq-upstairs", "HQ upstairs", A1610, 2, 18702)),
        templates=(("office", ("main_entrance", "staff_entrance", "suite_door", "server_room"), {"unlock_main": False}),),
        doors=(DoorSpec("main_entrance", "hq-lobby", 1, "Main entrance", "exit_device", EXIT),
               DoorSpec("staff_entrance", "hq-lobby", 2, "Staff entrance", "strike_fail_secure", EXIT),
               DoorSpec("suite_door", "hq-upstairs", 1, "Executive suite", "lever_fail_secure", LEVER),
               DoorSpec("server_room", "hq-upstairs", 2, "Server room", "lever_fail_secure", LEVER)),
        intercoms=(IntercomSpec("Front intercom", "main_entrance", "S532", "0250DE000101"),),
        people=(PeopleSpec("staff", 36, ("staff",)), PeopleSpec("manager", 4, ("staff", "managers")), PeopleSpec("it", 2, ("staff", "it")),
                PeopleSpec("cleaning", 3, ("cleaning",), pin=True), PeopleSpec("former", 1, ("staff",))),
        visitors_door="main_entrance",
    ),
    SiteSpec(
        "demo-warehouse", "WH", WAREHOUSE, "PA", 52,
        controllers=(ControllerSpec("wh-gate", "Yard gate", A1210, 1, 18703), ControllerSpec("wh-office", "Warehouse office", A1610, 2, 18704)),
        templates=(("gate", ("vehicle_gate",), {"open_vehicle_gate": True}),
                   ("office", ("main_entrance", "staff_entrance"), {"unlock_main": False})),
        doors=(DoorSpec("vehicle_gate", "wh-gate", 1, "Vehicle gate", "gate_operator", "Pedestrian gate beside it"),
               DoorSpec("main_entrance", "wh-office", 1, "Office entrance", "exit_device", EXIT),
               DoorSpec("staff_entrance", "wh-office", 2, "Dock entrance", "strike_fail_secure", EXIT)),
        intercoms=(),
        people=(PeopleSpec("employee", 22, ("users", "staff")), PeopleSpec("manager", 2, ("users", "staff", "managers")),
                PeopleSpec("driver", 6, ("deliveries",), ref="vendor")),
    ),
    SiteSpec(
        "demo-apartments", "RA", APARTMENTS, "WV", 63,
        controllers=(ControllerSpec("apt-lobby", "Lobby", A1610, 2, 18705), ControllerSpec("apt-back", "Back of house", A1610, 2, 18706)),
        templates=(("multifamily", ("lobby", "garage", "package_room", "amenity"), {}),),
        doors=(DoorSpec("lobby", "apt-lobby", 1, "Lobby entrance", "exit_device", EXIT),
               DoorSpec("garage", "apt-lobby", 2, "Rear entrance", "strike_fail_secure", EXIT),
               DoorSpec("package_room", "apt-back", 1, "Package room", "lever_fail_secure", LEVER),
               DoorSpec("amenity", "apt-back", 2, "Fitness center", "lever_fail_secure", LEVER)),
        intercoms=(IntercomSpec("Lobby intercom", "lobby", "E12V2", "0250DE000201"),),
        people=(PeopleSpec("resident", 48, ("residents",), ref="unit"), PeopleSpec("property", 3, ("staff",)),
                PeopleSpec("maintenance", 2, ("maintenance",)), PeopleSpec("courier", 4, ("vendors",), pin=True, card=False, ref="vendor"),
                PeopleSpec("moved_out", 1, ("residents",), ref="unit")),
    ),
)
SITE_BY_SLUG = {s.slug: s for s in SITES}
CONTROLLERS = {c.key: c for s in SITES for c in s.controllers}

FIRST = ["Avery", "Blake", "Casey", "Dana", "Elliot", "Frankie", "Gray", "Harper", "Indy", "Jordan", "Kai", "Logan", "Morgan", "Noel", "Oakley",
         "Parker", "Quinn", "Reese", "Sage", "Taylor", "Umi", "Val", "Wren", "Xen", "Yael", "Zion", "Arden", "Briar", "Cove", "Drew"]
LAST = ["Abernathy", "Bellweather", "Calloway", "Dunmore", "Ellery", "Fairbanks", "Galloway", "Hartwell", "Ingram", "Jessop", "Kincaid",
        "Lockhart", "Merriweather", "Northcott", "Oakhurst", "Pemberton", "Quill", "Ravenscroft", "Stroud", "Thistlewood", "Underhill", "Vance",
        "Whitlock", "Yardley", "Zeller"]
COMPANIES = ["Northbound Couriers", "Three Rivers Freight", "Allegheny Parcel", "Riverbend Delivery", "Keystone Linehaul", "Ohio Valley Express"]


@dataclass
class Person:
    site: str
    tag: str
    name: str
    ref: str
    email: str
    groups: Tuple[str, ...]
    card: Optional[int] = None               # the 26-bit card number (the site's facility code)
    pin: Optional[str] = None
    suspended: bool = False
    card_expired: bool = False
    extra: Dict[str, str] = field(default_factory=dict)


def people() -> List[Person]:
    """Every cardholder, the same on every run: names unique across the organization, cards unique per site, PINs unique (the organization's
    rule: one PIN, one person)."""
    rnd = random.Random(20261114)
    names = [f"{f} {last}" for f in FIRST for last in LAST]
    rnd.shuffle(names)
    pins = rnd.sample(range(100000, 999999), 200)
    out: List[Person] = []
    for site in SITES:
        cards = rnd.sample(range(1000, 65000), 200)
        unit = 0
        for spec in site.people:
            for n in range(spec.count):
                name = names.pop()
                if spec.ref == "unit":
                    unit += 1
                    ref = f"Unit {100 * (1 + (unit - 1) // 12) + (unit - 1) % 12 + 1}"
                elif spec.ref == "vendor":
                    ref = f"{COMPANIES[len(out) % len(COMPANIES)]} #{len(out) + 1}"
                else:
                    ref = f"{site.prefix}-{len(out) + 1001}"
                first, last = name.split(" ", 1)
                out.append(Person(site=site.slug, tag=spec.tag, name=name, ref=ref, email=f"{first}.{last}@example.com".lower(), groups=spec.groups,
                                  card=cards.pop() if spec.card else None, pin=f"{pins.pop()}" if spec.pin else None,
                                  suspended=spec.tag == "moved_out", card_expired=spec.tag == "former"))
    return out

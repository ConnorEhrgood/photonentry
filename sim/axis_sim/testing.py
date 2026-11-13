"""The simulator as tests drive it: a simulated A1610 with a movable clock, called through its real HTTP API (Basic auth) and its control API."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from axis_sim.device import Device
from axis_sim.server import SimClock, create_app

MAC = "00408c184bdb"
DOOR1, DOOR2 = f"Axis-{MAC}:door1", f"Axis-{MAC}:door2"
R1IN, R1OUT, R2IN = f"Axis-{MAC}:reader1in", f"Axis-{MAC}:reader1out", f"Axis-{MAC}:reader2in"


class Sim:
    def __init__(self, max_limit: int = 100) -> None:
        self.clock = SimClock()
        self.device = Device(mac=MAC, doors=2, tz="America/New_York", clock=self.clock)
        self.client = TestClient(create_app(self.device, max_limit=max_limit))
        self.auth = ("root", "pass")

    def call(self, endpoint: str, method: str, msg: Dict[str, Any] | None = None, status: int = 200) -> Dict[str, Any]:
        r = self.client.post(f"/vapix/{endpoint}", json={method: msg or {}}, auth=self.auth)
        assert r.status_code == status, r.text
        return r.json()

    def at(self, local: str) -> None:
        """Move the controller's clock to a local time, e.g. "2026-11-16 10:00" (a Monday)."""
        target = datetime.fromisoformat(local).replace(tzinfo=ZoneInfo(self.device.tz)).astimezone(timezone.utc)
        self.clock.offset = target - datetime.now(timezone.utc)
        with self.device.lock:
            self.device.tick()

    def card(self, idpoint: str, value: str):
        return self.client.post("/sim/present", json={"idpoint": idpoint, "id_data": [{"Name": "Card", "Value": value}]}).json()

    def pin(self, idpoint: str, value: str):
        return self.client.post("/sim/present", json={"idpoint": idpoint, "id_data": [{"Name": "PIN", "Value": value}]}).json()

    def door(self, token: str, state: str) -> None:
        self.client.post("/sim/door", json={"door": token, "state": state})

    def state(self, door: str) -> Dict[str, str]:
        return self.client.get("/sim/state").json()["doors"][door]

    def topics(self) -> List[str]:
        return ["/".join(kv["Value"] for kv in sorted((k for k in e["KeyValues"] if k["Key"].startswith("topic")), key=lambda k: k["Key"]))
                for e in self.device.log]


def inventory(sim: Sim) -> Dict[str, List[str]]:
    """Door token -> its access points, read from the simulator as entry-link reads a controller."""
    aps = sim.call("pacs", "pacsaxis:GetAccessPointList")["AccessPoint"]
    doors = sim.call("doorcontrol", "axtdc:GetDoorList")["Door"]
    return {d["token"]: sorted(a["token"] for a in aps if a["Entity"] == d["token"]) for d in doors}


def apply_settings(sim: Sim, settings: Dict[str, Any]) -> None:
    """Apply compiled settings in dependency order (what entry-link does on a fresh controller; it also removes stale `pe-` objects)."""
    def put(endpoint: str, method: str, key: str, items: List[Dict[str, Any]]) -> None:
        if items:
            sim.call(endpoint, method, {key: items})

    put("schedule", "axsch:SetSchedule", "Schedule", settings["schedules"])
    put("pacs", "pacsaxis:SetAccessProfile", "AccessProfile", settings["access_profiles"])
    put("pacs", "axudb:SetUser", "User", settings["users"])
    put("pacs", "pacsaxis:SetCredential", "Credential", settings["credentials"])
    put("doorcontrol", "axtdc:SetDoorScheduleConfiguration", "DoorScheduleConfiguration", settings["door_schedules"])
    for d in settings["doors"]:
        door = sim.call("doorcontrol", "axtdc:GetDoor", {"Token": [d["token"]]})["Door"][0]
        door.update({k: d[k] for k in ("Name", "AccessTime", "OpenTooLongTime", "PreAlarmTime")})
        sim.call("doorcontrol", "axtdc:SetDoor", {"Door": [door]})
        cfg = sim.call("doorcontrol", "axtdc:GetDoorConfiguration", {"Token": [d["token"]]})["DoorConfiguration"][0]
        cfg["DoorScheduleConfiguration"] = d["DoorScheduleConfiguration"]
        sim.call("doorcontrol", "axtdc:SetDoorConfiguration", {"DoorConfiguration": [cfg]})

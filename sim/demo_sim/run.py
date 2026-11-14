"""The demo's simulators (docs/DEMO.md §2): six simulated Axis controllers, the real `entry-link` on each, two simulated Akuvox intercoms and the
driver that plays the sites' days on them, back-filled 30 days, then live.

    python -m demo_sim run      # the container's command (deploy/demo/)

Files in the state folder (`DEMO_STATE`, a volume):
- `claims.json`   {controller key: claim code}, written once every entry-link has one: `scripts/demo.sh` hands it to the seed;
- `roster.json`   the seed's answer (app/demo/seed.py), piped back by `scripts/demo.sh`: cards, doors, intercoms;
- `history.done`  the history is written (it is written once);
- `devices/`      each controller's snapshot (a restart keeps its settings and log), `link/<key>/` each entry-link's own state.
"""
from __future__ import annotations

import heapq
import itertools
import json
import logging
import os
import random
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from axis_sim.device import Device
from axis_sim.server import SimClock
from demo_sim import plan
from demo_sim.intercom import Intercom

log = logging.getLogger("demo_sim")

# The six controllers: key -> (doors, model, VAPIX port, entry-link's intercom port). The ports match app/demo (local_port).
CONTROLLERS: Dict[str, Tuple[int, str, int, int]] = {
    "hq-lobby": (2, "AXIS A1610", 18801, 18701), "hq-upstairs": (2, "AXIS A1610", 18802, 18702),
    "wh-gate": (1, "AXIS A1210", 18803, 18703), "wh-office": (2, "AXIS A1610", 18804, 18704),
    "apt-lobby": (2, "AXIS A1610", 18805, 18705), "apt-back": (2, "AXIS A1610", 18806, 18706),
}
TICK_EVERY = timedelta(minutes=10)          # the history's timer runs (door schedules); live, the simulator's own ticker runs them
LOG_ROWS = 3000                             # each controller's log: a day of history fits; ~7 MB each (a full 30,000 would be ~70 MB)
CALLERS = ["201", "202", "205", "210", "214"]  # the extensions that answer (internal numbers, never a phone number)


def mac_of(key: str) -> str:
    return f"0250de0000{list(CONTROLLERS).index(key) + 1:02x}"


def reader(key: str, door: int, side: str) -> str:
    return f"Axis-{mac_of(key)}:reader{door}{side}"


def door_token(key: str, door: int) -> str:
    return f"Axis-{mac_of(key)}:door{door}"


# -- carrying out a plan ---------------------------------------------------------------------------------------------------------------------------


@dataclass(order=True)
class Step:
    at: datetime
    n: int
    controller: str = field(compare=False)
    do: Callable[[Device], None] = field(compare=False)
    outside: bool = field(default=False, compare=False)    # an HTTP request to entry-link: made without holding the controller's lock


class Executor:
    """Runs actions as steps on the controllers, in time order. `live=False` (the history): each step moves its controller's clock to the step's
    time, so the controller decides and logs as it would have then. `live=True`: the caller runs what is due on the real clock, and intercom
    calls go through the intercoms and entry-link."""

    def __init__(self, devices: Dict[str, Device], clocks: Dict[str, SimClock], intercoms: Dict[str, Intercom], live: bool,
                 now: Callable[[], datetime] = lambda: datetime.now(timezone.utc), seed: int = 0) -> None:
        self.devices, self.clocks, self.intercoms, self.live = devices, clocks, intercoms, live
        self.now = now
        self.heap: List[Step] = []
        self.count = itertools.count()
        self.rnd = random.Random(seed)
        self.done = {"badge": 0, "granted": 0, "denied": 0, "force": 0, "hold": 0, "vehicle": 0, "call": 0, "opened_from_intercom": 0}
        self.lock = threading.Lock()

    def at(self, when: datetime, controller: str, do: Callable[[Device], None], outside: bool = False) -> None:
        with self.lock:
            heapq.heappush(self.heap, Step(when, next(self.count), controller, do, outside))

    def walk(self, when: datetime, controller: str, door: int, open_s: float = 0.0) -> None:
        """Someone goes through: the door opens a moment later and closes behind them."""
        token = door_token(controller, door)
        start = when + timedelta(seconds=self.rnd.uniform(1.5, 3))
        self.at(start, controller, lambda d: d.set_physical(token, "Open"))
        self.at(start + timedelta(seconds=open_s or self.rnd.uniform(3, 6)), controller, lambda d: d.set_physical(token, "Closed"))

    def add(self, a: plan.Action) -> None:
        token = door_token(a.controller, a.door)
        self.done[a.kind] += 1
        if a.kind in ("badge", "hold"):
            def present(d: Device, a: plan.Action = a) -> None:
                granted, _ = d.present(reader(a.controller, a.door, a.side), a.credential())
                self.done["granted" if granted else "denied"] += 1
                if granted:
                    when = d.now_utc()
                    self.walk(when, a.controller, a.door, open_s=a.seconds if a.kind == "hold" else 0.0)
                    if a.kind == "hold" and not self.live:      # the history runs the held-open timers itself
                        for s in range(5, int(a.seconds) + 5, 5):
                            self.at(when + timedelta(seconds=s), a.controller, lambda d: None)
            self.at(a.at, a.controller, present)
        elif a.kind in ("force", "vehicle"):
            self.at(a.at, a.controller, lambda d, t=token: d.set_physical(t, "Open"))
            self.at(a.at + timedelta(seconds=a.seconds), a.controller, lambda d, t=token: d.set_physical(t, "Closed"))
        elif a.kind == "call":
            self._call(a, token)

    def _call(self, a: plan.Action, token: str) -> None:
        caller = self.rnd.choice(CALLERS)
        answer_at = a.at + timedelta(seconds=a.seconds)
        end_at = answer_at + timedelta(seconds=self.rnd.uniform(4, 12)) if a.answered else a.at + timedelta(seconds=30)
        if not self.live:
            # The history: the events entry-link would have recorded for the intercom, written into the controller's log (docs/DEMO.md §2).
            src = {"DoorToken": token, "IntercomId": a.intercom}

            def started(d: Device) -> None:
                d.record(["PhotonEntry", "Intercom", "CallStarted"], src, {"Caller": caller})

            def opened(d: Device) -> None:
                ok = d.access_door(token)
                d.record(["PhotonEntry", "Intercom", "Unlock"], src, {"Caller": caller, "Result": "ok" if ok else "failed"})
                if ok:
                    self.done["opened_from_intercom"] += 1
                    self.walk(d.now_utc(), a.controller, a.door)

            self.at(a.at, a.controller, started)
            if a.answered:
                self.at(answer_at, a.controller, opened)
            self.at(end_at, a.controller, lambda d: d.record(["PhotonEntry", "Intercom", "CallEnded"], src, {"Caller": caller}))
            return
        icom = self.intercoms.get(a.intercom)
        if icom is None:
            return
        # Live: the intercom itself, over HTTP to entry-link; entry-link records the events and opens the door; the watcher walks through.
        self.at(a.at, a.controller, lambda d: icom.call_start(caller), outside=True)
        if a.answered:
            def relay(d: Device) -> None:
                if icom.unlock() == 200:
                    self.done["opened_from_intercom"] += 1
            self.at(answer_at, a.controller, relay, outside=True)
        self.at(end_at, a.controller, lambda d: icom.call_end(caller), outside=True)

    def ticks(self, start: datetime, end: datetime) -> None:
        """The history's timer runs: door schedules change at their times (the vehicle gate opens at 7)."""
        for key in self.devices:
            t = start
            while t < end:
                self.at(t, key, lambda d: None)
                t += TICK_EVERY

    def run(self, until: datetime, stop: Optional[threading.Event] = None) -> int:
        """Carry out every step due before `until`, in time order. Returns the steps run."""
        n = 0
        while not (stop and stop.is_set()):
            with self.lock:
                if not self.heap or self.heap[0].at >= until:
                    return n
                step = heapq.heappop(self.heap)
            self._perform(step)
            n += 1
        return n

    def _perform(self, step: Step) -> None:
        d = self.devices[step.controller]
        try:
            if step.outside:
                step.do(d)
                return
            with d.lock:
                if not self.live:
                    self.clocks[step.controller].offset = step.at - datetime.now(timezone.utc)
                d.tick()
                step.do(d)
        except Exception as e:  # noqa: BLE001 - one odd step (a door locked down meanwhile) must not stop the demo
            log.warning("step at %s on %s: %s", step.at.isoformat(), step.controller, e)

    def back_to_now(self) -> None:
        for key, d in self.devices.items():
            with d.lock:
                self.clocks[key].offset = timedelta(0)
                d.tick()


def history(site_rosters: List[Dict[str, Any]], devices: Dict[str, Device], clocks: Dict[str, SimClock], days: int, now: datetime,
            wait_read: Optional[Callable[[], None]] = None) -> Dict[str, int]:
    """Write `days` of the sites' days into the controllers' logs, ending now, a day at a time. `wait_read` waits until entry-link has read
    what was written (the demo's controllers keep a short log: LOG_ROWS)."""
    ex = Executor(devices, clocks, {}, live=False, seed=days)
    start = now - timedelta(days=days)
    for s in site_rosters:
        for a in plan.between(plan.Site.from_roster(s), start, now):
            ex.add(a)
    ex.ticks(start, now)
    t = start
    while t < now:
        t = min(t + timedelta(days=1), now)
        ex.run(until=t)
        if wait_read:
            wait_read()
    ex.back_to_now()
    return ex.done


def read_up(devices: Dict[str, Device], timeout_s: float = 600.0, sleep: Callable[[float], None] = time.sleep) -> bool:
    """Wait until every controller's reader (entry-link) has asked for rows after the newest one: all is read."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if all(not d.log or d.read_to >= d.log[-1]["rowid"] for d in devices.values()):
            return True
        sleep(0.2)
    log.warning("entry-link is behind on reading the history; going on")
    return False


class Watcher:
    """Live: a door opened remotely (from the app, or an intercom's web relay) has someone walk through it, as a person would."""

    def __init__(self, ex: Executor) -> None:
        self.ex = ex
        self.seen: Dict[Tuple[str, str], Optional[datetime]] = {}

    def check(self) -> int:
        n = 0
        for key, d in self.ex.devices.items():
            with d.lock:
                for token, rt in d.runtime.items():
                    remote = rt.mode == "Accessed" and rt.accessed_by is None and rt.physical == "Closed"
                    if remote and self.seen.get((key, token)) != rt.accessed_until:
                        self.seen[(key, token)] = rt.accessed_until
                        self.ex.walk(self.ex.now(), key, int(token.rsplit("door", 1)[1]))
                        n += 1
        return n


# -- the process -----------------------------------------------------------------------------------------------------------------------------------


class Runner:
    def __init__(self, state: Path, cloud: str, provision: str, entry_link: str) -> None:
        self.state, self.cloud, self.provision, self.entry_link = state, cloud.rstrip("/"), provision.rstrip("/"), entry_link
        self.devices: Dict[str, Device] = {}
        self.clocks: Dict[str, SimClock] = {}
        self.procs: Dict[str, subprocess.Popen] = {}
        self.servers: List[Any] = []
        self.stop = threading.Event()

    def start_devices(self) -> None:
        from axis_sim.server import run as serve
        (self.state / "devices").mkdir(parents=True, exist_ok=True)
        for key, (doors, _model, port, _local) in CONTROLLERS.items():
            clock = SimClock()
            d = Device(mac=mac_of(key), doors=doors, tz="America/New_York", clock=clock, log_capacity=LOG_ROWS)
            snap = self.state / "devices" / f"{key}.json"
            if snap.exists():
                d.restore(json.loads(snap.read_text()))
                log.info("%s: restored (%d events in its log)", key, len(d.log))
            self.devices[key], self.clocks[key] = d, clock
            server, _ = serve(d, port=port)
            self.servers.append(server)

    def start_links(self) -> None:
        for key, (_doors, model, port, local) in CONTROLLERS.items():
            folder = self.state / "link" / key
            folder.mkdir(parents=True, exist_ok=True)
            env = dict(os.environ, ENTRY_LINK_CLOUD=self.cloud, ENTRY_LINK_STATE_DIR=str(folder), ENTRY_LINK_VAPIX=f"http://127.0.0.1:{port}",
                       ENTRY_LINK_VAPIX_USER="root", ENTRY_LINK_VAPIX_PASS="pass", ENTRY_LINK_MODEL=model, ENTRY_LINK_SERIAL=mac_of(key).upper(),
                       ENTRY_LINK_FIRMWARE="12.6.1", ENTRY_LINK_LOCAL_BIND="127.0.0.1", ENTRY_LINK_LOCAL_PORT=str(local),
                       ENTRY_LINK_EVENT_POLL_MS="250")
            out = open(folder / "entry-link.log", "a")
            self.procs[key] = subprocess.Popen([self.entry_link], env=env, stdout=out, stderr=out)

    def claims(self, timeout_s: float = 60.0) -> Dict[str, str]:
        deadline = time.monotonic() + timeout_s
        while True:
            codes = {}
            for key in CONTROLLERS:
                f = self.state / "link" / key / "state.json"
                try:
                    code = json.loads(f.read_text()).get("claim_code", "")
                except (OSError, ValueError):
                    code = ""
                if code:
                    codes[key] = code
            if len(codes) == len(CONTROLLERS) or time.monotonic() > deadline:
                return codes
            time.sleep(0.5)

    def settled(self, roster: Dict[str, Any]) -> bool:
        """Every controller holds the cards the seed gave it (the settings arrived)."""
        return all(any(t.startswith("pe-c-") for t in d.store["Credential"]) for d in self.devices.values())

    def snapshot(self) -> None:
        for key, d in self.devices.items():
            with d.lock:
                data = json.dumps(d.snapshot())
            tmp = self.state / "devices" / f"{key}.json.tmp"
            tmp.write_text(data)
            tmp.replace(self.state / "devices" / f"{key}.json")

    def intercoms(self, roster: Dict[str, Any]) -> Dict[str, Intercom]:
        out = {}
        for s in roster["sites"]:
            for i in s["intercoms"]:
                out[i["id"]] = Intercom(i["id"], i["mac"], f"{self.provision}{i['provision_path']}")
        return out

    def main(self) -> None:
        signal.signal(signal.SIGTERM, lambda *_: self.stop.set())
        self.start_devices()
        self.start_links()
        codes = self.claims()
        (self.state / "claims.json").write_text(json.dumps(codes))
        log.info("claim codes ready for %d controller(s)", len(codes))
        roster_file = self.state / "roster.json"
        while not roster_file.exists() and not self.stop.is_set():
            time.sleep(1)
        if self.stop.is_set():
            return self.shutdown()
        roster = json.loads(roster_file.read_text())
        while not self.settled(roster) and not self.stop.is_set():
            time.sleep(1)
        if not (self.state / "history.done").exists():
            done = history(roster["sites"], self.devices, self.clocks, roster.get("history_days", 30), datetime.now(timezone.utc),
                           wait_read=lambda: read_up(self.devices))
            log.info("history written: %s", json.dumps(done))
            self.snapshot()
            (self.state / "history.done").write_text(json.dumps(done))
        self.live(roster)
        self.shutdown()

    def live(self, roster: Dict[str, Any]) -> None:
        icoms = self.intercoms(roster)
        ex = Executor(self.devices, self.clocks, icoms, live=True, seed=int(time.time()))
        watcher = Watcher(ex)
        sites = [plan.Site.from_roster(s) for s in roster["sites"]]
        planned_to = datetime.now(timezone.utc)
        last_fetch = last_snap = 0.0
        while not self.stop.is_set():
            now = datetime.now(timezone.utc)
            if planned_to < now + timedelta(hours=1):
                for site in sites:
                    for a in plan.between(site, planned_to, planned_to + timedelta(hours=6)):
                        ex.add(a)
                planned_to += timedelta(hours=6)
            if time.monotonic() - last_fetch >= 3600:
                last_fetch = time.monotonic()
                for i in icoms.values():
                    if not i.provision_now():
                        log.warning("intercom %s: settings not fetched", i.mac)
            if time.monotonic() - last_snap >= 600:
                last_snap = time.monotonic()
                self.snapshot()
            watcher.check()
            ex.run(until=datetime.now(timezone.utc), stop=self.stop)
            self.stop.wait(0.5)

    def shutdown(self) -> None:
        if self.devices:
            self.snapshot()
        for p in self.procs.values():
            p.send_signal(signal.SIGTERM)
        for p in self.procs.values():
            try:
                p.wait(10)
            except subprocess.TimeoutExpired:
                p.kill()
        for s in self.servers:
            s.should_exit = True

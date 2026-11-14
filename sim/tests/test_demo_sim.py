"""The demo's simulators (docs/DEMO.md): the sites' days, the history on the simulated controllers, a restart, the simulated intercom and the
walk through a remotely opened door."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List

import pytest

from axis_sim.device import Device
from axis_sim.server import SimClock
from demo_sim import plan, run
from demo_sim.intercom import Intercom, parse

HOLIDAY = "2026-11-26"


def person(tag: str, n: int, pin: bool = False, card: bool = True) -> Dict:
    return {"name": f"{tag} {n}", "tag": tag, "card": f"{0x1000000 + n * 7 + len(tag):08x}" if card else None, "pin": f"{4000 + n}" if pin else None}


def roster() -> List[Dict]:
    """Shaped like the seed's (app/demo/seed.py), with made-up cards."""
    def site(slug, doors, people, intercoms=()):
        return {"slug": slug, "timezone": "America/New_York", "holidays": [HOLIDAY], "doors": doors, "people": people, "intercoms": list(intercoms)}
    return [
        site("demo-hq", {"main_entrance": {"controller": "hq-lobby", "door": 1}, "staff_entrance": {"controller": "hq-lobby", "door": 2},
                         "suite_door": {"controller": "hq-upstairs", "door": 1}, "server_room": {"controller": "hq-upstairs", "door": 2}},
             [person("staff", n) for n in range(36)] + [person("manager", n) for n in range(4)] + [person("it", n) for n in range(2)]
             + [person("cleaning", n, pin=True) for n in range(3)] + [person("former", 0)],
             [{"id": "icom-hq", "name": "Front intercom", "door": "main_entrance", "mac": "0250DE000101"}]),
        site("demo-warehouse", {"vehicle_gate": {"controller": "wh-gate", "door": 1}, "main_entrance": {"controller": "wh-office", "door": 1},
                                "staff_entrance": {"controller": "wh-office", "door": 2}},
             [person("employee", n) for n in range(22)] + [person("manager", n) for n in range(2)] + [person("driver", n) for n in range(6)]),
        site("demo-apartments", {"lobby": {"controller": "apt-lobby", "door": 1}, "garage": {"controller": "apt-lobby", "door": 2},
                                 "package_room": {"controller": "apt-back", "door": 1}, "amenity": {"controller": "apt-back", "door": 2}},
             [person("resident", n) for n in range(48)] + [person("property", n) for n in range(3)] + [person("maintenance", n) for n in range(2)]
             + [person("courier", n, pin=True, card=False) for n in range(4)] + [person("moved_out", 0)],
             [{"id": "icom-apt", "name": "Lobby intercom", "door": "lobby", "mac": "0250DE000201"}]),
    ]


def sites() -> Dict[str, plan.Site]:
    return {s["slug"]: plan.Site.from_roster(s) for s in roster()}


def devices():
    devs, clocks = {}, {}
    for key, (doors, *_rest) in run.CONTROLLERS.items():
        clocks[key] = SimClock()
        devs[key] = Device(mac=run.mac_of(key), doors=doors, clock=clocks[key], log_capacity=run.LOG_ROWS)
    return devs, clocks


MONDAY = date(2026, 11, 16)


def test_a_day_is_the_same_however_often_it_is_planned_and_differs_by_kind():
    s = sites()
    assert plan.day(s["demo-hq"], MONDAY) == plan.day(s["demo-hq"], MONDAY)
    weekday = plan.day(s["demo-hq"], MONDAY)
    sunday = plan.day(s["demo-hq"], MONDAY - timedelta(days=1))
    holiday = plan.day(s["demo-hq"], date.fromisoformat(HOLIDAY))
    assert len(weekday) > 80 and len(sunday) < 10 and len(holiday) < 10
    kinds = Counter(a.kind for a in weekday)
    assert kinds["call"] >= 5 and kinds["badge"] > 60
    # Office hours in Pittsburgh: arrivals from 7:30 local, the intercom from 9 to 17.
    calls = [a.at.astimezone(s["demo-hq"].tz) for a in weekday if a.kind == "call"]
    assert all(9 <= c.hour < 17 for c in calls)
    assert min(a.at.astimezone(s["demo-hq"].tz) for a in weekday if a.who.startswith("staff")).hour >= 7


def test_every_site_has_its_own_events_and_a_day_fits_the_short_log():
    s = sites()
    for slug, wanted in (("demo-hq", {"badge", "call", "force"}), ("demo-warehouse", {"badge", "vehicle"}),
                         ("demo-apartments", {"badge", "call"})):
        week = [a for n in range(7) for a in plan.day(s[slug], MONDAY + timedelta(days=n))]
        assert wanted <= {a.kind for a in week}, slug
        assert {a.kind for a in week} & {"force", "hold"}, slug                                # an alarm in a week at every site
        for n in range(7):
            assert all(v < run.LOG_ROWS for v in plan.rows_per_controller(plan.day(s[slug], MONDAY + timedelta(days=n))).values())
    # The warehouse's dock door is held open now and then, and the gate opens for vehicles only on working days.
    month = [a for n in range(30) for a in plan.day(s["demo-warehouse"], MONDAY + timedelta(days=n))]
    assert any(a.kind == "hold" for a in month)
    assert all(a.at.astimezone(s["demo-warehouse"].tz).weekday() < 5 for a in month if a.kind == "vehicle")
    # Couriers use their PIN; cleaners sometimes do.
    apt = [a for n in range(7) for a in plan.day(s["demo-apartments"], MONDAY + timedelta(days=n))]
    assert any(a.id_data and a.id_data[0][0] == "PIN" for a in apt if a.who.startswith("courier"))


def test_between_takes_the_window_across_days():
    s = sites()["demo-apartments"]
    start = datetime(2026, 11, 16, 3, 0, tzinfo=timezone.utc)
    got = plan.between(s, start, start + timedelta(days=2))
    assert got and all(start <= a.at < start + timedelta(days=2) for a in got)
    assert got == sorted(got, key=lambda a: (a.at, a.controller, a.door))


def test_the_history_runs_on_the_controllers_in_the_past_and_returns_to_now():
    devs, clocks = devices()
    now = datetime(2026, 11, 14, 20, 0, tzinfo=timezone.utc)
    reads: List[int] = []
    done = run.history(roster(), devs, clocks, 3, now, wait_read=lambda: reads.append(1))
    assert len(reads) == 3                                                    # a day at a time
    assert done["badge"] > 300 and done["call"] > 20 and done["denied"] > 0    # no settings on these controllers: every card is unknown
    assert done["opened_from_intercom"] > 0                                   # the intercom's relay opens the door whatever the cards
    times = [r["UtcTime"] for r in devs["apt-lobby"].log]
    assert min(times) < (now - timedelta(days=2)).isoformat() and max(times) < now.isoformat()
    topics = Counter("/".join(kv["Value"] for kv in sorted((k for k in r["KeyValues"] if k["Key"].startswith("topic")), key=lambda k: k["Key"]))
                     for r in devs["apt-lobby"].log)
    assert topics["PhotonEntry/Intercom/CallStarted"] and topics["PhotonEntry/Intercom/Unlock"] and topics["PhotonEntry/Intercom/CallEnded"]
    assert all(c.offset == timedelta(0) for c in clocks.values())
    rows = [r for r in devs["hq-lobby"].log if any(kv["Value"] == "DoorAlarm" for kv in r["KeyValues"])]
    assert rows                                                               # forced doors


def test_read_up_waits_for_the_reader():
    devs, _ = devices()
    d = devs["hq-lobby"]
    newest = d.log[-1]["rowid"]
    assert run.read_up(devs, timeout_s=0.01, sleep=lambda s: None) is False
    for dev in devs.values():
        dev.fetch_events(dev.log[-1]["rowid"])
    assert d.read_to == newest and run.read_up(devs, timeout_s=0.01) is True


def test_a_snapshot_brings_a_controller_back_after_a_restart():
    devs, clocks = devices()
    d = devs["hq-lobby"]
    d.present(run.reader("hq-lobby", 1, "in"), [{"Name": "Card", "Value": "00000001"}])
    d.set_physical(run.door_token("hq-lobby", 2), "Open")
    snap = d.snapshot()
    again = Device(mac=d.mac, doors=2, clock=clocks["hq-lobby"], log_capacity=run.LOG_ROWS)
    again.restore(snap)
    assert again.log == d.log and again.runtime[run.door_token("hq-lobby", 2)].physical == "Open"
    again.present(run.reader("hq-lobby", 1, "in"), [{"Name": "Card", "Value": "00000001"}])
    assert again.log[-1]["rowid"] > d.log[-1]["rowid"]
    with pytest.raises(ValueError):
        Device(mac="0250de0000ff", doors=2).restore(snap)


def test_the_intercom_reads_its_settings_and_calls_with_them():
    cfg = ("# PhotonEntry\n\nConfig.Features.ACTIONURL.MakeCall = http://127.0.0.1:18705/v1/event?intercom=i&key=k&kind=call_start&remote=$remote\n"
           "Config.Features.ACTIONURL.HangUp = http://127.0.0.1:18705/v1/event?intercom=i&key=k&kind=call_end&remote=$remote\n"
           "Config.DoorSetting.WEBRELAY.WebRelay_Action_1 = http://127.0.0.1:18705/v1/relay?intercom=i&key=k\n")
    assert parse(cfg)["Config.DoorSetting.WEBRELAY.WebRelay_Action_1"].endswith("key=k")
    got, asked = [], []
    i = Intercom("i", "0250de000201", "https://prov.test/provision/v1/tok/", get=lambda u: got.append(u) or 200,
                 fetch=lambda u: asked.append(u) or (cfg if u.endswith("0250DE000201.cfg") else "# general"))
    assert i.unlock() == 0                                                     # nothing fetched yet: nothing to call
    assert i.provision_now() is True
    assert asked == ["https://prov.test/provision/v1/tok/r000000000532.cfg", "https://prov.test/provision/v1/tok/0250DE000201.cfg"]
    assert (i.call_start("201"), i.unlock(), i.call_end("201")) == (200, 200, 200)
    assert got[0].endswith("kind=call_start&remote=201") and got[1].endswith("/v1/relay?intercom=i&key=k")
    lost = Intercom("i", "0250de000201", "https://prov.test/x/", get=lambda u: 200, fetch=lambda u: None)
    assert lost.provision_now() is False and lost.call_start("201") == 0 and lost.call_end("201") == 0


def test_live_calls_go_through_the_intercom_and_a_remote_unlock_is_walked_through():
    devs, clocks = devices()
    got: List[str] = []

    class FakeIntercom:
        def call_start(self, caller):
            got.append("start")
            return 200

        def unlock(self):
            got.append("unlock")
            with devs["apt-lobby"].lock:
                devs["apt-lobby"].access_door(run.door_token("apt-lobby", 1))       # what entry-link does on the web relay
            return 200

        def call_end(self, caller):
            got.append("end")
            return 200
    now = datetime.now(timezone.utc)
    ex = run.Executor(devs, clocks, {"icom-apt": FakeIntercom()}, live=True)
    ex.add(plan.Action(now, "call", "apt-lobby", 1, seconds=1, answered=True, intercom="icom-apt"))
    ex.add(plan.Action(now, "call", "apt-lobby", 1, seconds=1, answered=True, intercom="gone"))         # an intercom no longer there
    ex.run(until=now + timedelta(minutes=1))
    assert got == ["start", "unlock", "end"] and ex.done["opened_from_intercom"] == 1
    watcher = run.Watcher(ex)
    assert watcher.check() == 1 and watcher.check() == 0                      # one walk per unlock
    ex.run(until=now + timedelta(minutes=1))
    door = devs["apt-lobby"].runtime[run.door_token("apt-lobby", 1)]
    assert door.physical == "Closed"
    # A step that fails (a door action on a door that is not there) is logged and skipped.
    ex.at(now, "apt-lobby", lambda d: d.set_physical("Axis-nope:door9", "Open"))
    assert ex.run(until=now + timedelta(minutes=1)) == 1

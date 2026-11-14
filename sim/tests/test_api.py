"""The simulator speaks VAPIX as Axis documents it: calling convention, faults, authentication, paging, the event log."""
from __future__ import annotations

import httpx

from axis_sim.testing import DOOR1, R1IN, Sim


def test_requests_without_credentials_are_challenged_for_digest_and_basic(sim):
    r = sim.client.post("/vapix/pacs", json={"pacsaxis:GetAccessControllerList": {}})
    assert r.status_code == 401
    challenges = r.headers.get_list("www-authenticate")
    assert any(c.startswith("Digest realm=\"AXIS_00408C184BDB\"") and 'qop="auth"' in c for c in challenges)
    assert any(c.startswith("Basic") for c in challenges)
    assert sim.client.post("/vapix/pacs", json={"pacsaxis:GetAccessControllerList": {}}, auth=("root", "wrong")).status_code == 401


def test_digest_authentication(sim):
    r = sim.client.post("/vapix/pacs", json={"pacsaxis:GetAccessControllerList": {}}, auth=httpx.DigestAuth("root", "pass"))
    assert r.status_code == 200 and r.json()["AccessController"][0]["token"] == "Axis-00408c184bdb AccessController"


def test_responses_are_the_bare_message(sim):
    out = sim.call("pacs", "pacsaxis:GetAccessControllerList")
    assert set(out) == {"AccessController"} and len(out["AccessController"][0]["AccessPoint"]) == 3
    assert sim.call("doorcontrol", "tdc:AccessDoor", {"Token": DOOR1}) == {}
    assert sim.call("doorcontrol", "tdc:GetDoorState", {"Token": DOOR1})["DoorState"]["DoorMode"] == "Accessed"


def test_faults(sim):
    f = sim.call("doorcontrol", "tdc:GetDoorState", {"Token": "nope"}, status=400)
    assert f == {"Fault": "env:Sender", "FaultCode": "ter:InvalidArgVal", "FaultSubCode": "ter:NotFound", "FaultReason": "Invalid argument",
                 "FaultMsg": "Token 'nope' not found"}
    assert sim.call("pacs", "pacsaxis:NoSuchMethod", status=400)["FaultCode"] == "ter:InvalidArgVal"
    assert sim.call("pacs", "axsch:GetScheduleList", status=400)["FaultCode"] == "ter:InvalidArgVal"     # wrong endpoint for the prefix
    r = sim.client.post("/vapix/pacs", content=b"{nope", auth=sim.auth)
    assert r.status_code == 400
    r = sim.client.post("/vapix/pacs", json={"a:B": {}, "c:D": {}}, auth=sim.auth)
    assert r.status_code == 400
    assert sim.client.post("/vapix/nothing", json={}, auth=sim.auth).status_code == 404
    assert sim.call("doorcontrol", "axtdc:RemoveDoor", {"Token": [DOOR1]}, status=500)["FaultSubCode"] == "ter:NotSupported"


def test_set_get_remove_and_generated_tokens(sim):
    out = sim.call("pacs", "axudb:SetUser", {"User": [{"token": "", "Name": "Smith, Alice", "Attribute": []}, {"token": "pe-u-b", "Name": "B"}]})
    generated = out["Token"][0]
    assert generated.startswith("Axis-00408c184bdb:") and out["Token"][1] == "pe-u-b"
    assert sim.call("pacs", "axudb:GetUser", {"Token": [generated, "unknown"]})["User"][0]["Name"] == "Smith, Alice"
    assert sim.call("pacs", "axudb:RemoveUser", {"Token": ["pe-u-b"]}) == {}
    assert sim.call("pacs", "axudb:RemoveUser", {"Token": ["pe-u-b"]}, status=400)["FaultSubCode"] == "ter:NotFound"


def test_set_checks_references(sim):
    bad = {"token": "c", "IdData": [{"Name": "Card", "Value": "01"}], "CredentialAccessProfile": [{"AccessProfile": "nope"}]}
    assert sim.call("pacs", "pacsaxis:SetCredential", {"Credential": [bad]}, status=400)["FaultSubCode"] == "ter:InvalidCredentialFault"
    profile = {"token": "p", "Name": "P", "Schedule": ["standard_always"], "AccessPolicy": [{"AccessPoint": "nope", "Schedule": []}]}
    assert sim.call("pacs", "pacsaxis:SetAccessProfile", {"AccessProfile": [profile]}, status=400)["FaultSubCode"] == "ter:InvalidAccessProfileFault"
    sched = {"token": "s", "Name": "S", "ScheduleDefinition": "BEGIN:VCALENDAR\nBEGIN:VEVENT\nDTSTART:20000103T080000Z\nEND:VEVENT\nEND:VCALENDAR\n"}
    assert sim.call("schedule", "axsch:SetSchedule", {"Schedule": [sched]}, status=400)["FaultSubCode"] == "ter:InvalidScheduleFault"
    dsc = {"token": "d", "DoorSchedule": [{"ScheduledState": [{"ScheduleToken": ["nope"], "EnterAction": "Unlock"}]}]}
    assert sim.call("doorcontrol", "axtdc:SetDoorScheduleConfiguration", {"DoorScheduleConfiguration": [dsc]}, status=400)["FaultSubCode"] == \
        "ter:InvalidDoorScheduleFault"
    cfg = sim.call("doorcontrol", "axtdc:GetDoorConfiguration", {"Token": [DOOR1]})["DoorConfiguration"][0]
    assert sim.call("doorcontrol", "axtdc:SetDoorConfiguration", {"DoorConfiguration": [{**cfg, "DoorScheduleConfiguration": "nope"}]},
                    status=400)["FaultSubCode"] == "ter:InvalidDoorConfigurationFault"
    dup = [{"token": "x", "IdData": [{"Name": "CardNr", "Value": "5"}]}, {"token": "y", "IdData": [{"Name": "CardNr", "Value": "5"}]}]
    assert sim.call("pacs", "pacsaxis:SetCredential", {"Credential": dup}, status=400)["FaultSubCode"] == "ter:InvalidCredentialFault"
    assert sim.call("schedule", "axsch:RemoveSchedule", {"Token": ["standard_always"]}, status=500)["FaultSubCode"] == "ter:NotSupported"


def test_lists_are_paged():
    sim = Sim(max_limit=2)
    sim.call("pacs", "axudb:SetUser", {"User": [{"token": f"u{n}", "Name": f"U{n}"} for n in range(5)]})
    seen, ref = [], None
    while True:
        out = sim.call("pacs", "axudb:GetUserList", {"StartReference": ref} if ref else {})
        seen += [u["token"] for u in out["User"]]
        ref = out.get("NextStartReference")
        if not ref:
            break
    assert seen == [f"u{n}" for n in range(5)]
    assert sim.call("pacs", "axudb:GetUserList", {"StartReference": "zz"}, status=400)["FaultSubCode"] == "ter:InvalidStartReference"
    assert sim.call("pacs", "axudb:GetUser", {"Token": ["u0", "u1", "u2"]}, status=400)["FaultSubCode"] == "ter:TooManyItems"
    info = sim.call("pacs", "axudb:GetUserInfoList", {"Limit": 1})
    assert info["UserInfo"] == [{"token": "u0", "Name": "U0"}] and info["NextStartReference"] == "1"


def test_event_log_is_read_by_row_id(sim):
    first, more = sim.device.fetch_events()
    assert not more and first[-1]["rowid"] == len(sim.device.log)
    sim.card(R1IN, "deadbeef")
    out = sim.call("eventlogger", "axlog:FetchEvents", {"RowID": first[-1]["rowid"], "Limit": 1})
    assert out["More"] is True and len(out["Event"]) == 1
    ev = out["Event"][0]
    keys = {kv["Key"]: kv for kv in ev["KeyValues"]}
    assert keys["topic0"]["Value"] == "IdPoint" and ev["UUID"] == "5581ad80-95b0-11e0-b883-00408c184bdb" and ev["UtcTime"].endswith("Z")
    rest = sim.call("eventlogger", "axlog:FetchEvents", {"RowID": ev["rowid"]})
    denied = rest["Event"][-1]
    keys = {kv["Key"]: kv for kv in denied["KeyValues"]}
    assert [keys[f"topic{n}"]["Value"] for n in range(4)] == ["AccessControl", "Denied", "CredentialNotFound", "Card"]
    assert keys["Card"]["Value"] == "deadbeef" and keys["AccessPointToken"]["Tags"] == ["wstype:pt:ReferenceToken", "onvif-source"]
    filtered = sim.call("eventlogger", "axlog:FetchEvents", {"Filters": [{"Key": "topic1", "Value": "Denied"}]})["Event"]
    assert len(filtered) == 1
    assert sim.call("eventlogger", "axlog:FetchEvents", {"Descending": True, "Limit": 1})["Event"][0]["rowid"] == denied["rowid"]


def test_the_log_keeps_its_capacity(sim):
    sim.device.log_capacity = 10                       # 30,000 on a real controller (EVENT_LOG_CAPACITY); the demo keeps fewer
    for _ in range(10):
        sim.card(R1IN, "00")
    assert len(sim.device.log) == 10 and sim.device.log[0]["rowid"] > 1


def test_outage_and_control_api(sim):
    sim.client.post("/sim/offline", json={"offline": True})
    assert sim.client.post("/vapix/pacs", json={"pacsaxis:GetAccessControllerList": {}}, auth=sim.auth).status_code == 503
    sim.client.post("/sim/offline", json={"offline": False})
    assert sim.client.post("/sim/clock", json={"offset_s": 60}).json() == {"ok": True}
    assert sim.client.get("/sim/state").json()["counts"]["Door"] == 2

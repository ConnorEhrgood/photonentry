"""The PhotonVox client (app/vox.py) against the contract (contract/vox/): what it accepts, and every way it refuses."""
from __future__ import annotations

import copy
import json
import pathlib
import uuid
from datetime import datetime, timezone

import httpx
import jsonschema
import pytest

from app import crypto, vox
from app.models import CallMatch, Intercom

CONTRACT = pathlib.Path(__file__).resolve().parents[3] / "contract" / "vox"
STATIONS = json.loads((CONTRACT / "door-stations.sample.json").read_text())
CALL = json.loads((CONTRACT / "door-call.sample.json").read_text())
ORG = uuid.UUID(STATIONS["organization_id"])
AT = datetime(2026, 11, 14, 15, 2, 20, tzinfo=timezone.utc)


def test_the_samples_follow_the_contract():
    jsonschema.validate(STATIONS, json.loads((CONTRACT / "door-stations.schema.json").read_text()))
    jsonschema.validate(CALL, json.loads((CONTRACT / "door-call.schema.json").read_text()))


def answer(status, body):
    asked = []

    def fetch(url, token, params):
        asked.append((url, token, params))
        return status, body
    return fetch, asked


def test_door_stations_and_a_call():
    fetch, asked = answer(200, STATIONS)
    [s] = vox.stations(fetch, "tok", ORG)
    assert (s.id, s.extension, s.sip.transport, s.sip.password) == ("front-door", "150", "udp", "Rk2v9QpL4xT7mW1z")
    assert asked[0][:2] == ("https://api.vox.photonind.com/integrations/entry/v1/door-stations", "tok")
    fetch, asked = answer(200, CALL)
    call = vox.door_call(fetch, "tok", ORG, "front-door", AT)
    assert call.answered_by.name == "Front desk (Ann Lee)" and call.ended_at is None
    assert asked[0][2] == {"station": "front-door", "at": AT.isoformat(), "window_s": "120"}
    fetch, _ = answer(200, {**CALL, "call": None})
    assert vox.door_call(fetch, "tok", ORG, "front-door", AT) is None


def unreachable(url, token, params):
    raise httpx.ConnectError("down")


@pytest.mark.parametrize("fetch,words", [
    (unreachable, "could not be reached (ConnectError)"),
    (answer(401, None)[0], "refused the token"),
    (answer(403, {"detail": "scope"})[0], "vox:entry"),
    (answer(500, None)[0], "HTTP 500"),
    (answer(200, {"organization_id": str(ORG)})[0], "not what PhotonEntry expects"),
    (answer(200, {**STATIONS, "extra": 1})[0], "not what PhotonEntry expects"),
    (answer(200, {**STATIONS, "organization_id": str(uuid.uuid4())})[0], "another organization"),
])
def test_every_refusal_is_a_sentence_never_data(fetch, words):
    with pytest.raises(vox.VoxError, match=words.replace("(", r"\(").replace(")", r"\)")):
        vox.stations(fetch, "tok", ORG)


def test_a_call_about_another_station_or_a_missing_one():
    fetch, _ = answer(200, {**CALL, "station_id": "ds-other"})
    with pytest.raises(vox.VoxError, match="another door station"):
        vox.door_call(fetch, "tok", ORG, "front-door", AT)
    with pytest.raises(vox.NotFound):
        vox.door_call(answer(404, None)[0], "tok", ORG, "front-door", AT)


def test_a_station_s_sip_account_onto_an_intercom():
    [s] = vox.stations(answer(200, STATIONS)[0], "tok", ORG)
    i = Intercom(sip_server="", sip_port=5061, sip_transport="tls", sip_user="", sip_password_sealed="", vox_station_id="", sip_outbound_proxy="")
    assert vox.copy_sip(i, s, AT) is True
    assert (i.vox_station_id, i.sip_server, i.sip_user, i.sip_synced_at) == ("front-door", "cedar-works.pbx.photonind.com", "150", AT)
    assert crypto.unseal(i.sip_password_sealed) == "Rk2v9QpL4xT7mW1z" and "Rk2v9" not in i.sip_password_sealed
    assert vox.copy_sip(i, s, AT) is False                                         # unchanged: nothing to give the intercom
    assert i.sip_outbound_proxy == ""
    rotated = copy.deepcopy(STATIONS)
    rotated["stations"][0]["sip"]["password"] = "NewPassword123456"
    rotated["stations"][0]["sip"]["outbound_proxy"] = "sbc.photonind.com:5060"
    [s2] = vox.stations(answer(200, rotated)[0], "tok", ORG)
    assert vox.copy_sip(i, s2, AT) is True and crypto.unseal(i.sip_password_sealed) == "NewPassword123456"
    assert i.sip_outbound_proxy == "sbc.photonind.com:5060"
    bad = copy.deepcopy(STATIONS)
    bad["stations"][0]["sip"]["outbound_proxy"] = "no port here"
    with pytest.raises(vox.VoxError, match="not what PhotonEntry expects"):
        vox.stations(answer(200, bad)[0], "tok", ORG)


def test_how_the_events_name_who_answered():
    assert vox.answered(None) is None
    assert vox.answered(CallMatch(state="none")) is None
    assert vox.answered(CallMatch(state="found", name="Ann Lee", extension="101")) == "Ann Lee (101)"
    assert vox.answered(CallMatch(state="found", name="", extension="101")) == "101"


def test_the_real_fetch_reads_json_or_nothing(monkeypatch):
    class R:
        status_code = 200

        def __init__(self, text):
            self.text = text

        def json(self):
            return json.loads(self.text)
    monkeypatch.setattr(httpx, "get", lambda url, params, headers, timeout: R('{"a": 1}') if params else R("<html>"))
    assert vox.http_get("https://x", "t", {"p": "1"}) == (200, {"a": 1})
    assert vox.http_get("https://x", "t", {}) == (200, None)

#!/usr/bin/env python3
"""PhotonEntry's PhotonVox client against a running PhotonVox (docs/VOX.md), read-only: the door stations, a station's SIP account onto an
intercom and into its Akuvox file, the call behind a door, and a refused token. For the development PhotonVox on LXC 800, never production.
  VOX_API_URL=http://10.10.0.80:8113 VOX_TOKEN_FILE=<file> VOX_ORG=<directory organization id> ~/.venvs/photonentry/bin/python scripts/vox-dev-check.py
The token is read from a file and never printed."""
import json
import os
import pathlib
import sys
import uuid
from datetime import datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))
os.environ.setdefault("SECRETS_KEY", "dGVzdC1zZWNyZXRzLWtleS1mb3ItcGhvdG9uZW50cnk=")   # a throwaway key: nothing is stored
import jsonschema  # noqa: E402

from app import akuvox, crypto, vox  # noqa: E402
from app.config import settings  # noqa: E402
from app.models import Intercom  # noqa: E402

url = os.environ["VOX_API_URL"]
assert "photonind.com" not in url, "development PhotonVox only"
settings.vox_api_url = url
token = pathlib.Path(os.environ["VOX_TOKEN_FILE"]).read_text().strip()
org = uuid.UUID(os.environ["VOX_ORG"])
schemas = {n: json.loads((ROOT / "contract" / "vox" / f"{n}.schema.json").read_text()) for n in ("door-stations", "door-call")}
now = datetime.now(timezone.utc)
ok = lambda what: print(f"ok   {what}")  # noqa: E731

status, body = vox.http_get(f"{url}/integrations/entry/v1/door-stations", token, {})
assert status == 200, status
jsonschema.validate(body, schemas["door-stations"])
stations = vox.stations(vox.http_get, token, org)
ok(f"door stations: {', '.join(f'{s.id} ({s.extension}, proxy {s.sip.outbound_proxy})' for s in stations)}; valid against the contract")

s = stations[0]
i = Intercom(sip_server="", sip_port=5061, sip_transport="tls", sip_user="", sip_password_sealed="", vox_station_id="", sip_outbound_proxy="")
assert vox.copy_sip(i, s, now) and not vox.copy_sip(i, s, now)
text = akuvox.render(akuvox.Device(id="ic-check", name="Check", relay_target="127.0.0.1:8742", relay_secret="k", admin_password="a",
                                   provision_url="https://prov.example/", sip_server=i.sip_server, sip_port=i.sip_port,
                                   sip_transport=i.sip_transport, sip_user=i.sip_user, sip_password=crypto.unseal(i.sip_password_sealed),
                                   sip_outbound_proxy=i.sip_outbound_proxy))
lines = dict(l.split(" = ", 1) for l in text.splitlines() if " = " in l)
host, _, port = s.sip.outbound_proxy.rpartition(":") if s.sip.outbound_proxy else ("", "", "")
assert lines["Config.Account1.SIP.Server"] == s.sip.server and lines["Config.Account1.GENERAL.UserName"] == s.sip.username
assert lines["Config.Account1.OUTPROXY.Enable"] == ("1" if host else "0") and lines["Config.Account1.OUTPROXY.Server"] == host
assert lines["Config.Account1.OUTPROXY.Port"] == port and lines["Config.Account1.SIP.TransType"] == str(akuvox.TRANSPORT[s.sip.transport])
ok(f"station {s.id}: SIP account onto an intercom, and into its Akuvox file (server {s.sip.server}, outbound proxy {host or 'off'}:{port})")

found = None
for minutes in (1, 5, 15, 60, 240, 1440):
    at = now - timedelta(minutes=minutes)
    status, body = vox.http_get(f"{url}/integrations/entry/v1/door-calls", token, {"station": s.id, "at": at.isoformat(), "window_s": "600"})
    assert status == 200, status
    jsonschema.validate(body, schemas["door-call"])
    found = vox.door_call(vox.http_get, token, org, s.id, at)
    if found:
        break
if found:
    a = found.answered_by
    ok(f"door-calls: call {found.id[:8]}… started {found.started_at:%H:%M:%S}, answered by {a.name} ({a.extension}) "
       f"→ the events would say \"Answered by {a.name} ({a.extension})\"")
else:
    ok("door-calls: valid answers, no call from that station in the last day")
status, _ = vox.http_get(f"{url}/integrations/entry/v1/door-calls", token, {"station": s.id, "at": "not-a-time", "window_s": "60"})
assert status == 400, status
ok("a bad time: 400")
try:
    vox.door_call(vox.http_get, token, org, "no-such-door", now)
    raise AssertionError("an unknown station was answered")
except vox.NotFound:
    ok("an unknown station: 404 (NotFound)")
try:
    vox.stations(vox.http_get, "pvx_entry_wrong_token_0123456789", org)
    raise AssertionError("a wrong token was accepted")
except vox.VoxError as e:
    assert "refused the token" in str(e)
    ok("a wrong token: refused (401)")
try:
    vox.stations(vox.http_get, token, uuid.uuid4())
    raise AssertionError("an answer for another organization was taken")
except vox.VoxError as e:
    assert "another organization" in str(e)
    ok("connected for another organization: refused")

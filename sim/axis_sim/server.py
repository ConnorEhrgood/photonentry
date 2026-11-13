"""The simulator's HTTP side: the VAPIX JSON endpoints, with Axis's calling convention, faults and authentication, and a control API for tests.

    POST /vapix/doorcontrol   tdc + axtdc        POST /vapix/pacs       tac + pacsaxis + axudb
    POST /vapix/schedule      axsch              POST /vapix/idpoint    axtid
    POST /vapix/eventlogger   axlog

Body `{"prefix:Method": {...}}`; the response is the message itself (`{}` when empty, `{"Token": [...]}` for every Set). A fault is HTTP 400
(`env:Sender`) or 500 (`env:Receiver`) with Axis's JSON fault body (the status codes are INFERRED: Axis documents none).

Authentication: HTTP Digest (MD5, qop=auth, realm `AXIS_<MAC>`) or Basic, both offered on a 401, as the device does depending on its policy.

    /sim/...   the test harness's control API (no authentication; the simulator is only ever bound to loopback): present a credential at a
               reader, open or close a door, move the clock, take the device offline, read its state.
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from axis_sim import ical
from axis_sim.device import Device, Fault, _seconds, not_found

# kind -> (store name, its "Info" fields or None); Get/Set/Remove/List methods are generated from this table.
OBJECTS = {
    "Door": ("Door", ["token", "Name", "Description"]),
    "DoorConfiguration": ("DoorConfiguration", None),
    "DoorScheduleConfiguration": ("DoorScheduleConfiguration", None),
    "AccessPoint": ("AccessPoint", ["token", "Name", "Description", "AreaFrom", "AreaTo", "EntityType", "Entity"]),
    "AccessController": ("AccessController", ["token", "Name", "Description"]),
    "AuthenticationProfile": ("AuthenticationProfile", ["token", "Name", "Description"]),
    "AccessProfile": ("AccessProfile", ["token", "Name", "Description"]),
    "Credential": ("Credential", ["token", "UserToken", "Description", "ValidFrom", "ValidTo", "Enabled", "Status"]),
    "User": ("User", ["token", "Name", "Description"]),
    "Schedule": ("Schedule", ["token", "Name", "Description"]),
    "IdPoint": ("IdPoint", ["token", "Name", "Location", "Area", "Description"]),
    "IdPointConfiguration": ("IdPointConfiguration", None),
}
ENDPOINT_PREFIXES = {
    "doorcontrol": {"tdc", "axtdc"}, "pacs": {"tac", "pacsaxis", "axudb"}, "schedule": {"axsch"}, "idpoint": {"axtid"}, "eventlogger": {"axlog"},
}
# Which object kinds each endpoint serves.
ENDPOINT_OBJECTS = {
    "doorcontrol": {"Door", "DoorConfiguration", "DoorScheduleConfiguration"},
    "pacs": {"AccessPoint", "AccessController", "AuthenticationProfile", "AccessProfile", "Credential", "User"},
    "schedule": {"Schedule"}, "idpoint": {"IdPoint", "IdPointConfiguration"}, "eventlogger": set(),
}
DOOR_ACTIONS = {"LockDoor": "Lock", "UnlockDoor": "Unlock", "BlockDoor": "Block", "LockDownDoor": "LockDown",
                "LockDownReleaseDoor": "LockDownRelease", "LockOpenDoor": "LockOpen", "LockOpenReleaseDoor": "LockOpenRelease",
                "DoubleLockDoor": "DoubleLock"}


def _invalid(sub: str, msg: str) -> Fault:
    return Fault("env:Sender", "ter:InvalidArgVal", sub, msg)


class Api:
    def __init__(self, device: Device, max_limit: int = 100) -> None:
        self.dev = device
        self.max_limit = max_limit          # INFERRED: Axis documents no MaxLimit; small enough that clients must page

    # -- generic object methods ---------------------------------------------------------------------------------------------------------------

    def _list(self, kind: str, msg: Dict[str, Any], info: bool) -> Dict[str, Any]:
        items = sorted(self.dev.store[OBJECTS[kind][0]].values(), key=lambda o: o["token"])
        start = msg.get("StartReference") or ""
        offset = 0
        if start:
            if not start.isdigit() or int(start) > len(items):
                raise _invalid("ter:InvalidStartReference", "Invalid StartReference")
            offset = int(start)
        limit = msg.get("Limit") or self.max_limit
        limit = self.max_limit if limit < 1 or limit > self.max_limit else limit
        page = items[offset: offset + limit]
        out: Dict[str, Any] = {self._key(kind, info): [self._view(kind, o, info) for o in page]}
        if offset + limit < len(items):
            out["NextStartReference"] = str(offset + limit)
        return out

    def _get(self, kind: str, msg: Dict[str, Any], info: bool) -> Dict[str, Any]:
        tokens = msg.get("Token") or []
        if isinstance(tokens, str):
            tokens = [tokens]
        if len(tokens) > self.max_limit:
            raise Fault("env:Sender", "ter:InvalidArgs", "ter:TooManyItems", "Too many items")
        store = self.dev.store[OBJECTS[kind][0]]
        return {self._key(kind, info): [self._view(kind, store[t], info) for t in tokens if t in store]}

    @staticmethod
    def _key(kind: str, info: bool) -> str:
        return f"{kind}Info" if info else kind

    @staticmethod
    def _view(kind: str, obj: Dict[str, Any], info: bool) -> Dict[str, Any]:
        fields = OBJECTS[kind][1]
        return {k: obj[k] for k in fields if k in obj} if info and fields else dict(obj)

    def _set(self, kind: str, msg: Dict[str, Any]) -> Dict[str, Any]:
        items = msg.get(kind)
        if not isinstance(items, list) or not items:
            raise Fault("env:Sender", "ter:InvalidArgs", "", f"{kind} list required")
        store = self.dev.store[OBJECTS[kind][0]]
        staged = []
        for obj in items:
            obj = dict(obj)
            if not obj.get("token"):
                obj["token"] = self.dev.new_token()
            if len(obj["token"]) > 64:
                raise Fault("env:Sender", "ter:InvalidArgs", "", "token longer than 64 characters")
            if "Name" in obj and len(obj["Name"]) > 64 and kind not in ("User",):
                raise Fault("env:Sender", "ter:InvalidArgs", "", "Name longer than 64 characters")
            if kind == "DoorConfiguration" and obj["token"] not in self.dev.store["Door"]:
                raise _invalid("ter:InvalidDoorConfigurationFault", "No door with that token")
            if kind == "Door" and obj["token"] not in self.dev.runtime:
                raise Fault("env:Receiver", "ter:ActionNotSupported", "ter:NotSupported", "New doors are made by commissioning (simulator)")
            self._validate(kind, obj, staged)
            staged.append(obj)
        for obj in staged:
            store[obj["token"]] = obj
        if kind in ("DoorConfiguration", "DoorScheduleConfiguration", "Schedule"):
            for door, rt in self.dev.runtime.items():
                rt.schedule_state = None                 # Axis: the enter action is generated again when the configuration is set
        self.dev.tick()
        return {"Token": [o["token"] for o in staged]}

    def _validate(self, kind: str, obj: Dict[str, Any], staged: List[Dict[str, Any]]) -> None:
        """The checks a controller makes before it stores an object. References to other objects must exist (INFERRED: Axis documents the
        fault names, not every check; being strict here makes the client prove its order of operations)."""
        st = self.dev.store
        if kind == "Schedule":
            try:
                ical.parse(obj.get("ScheduleDefinition", ""))
                ical.parse(obj.get("ExceptionScheduleDefinition") or "")
            except ical.InvalidSchedule as e:
                raise _invalid("ter:InvalidScheduleFault", str(e)) from e
        elif kind == "AccessProfile":
            for t in obj.get("Schedule", []):
                if t not in st["Schedule"]:
                    raise _invalid("ter:InvalidAccessProfileFault", f"Schedule '{t}' not found")
            for pol in obj.get("AccessPolicy", []):
                if pol.get("AccessPoint") not in st["AccessPoint"]:
                    raise _invalid("ter:InvalidAccessProfileFault", f"AccessPoint '{pol.get('AccessPoint')}' not found")
                for t in pol.get("Schedule", []):
                    if t not in st["Schedule"]:
                        raise _invalid("ter:InvalidAccessProfileFault", f"Schedule '{t}' not found")
        elif kind == "Credential":
            names = [d["Name"] for d in obj.get("IdData", [])]
            if len(names) != len(set(names)):
                raise _invalid("ter:InvalidCredentialFault", "IdData names must be unique")
            for cap in obj.get("CredentialAccessProfile", []):
                if cap.get("AccessProfile") not in st["AccessProfile"]:
                    raise _invalid("ter:InvalidCredentialFault", f"AccessProfile '{cap.get('AccessProfile')}' not found")
            card_nr = next((d["Value"] for d in obj.get("IdData", []) if d["Name"] == "CardNr"), None)
            if card_nr is not None:
                for other in list(st["Credential"].values()) + staged:
                    if other["token"] != obj["token"] and any(d["Name"] == "CardNr" and d["Value"] == card_nr for d in other.get("IdData", [])):
                        raise _invalid("ter:InvalidCredentialFault", f"CardNr {card_nr} is already used")
            for t in ("ValidFrom", "ValidTo"):
                if obj.get(t):
                    try:
                        datetime.fromisoformat(obj[t].replace("Z", "+00:00"))
                    except ValueError as e:
                        raise _invalid("ter:InvalidCredentialFault", f"bad {t}") from e
        elif kind == "DoorScheduleConfiguration":
            for ds in obj.get("DoorSchedule", []):
                for state in ds.get("ScheduledState", []):
                    for t in state.get("ScheduleToken", []):
                        if t not in st["Schedule"]:
                            raise _invalid("ter:InvalidDoorScheduleFault", f"Schedule '{t}' not found")
            if len(obj.get("DoorSchedule", [])) > 1 and any(not ds.get("PriorityLevel") for ds in obj["DoorSchedule"]):
                raise _invalid("ter:InvalidDoorScheduleFault", "DoorSchedule without PriorityLevel must be the only one")
        elif kind == "DoorConfiguration":
            link = obj.get("DoorScheduleConfiguration") or ""
            if link and link not in st["DoorScheduleConfiguration"]:
                raise _invalid("ter:InvalidDoorConfigurationFault", f"DoorScheduleConfiguration '{link}' not found")
        elif kind == "Door":
            for f in ("AccessTime", "OpenTooLongTime", "PreAlarmTime"):
                if f in obj:
                    _seconds(obj[f])

    def _remove(self, kind: str, msg: Dict[str, Any]) -> Dict[str, Any]:
        tokens = msg.get("Token") or []
        if isinstance(tokens, str):
            tokens = [tokens]
        store = self.dev.store[OBJECTS[kind][0]]
        if kind in ("Door", "AccessController"):
            raise Fault("env:Receiver", "ter:ActionNotSupported", "ter:NotSupported", f"Not allowed to remove the {kind}")
        for t in tokens:
            if t not in store:
                raise not_found(t)
        if kind == "Schedule" and "standard_always" in tokens:
            raise Fault("env:Receiver", "ter:ActionNotSupported", "ter:NotSupported", "standard_always cannot be removed")
        for t in tokens:
            del store[t]
        return {}

    # -- dispatch ---------------------------------------------------------------------------------------------------------------------------------

    def call(self, endpoint: str, body: Any) -> Dict[str, Any]:
        if not isinstance(body, dict) or len(body) != 1:
            raise Fault("env:Sender", "ter:InvalidArgVal", "", "Body must hold exactly one method")
        name, msg = next(iter(body.items()))
        prefix, _, method = name.partition(":")
        if prefix not in ENDPOINT_PREFIXES[endpoint] or not isinstance(msg, dict):
            raise Fault("env:Sender", "ter:InvalidArgVal", "", f"Unknown method {name}")
        self.dev.calls.append(name)
        self.dev.tick()
        result = self._method(endpoint, method, msg)
        if result is None:
            raise Fault("env:Sender", "ter:InvalidArgVal", "", f"Unknown method {name}")
        return result

    def _method(self, endpoint: str, method: str, msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        dev = self.dev
        for kind in ENDPOINT_OBJECTS[endpoint]:
            if method == f"Get{kind}InfoList" and OBJECTS[kind][1]:
                return self._list(kind, msg, info=True)
            if method == f"Get{kind}List":
                return self._list(kind, msg, info=False)
            if method == f"Get{kind}Info" and OBJECTS[kind][1]:
                return self._get(kind, msg, info=True)
            if method == f"Get{kind}":
                return self._get(kind, msg, info=False)
            if method == f"Set{kind}":
                return self._set(kind, msg)
            if method == f"Remove{kind}":
                return self._remove(kind, msg)
        if endpoint == "doorcontrol":
            if method == "GetDoorState":
                token = msg.get("Token", "")
                rt = dev.runtime.get(token)
                if rt is None:
                    raise not_found(token)
                return {"DoorState": {"DoorPhysicalState": rt.physical, "LockPhysicalState": "Unlocked" if rt.mode in (
                    "Unlocked", "Accessed", "LockedOpen") else "Locked", "Alarm": rt.alarm, "DoorMode": rt.mode}}
            if method == "AccessDoor":
                token = msg.get("Token", "")
                seconds = _seconds(msg["AccessTime"]) if msg.get("AccessTime") else None
                if not dev.access_door(token, seconds):
                    raise Fault("env:Receiver", "ter:Action", "ter:Failure", "Failed to go to Accessed state and unlock the door", "Failure")
                return {}
            if method in DOOR_ACTIONS:
                dev.door_action(msg.get("Token", ""), DOOR_ACTIONS[method])
                return {}
        if endpoint == "pacs":
            if method in ("EnableCredential", "DisableCredential"):
                c = dev.store["Credential"].get(msg.get("Token", ""))
                if c is None:
                    raise not_found(msg.get("Token", ""))
                enable = method == "EnableCredential"
                c["Enabled"], c["Status"] = enable, ("Enabled" if enable else msg.get("Status") or "Disabled")
                return {}
            if method in ("EnableAccessPoint", "DisableAccessPoint"):
                ap = dev.store["AccessPoint"].get(msg.get("Token", ""))
                if ap is None:
                    raise not_found(msg.get("Token", ""))
                ap["Enabled"] = method == "EnableAccessPoint"
                return {}
            if method == "GetCredentialStatistics":
                creds = dev.store["Credential"].values()
                return {"CredentialStatistics": {"NumberOfCredentials": len(creds),
                                                 "NumberOfDisabledCredentials": sum(1 for c in creds if not c.get("Enabled", True))}}
        if endpoint == "schedule" and method == "ScheduleActive":
            tokens = msg.get("Token") or []
            states = [dev.schedule_active(t) for t in tokens]
            return {"Active": any(a for a, _ in states) and not any(e for _, e in states), "Exception": any(e for _, e in states)}
        if endpoint == "idpoint" and method == "IndicateRemoteActivities":
            if msg.get("Token") not in dev.store["IdPoint"]:
                raise not_found(str(msg.get("Token")))
            for act in msg.get("Activities", []):
                params = act.get("Params", [])
                dev.present(msg["Token"], [{"Name": "REX", "Value": "Active"}] if act.get("Type") == "REX" else params)
            return {}
        if endpoint == "eventlogger" and method == "FetchEvents":
            events, more = dev.fetch_events(int(msg.get("RowID") or 0), msg.get("Limit") or 0, msg.get("Filters"), bool(msg.get("Descending")))
            return {"Event": events, "More": more}
        return None


class DigestAuth:
    """HTTP Digest (RFC 2617, MD5, qop=auth) and Basic, for one account. Nonces live 5 minutes."""

    def __init__(self, user: str, password: str, realm: str) -> None:
        self.user, self.password, self.realm = user, password, realm
        self.nonces: Dict[str, float] = {}
        self.lock = threading.Lock()

    def challenge(self) -> List[Tuple[str, str]]:
        nonce = secrets.token_hex(16)
        with self.lock:
            self.nonces[nonce] = time.monotonic()
        return [("WWW-Authenticate", f'Digest realm="{self.realm}", nonce="{nonce}", algorithm=MD5, qop="auth"'),
                ("WWW-Authenticate", f'Basic realm="{self.realm}"')]

    def check(self, header: Optional[str], method: str) -> bool:
        if not header:
            return False
        scheme, _, rest = header.partition(" ")
        if scheme == "Basic":
            try:
                user, _, pw = base64.b64decode(rest).decode().partition(":")
            except Exception:  # noqa: BLE001 - any undecodable header is simply not authenticated
                return False
            return secrets.compare_digest(user, self.user) and secrets.compare_digest(pw, self.password)
        if scheme != "Digest":
            return False
        p: Dict[str, str] = {}
        for part in _split(rest):
            k, _, v = part.strip().partition("=")
            p[k] = v.strip('"')
        with self.lock:
            born = self.nonces.get(p.get("nonce", ""))
        if born is None or time.monotonic() - born > 300 or p.get("username") != self.user or p.get("realm") != self.realm:
            return False
        ha1 = hashlib.md5(f"{self.user}:{self.realm}:{self.password}".encode()).hexdigest()
        ha2 = hashlib.md5(f"{method}:{p.get('uri', '')}".encode()).hexdigest()
        if p.get("qop") == "auth":
            want = hashlib.md5(f"{ha1}:{p['nonce']}:{p.get('nc', '')}:{p.get('cnonce', '')}:auth:{ha2}".encode()).hexdigest()
        else:
            want = hashlib.md5(f"{ha1}:{p['nonce']}:{ha2}".encode()).hexdigest()
        return secrets.compare_digest(want, p.get("response", ""))


def _split(text: str) -> List[str]:
    """Split a Digest header's parameters on commas outside quotes."""
    out, cur, quoted = [], "", False
    for ch in text:
        if ch == '"':
            quoted = not quoted
        if ch == "," and not quoted:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur)
    return out


def create_app(device: Device, user: str = "root", password: str = "pass", max_limit: int = 100) -> FastAPI:
    api = Api(device, max_limit)
    auth = DigestAuth(user, password, f"AXIS_{device.mac.upper()}")
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.api = api

    @app.post("/vapix/{endpoint}")
    async def vapix(endpoint: str, request: Request):
        if endpoint not in ENDPOINT_PREFIXES:
            return JSONResponse({"detail": "not found"}, status_code=404)
        if device.offline:
            return JSONResponse({"detail": "simulated outage"}, status_code=503)
        if not auth.check(request.headers.get("authorization"), "POST"):
            resp = JSONResponse({"detail": "unauthorized"}, status_code=401)
            for k, v in auth.challenge():
                resp.headers.append(k, v)
            return resp
        try:
            body = json.loads(await request.body())
        except ValueError:
            return JSONResponse(Fault("env:Sender", "ter:InvalidArgVal", "", "Malformed JSON").body, status_code=400)
        with device.lock:
            try:
                return JSONResponse(api.call(endpoint, body))
            except Fault as f:
                return JSONResponse(f.body, status_code=400 if f.body["Fault"] == "env:Sender" else 500)

    # -- the harness's control API ----------------------------------------------------------------------------------------------------------

    @app.post("/sim/present")
    async def present(request: Request):
        b = await request.json()
        with device.lock:
            device.tick()
            granted, reason = device.present(b["idpoint"], b["id_data"])
        return {"granted": granted, "reason": reason}

    @app.post("/sim/door")
    async def door(request: Request):
        b = await request.json()
        with device.lock:
            device.tick()
            device.set_physical(b["door"], b["state"])
        return {"ok": True}

    @app.post("/sim/offline")
    async def offline(request: Request):
        device.offline = bool((await request.json())["offline"])
        return {"ok": True}

    @app.post("/sim/clock")
    async def clock(request: Request):
        """Move the simulated clock: {"offset_s": seconds from real time}. Only when the device runs on a SimClock."""
        if not isinstance(device.clock, SimClock):
            return JSONResponse({"detail": "the device's clock is not movable"}, status_code=409)
        device.clock.offset = timedelta(seconds=float((await request.json())["offset_s"]))
        with device.lock:
            device.tick()
        return {"ok": True}

    @app.get("/sim/state")
    def state():
        with device.lock:
            device.tick()
            return {"doors": {t: {"mode": rt.mode, "physical": rt.physical, "alarm": rt.alarm} for t, rt in device.runtime.items()},
                    "counts": {k: len(v) for k, v in device.store.items()}, "events": len(device.log), "calls": len(device.calls)}

    return app


class SimClock:
    """Real time plus an offset the harness can move, so tests can jump to Christmas or 21:00 without waiting."""

    def __init__(self) -> None:
        self.offset = timedelta(0)

    def __call__(self) -> datetime:
        return datetime.now(timezone.utc) + self.offset


def run(device: Device, host: str = "127.0.0.1", port: int = 8134, **kw: Any) -> Tuple[Any, threading.Thread]:
    """Start the simulator in a thread (tests, scripts). Returns (server, thread); `server.should_exit = True` stops it."""
    import uvicorn
    config = uvicorn.Config(create_app(device, **kw), host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.02)
    def ticker() -> None:
        while not server.should_exit:
            with device.lock:
                device.tick()
            time.sleep(0.1)
    threading.Thread(target=ticker, daemon=True).start()
    return server, thread

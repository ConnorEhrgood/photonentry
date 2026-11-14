"""A simulated Akuvox intercom for the demo (docs/DEMO.md §2): it fetches its settings file from PhotonEntry's provisioning server, as the
device does every hour, and drives a call with the addresses that file gives it: the action URLs for the call's start and end, the web relay
to open the door. No SIP and no audio: the call itself is not simulated, only what PhotonEntry sees of it."""
from __future__ import annotations

from typing import Callable, Dict, Optional

import httpx

Get = Callable[[str], int]          # GET a URL; returns the HTTP status (0: no answer)


def parse(text: str) -> Dict[str, str]:
    """`Config.X.Y = value` lines (app/akuvox.py render); comments and blank lines skipped."""
    out = {}
    for line in text.splitlines():
        if line.startswith("#") or " = " not in line:
            continue
        k, v = line.split(" = ", 1)
        out[k.strip()] = v.strip()
    return out


def http_get(url: str) -> int:
    try:
        return httpx.get(url, timeout=10).status_code
    except httpx.HTTPError:
        return 0


class Intercom:
    def __init__(self, id: str, mac: str, provision: str, get: Get = http_get,
                 fetch: Optional[Callable[[str], Optional[str]]] = None) -> None:
        self.id, self.mac, self.provision = id, mac.upper(), provision      # provision: the base address plus the intercom's own path
        self.get = get
        self.fetch = fetch or self._fetch
        self.config: Dict[str, str] = {}

    @staticmethod
    def _fetch(url: str) -> Optional[str]:
        try:
            r = httpx.get(url, timeout=15)
        except httpx.HTTPError:
            return None
        return r.text if r.status_code == 200 else None

    def provision_now(self) -> bool:
        """What the device does at power-up and every hour: its model's general file, then its own MAC file. Keeps the last good settings."""
        self.fetch(f"{self.provision}r000000000532.cfg")
        text = self.fetch(f"{self.provision}{self.mac}.cfg")
        if text is None:
            return False
        self.config = parse(text)
        return True

    def _url(self, key: str, caller: str) -> str:
        return self.config.get(key, "").replace("$remote", caller)

    def call_start(self, caller: str) -> int:
        url = self._url("Config.Features.ACTIONURL.MakeCall", caller)
        return self.get(url) if url else 0

    def unlock(self) -> int:
        """The answering person presses the unlock code: the intercom calls its web relay (entry-link on the door's controller)."""
        url = self.config.get("Config.DoorSetting.WEBRELAY.WebRelay_Action_1", "")
        return self.get(url) if url else 0

    def call_end(self, caller: str) -> int:
        url = self._url("Config.Features.ACTIONURL.HangUp", caller)
        return self.get(url) if url else 0

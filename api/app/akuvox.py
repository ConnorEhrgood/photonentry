"""Akuvox intercoms: the settings file PhotonEntry makes for each one (CRITICAL: it decides what opens the door; ARCHITECTURE §3.4).

No SmartPlus. Each intercom fetches `<MAC>.cfg` from our provisioning server (app/routes/provision.py), at an address holding its own random
token, every hour. The keys and their sources are in sim/reference/AKUVOX-AUTOP.md; none is confirmed on a device yet (GATE H).

What the file makes of the intercom:
- **a card reader for the Axis controller:** 34-bit Wiegand out, its own card check off, so every card and PIN goes to the controller, which
  decides;
- **never a lock:** its relay is not wired, and its settings keep cards, DTMF and tamper away from it anyway; the only way it opens the door is
  the "web relay": during a call the person answering presses the unlock code, and the intercom asks entry-link on the door's controller;
- **a phone:** its SIP account in PhotonVox;
- **a reporter:** calls and tamper go to entry-link by action URLs;
- **ours:** a random admin password.

The file is served in clear over HTTPS: Akuvox's file encryption is undocumented (AKUVOX-AUTOP.md §3), and a wrong guess would leave the intercom
unable to read it. Its address is the secret: a random token per intercom, which only the site's admins can see.
"""
from __future__ import annotations

import hashlib
import secrets
import string
from dataclasses import dataclass
from urllib.parse import quote

# The models PhotonEntry sets up (ARCHITECTURE §3.4): every one has a Wiegand output for the Axis controller's reader port.
MODELS = ("S532", "S535", "S539", "E18", "E16V2", "E12V2", "X912", "X915V2", "R29", "R20")
ADMIN_USER = "admin"
UNLOCK_CODE = "#"           # pressed during a call to open the door (the web relay's DTMF code)
TRANSPORT = {"udp": 0, "tcp": 1, "tls": 2}
_ALPHABET = string.ascii_letters + string.digits


def new_password(n: int = 24) -> str:
    """Letters and digits only: they pass through every field of the intercom's web page, its settings file and a URL without quoting."""
    return "".join(secrets.choice(_ALPHABET) for _ in range(n))


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True)
class Device:
    id: str                    # the intercom's id: entry-link knows it by this
    name: str
    relay_target: str          # entry-link as the intercom reaches it, "address:port" ("" if not known yet: no web relay)
    relay_secret: str
    admin_password: str
    provision_url: str         # this intercom's own provisioning address (a directory)
    sip_server: str = ""
    sip_port: int = 5061
    sip_transport: str = "tls"
    sip_user: str = ""
    sip_password: str = ""


def _value(v: object) -> str:
    """One line per key: a value never carries a line break (names are typed by people)."""
    return " ".join(str(v).split())


def local_url(d: Device, path: str, **params: str) -> str:
    query = "&".join(f"{k}={quote(v, safe='$')}" for k, v in {"intercom": d.id, "key": d.relay_secret, **params}.items())
    return f"http://{d.relay_target}{path}?{query}"


def render(d: Device) -> str:
    """The `<MAC>.cfg` file for one intercom."""
    lines = ["# PhotonEntry: this intercom's settings. Made by PhotonEntry; changes on the device are replaced within the hour.", ""]

    def put(key: str, value: object) -> None:
        lines.append(f"{key} = {_value(value)}")

    lines.append("# Provisioning: this address, every hour; PnP off (manual provisioning)")
    put("Config.Autoprovision.GENERAL.Url", d.provision_url)
    put("Config.Autoprovision.PNP.Enable", 0)
    put("Config.Autoprovision.MODE.Mode", 4)
    lines += ["", "# Its web page: user admin, a random password"]
    put("Config.Settings.WEB_LOGIN.Password", d.admin_password)

    lines += ["", "# Calls: its SIP account in PhotonVox"]
    sip = bool(d.sip_server and d.sip_user)
    put("Config.Account1.GENERAL.Enable", int(sip))
    put("Config.Account1.GENERAL.Label", d.name)
    put("Config.Account1.GENERAL.DisplayName", d.name)
    put("Config.Account1.GENERAL.UserName", d.sip_user)
    put("Config.Account1.GENERAL.AuthName", d.sip_user)
    put("Config.Account1.GENERAL.Pwd", d.sip_password)
    put("Config.Account1.SIP.Server", d.sip_server)
    put("Config.Account1.SIP.Port", d.sip_port)
    put("Config.Account1.SIP.TransType", TRANSPORT[d.sip_transport])
    put("Config.Account1.ENCRYPTION.SRTPEncryption", 2 if d.sip_transport == "tls" else 0)

    lines += ["", "# A card reader for the door controller: 34-bit Wiegand out, no card check of its own (the controller decides)"]
    put("Config.DoorSetting.GENERAL.WiegandMode", 1)
    put("Config.DoorSetting.GENERAL.WiegandType", 1)
    put("Config.DoorSetting.GENERAL.WiegandOutVerify", 0)
    put("Config.DoorSetting.GENERAL.WiegandPINCodeOutput", 2)
    lines += ["", "# Never a lock: cards, DTMF and tamper do not touch its relay (which is not wired)"]
    put("Config.DoorSetting.GENERAL.WiegandOpenRelayA", 0)
    put("Config.DoorSetting.GENERAL.WiegandOpenRelayB", 0)
    put("Config.DoorSetting.GENERAL.TamperOptions", 0)
    put("Config.DoorSetting.RELAY.DTMFUnlock", 0)
    put("Config.DoorSetting.DTMF.WhitelistEnable", 0)

    lines += ["", f"# Unlock from a call: the person answering presses {UNLOCK_CODE}; the intercom asks entry-link on the door's controller"]
    relay = bool(d.relay_target)
    put("Config.DoorSetting.WEBRELAY.RelayType", 1 if relay else 0)
    put("Config.DoorSetting.WEBRELAY.IpAddress", "")
    put("Config.DoorSetting.WEBRELAY.AuthorizationMode", 0)
    put("Config.DoorSetting.WEBRELAY.WebRelay_Action_1", local_url(d, "/v1/relay") if relay else "")
    put("Config.DoorSetting.WEBRELAY.WebRelay_Key_1", UNLOCK_CODE if relay else "")
    put("Config.DoorSetting.DTMF.Option", 0)
    put("Config.DoorSetting.DTMF.Code1", UNLOCK_CODE)

    lines += ["", "# Calls and tamper, reported to entry-link"]
    put("Config.Features.ACTIONURL.Enable", int(relay))
    put("Config.Features.ACTIONURL.Type", 0)
    put("Config.Features.ACTIONURL.AuthorizationMode", 0)
    put("Config.Features.ACTIONURL.MakeCall", local_url(d, "/v1/event", kind="call_start", remote="$remote") if relay else "")
    put("Config.Features.ACTIONURL.HangUp", local_url(d, "/v1/event", kind="call_end", remote="$remote") if relay else "")
    put("Config.Features.ACTIONURL.TamperAlarmTriggered", local_url(d, "/v1/event", kind="tamper") if relay else "")
    return "\n".join(lines) + "\n"


def general_file(name: str) -> str:
    """Every model asks for its general file first (`r000000000532.cfg`, ...); ours holds nothing, so the MAC file decides everything."""
    return f"# PhotonEntry: no general settings ({name}); this intercom's own file follows.\n"

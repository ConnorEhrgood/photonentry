"""The provisioning server for Akuvox intercoms (ARCHITECTURE §3.4; the file itself: app/akuvox.py).

An intercom fetches `GET /provision/v1/<token>/<file>` at power-up and every hour: first its model's general file (`r000000000532.cfg`; ours
says nothing), then `<MAC>.cfg`. The token is the intercom's own random secret, typed in once by the installer; it is looked up by its hash, as
the system (the device signs in as nobody). A MAC file for another MAC than the intercom's is not found: a token copied to another device does
not give it this intercom's settings. Every miss is the same 404, and requests are limited per address.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import select

from app import akuvox, crypto
from app.db import SystemSession
from app.models import Intercom
from app.routes.intercoms import provision_url, relay_target
from app.throttle import Throttle, client_key

router = APIRouter()
provision_throttle = Throttle(limit=30, window_s=60)
_GENERAL = re.compile(r"^r\d{12}P?(\.cfg)?$", re.IGNORECASE)
_MAC_FILE = re.compile(r"^([0-9A-Fa-f]{12})\.cfg$")
_HEADERS = {"Cache-Control": "no-store"}


def _missing() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Not found")


@router.get("/provision/v1/{token}/{name}", response_class=PlainTextResponse)
def fetch(token: str, name: str, request: Request) -> PlainTextResponse:
    provision_throttle.check(request)
    if len(token) > 64:
        raise _missing()
    general, mac = _GENERAL.match(name), _MAC_FILE.match(name)
    if not general and not mac:
        raise _missing()
    with SystemSession() as db:
        i = db.execute(select(Intercom).where(Intercom.provision_token_hash == akuvox.token_hash(token))).scalar_one_or_none()
        if i is None:
            raise _missing()
        if general:
            return PlainTextResponse(akuvox.general_file(name), headers=_HEADERS)
        if mac.group(1).upper() != i.mac:
            raise _missing()
        device = akuvox.Device(
            id=str(i.id), name=i.name, relay_target=relay_target(db, i), relay_secret=crypto.unseal(i.relay_secret_sealed),
            admin_password=crypto.unseal(i.admin_password_sealed), provision_url=provision_url(token), sip_server=i.sip_server,
            sip_port=i.sip_port, sip_transport=i.sip_transport, sip_user=i.sip_user, sip_outbound_proxy=i.sip_outbound_proxy,
            sip_password=crypto.unseal(i.sip_password_sealed) if i.sip_password_sealed else "")
        body = akuvox.render(device)
        i.last_fetch_at, i.last_fetch_ip = datetime.now(timezone.utc), client_key(request)[:64]
        db.commit()
    return PlainTextResponse(body, headers=_HEADERS)

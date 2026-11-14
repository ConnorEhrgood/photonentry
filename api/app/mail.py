"""Sending email through Postmark, as PhotonVox does (photonvox api/app/mail.py). One function, so tests can swap it; with no token configured
nothing is sent (the person who made a visitor's pass shares its link themselves).

**The demo organization gets no email at all** (photon-suite DEMO.md rule 1): `for_tenant` gives every sender a stand-in that logs and sends
nothing, whatever the address, with or without Postmark configured. Every caller that mails on an organization's behalf goes through it.
"""
from __future__ import annotations

import logging
import uuid
from typing import Callable, Optional

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Tenant

log = logging.getLogger("photonentry.mail")

Sender = Callable[[str, str, str], Optional[str]]


def send(to: str, subject: str, body: str) -> Optional[str]:
    """Send a plain-text email; returns Postmark's message id, or None when no token is configured (nothing sent)."""
    if not settings.postmark_token:
        return None
    r = httpx.post("https://api.postmarkapp.com/email", timeout=15, headers={"X-Postmark-Server-Token": settings.postmark_token,
                   "Accept": "application/json"}, json={"From": settings.mail_from, "To": to, "Subject": subject, "TextBody": body,
                                                         "MessageStream": "outbound"})
    r.raise_for_status()
    return r.json().get("MessageID")


def for_tenant(db: Session, tenant_id: uuid.UUID, send: Sender) -> Sender:
    """The sender to use for this organization: `send`, or for the demo organization one that only logs (returns None: "not sent")."""
    if not db.execute(select(Tenant.demo).where(Tenant.id == tenant_id)).scalar():
        return send

    def logged(to: str, subject: str, body: str) -> Optional[str]:   # noqa: ARG001 (no address is logged either)
        log.info("demo organization: not sent: %s", subject)
        return None
    return logged

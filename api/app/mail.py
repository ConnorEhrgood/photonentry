"""Sending email through Postmark, as PhotonVox does (photonvox api/app/mail.py). One function, so tests can swap it; with no token configured
nothing is sent (the person who made a visitor's pass shares its link themselves)."""
from __future__ import annotations

from typing import Callable, Optional

import httpx

from app.config import settings

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

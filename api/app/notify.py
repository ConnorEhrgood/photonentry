"""Lockdown notices by email (ARCHITECTURE §9.6: a lockdown "notifies every admin and operator"). CRITICAL: who is told, and that a notice
is neither lost nor sent twice.

The worker sends them, never the request that locks the doors: a slow or failing mail service cannot delay a lockdown. Each lockdown records when
its start and its end were mailed. Recipients: every active person with an email whose role **at that site** can start or end a lockdown
(`entry.lockdown`: operators, admins, owners; partner staff included, they are the customer's admins too). A notice the worker could not send
within an hour is marked and dropped (a late "locked down" email misleads more than none: the banner on every page still shows it). With no mail
configured, nothing is sent and the notices are marked, so configuring mail later does not send old ones. If the mail service fails partway, the
next pass sends that notice to everyone again: a few people may get it twice, which is better than someone not getting it.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import access, mail
from app.access import Grant
from app.config import settings
from app.models import Access, Door, Lockdown, Person, Site

log = logging.getLogger("photonentry.notify")
STALE = timedelta(hours=1)


def recipients(db: Session, lk: Lockdown, now: datetime) -> List[Tuple[str, str]]:
    """(email, name) of everyone who may start or end a lockdown at the lockdown's site, sorted, each once."""
    out = {}
    for a, p in db.execute(select(Access, Person).join(Person, Person.id == Access.person_id).where(Access.tenant_id == lk.tenant_id)).all():
        if p.active and p.email and access.allowed(Grant.from_row(a), "entry.lockdown", now, lk.site_id):
            out[p.email.lower()] = p.name
    return sorted(out.items())


def message(db: Session, lk: Lockdown, ending: bool) -> Tuple[str, str]:
    site = db.get(Site, lk.site_id)
    name = site.name if site else "A site"
    doors = {str(d.id): d.name for d in db.execute(select(Door).where(Door.site_id == lk.site_id)).scalars()}
    scope = "every door" if lk.whole_site else ", ".join(doors.get(d, "a removed door") for d in lk.door_ids)
    link = f"{settings.web_url.rstrip('/')}/doors?site={lk.site_id}"
    if ending:
        subject = f"Lockdown ended: {name}"
        body = (f"The lockdown at {name} has ended.\n\nEnded by {lk.ended_by_label or 'someone'} at {lk.ended_at:%H:%M} UTC: {lk.end_reason}\n"
                f"It began at {lk.started_at:%H:%M} UTC: {lk.reason}\n\n{link}\n")
    else:
        subject = f"Locked down: {name}"
        body = (f"{name} is locked down ({scope}).\n\nStarted by {lk.started_by_label or 'someone'} at {lk.started_at:%H:%M} UTC: {lk.reason}\n\n"
                f"Cards, PINs, schedules and remote unlocks are ignored until it ends; exits and fire release work as always.\n\n{link}\n")
    return subject, body


def _send_all(db: Session, lk: Lockdown, ending: bool, send: mail.Sender, now: datetime) -> Optional[bool]:
    """True: sent (or nothing to send); None: mail is not configured; False: the mail service failed (try again next pass)."""
    subject, body = message(db, lk, ending)
    for email, _name in recipients(db, lk, now):
        try:
            if send(email, subject, body) is None:
                return None
        except httpx.HTTPError as e:
            log.warning("lockdown notice failed: %s", type(e).__name__)
            return False
    return True


def notify_lockdowns(db: Session, send: mail.Sender, now: datetime) -> int:
    """Send what is due; returns the notices handled (sent or dropped). Commits per lockdown."""
    handled = 0
    due = db.execute(select(Lockdown).where((Lockdown.start_notified_at.is_(None)) |
                                            (Lockdown.ended_at.is_not(None) & Lockdown.end_notified_at.is_(None)))).scalars().all()
    for lk in due:
        for ending in (False, True):
            if ending and lk.ended_at is None:
                continue
            if (lk.end_notified_at if ending else lk.start_notified_at) is not None:
                continue
            at = lk.ended_at if ending else lk.started_at
            if now - at > STALE:
                result: Optional[bool] = True                       # too late to be useful: dropped
                log.warning("lockdown %s: the %s notice is over an hour old; not sent", lk.id, "end" if ending else "start")
            else:
                result = _send_all(db, lk, ending, send, now)
            if result is False:
                continue                                            # the mail service failed: the next pass tries again
            if ending:
                lk.end_notified_at = now
            else:
                lk.start_notified_at = now
            db.commit()
            handled += 1
    return handled

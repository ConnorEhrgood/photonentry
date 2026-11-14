"""Visitors' passes (ARCHITECTURE §10.2; Step 6). CRITICAL: an operator gives a stranger a way in.

A pass is a cardholder of its own, in **one access group an admin opened to visitors** (`for_visitors`), at one site, valid for a window of
at most 31 days, with two credentials: a 6-digit PIN for the keypad, and a 32-bit card number (34-bit Wiegand) that a QR code will carry once
the bench shows how Akuvox reads one (ARCHITECTURE §3.4). The controller enforces the window itself (the credentials' ValidFrom and ValidTo).

**Operators issue passes; the system writes them.** Operators may not write cardholders, credentials or settings (row-level security). The
API checks the person first (capability `entry.visitors.manage` at the site, a group open to visitors, a sane window), then this module writes
the pass in the system's session and records it in the person's name. That is the whole of the escalation, and it lives here.

**A pass is published at once, without anyone's drafts:** the controllers get the site as it was last published (`site_publication`), with
today's passes in place of the ones it held. A site never published cannot take passes. An admin's next publish carries the passes too
(app/sitedoc.py). A pass ended (revoked, or past its window) more than a day ago is no longer sent.
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Set

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import audit, crypto, publishing
from app.document import SiteDocument
from app.models import AccessGroup, Cardholder, CardholderGroup, Credential, Site, SitePublication, VisitorPass

MAX_DAYS = 31
KEEP = timedelta(days=1)                 # a pass that ended is still sent for a day (the controller refuses it by its own clock)
PIN_DIGITS = 6
Random = Callable[[int], int]            # secrets.randbelow, or a test's


class PassError(Exception):
    def __init__(self, code: str, detail: str, status: int = 422) -> None:
        super().__init__(detail)
        self.code, self.detail, self.status = code, detail, status


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def ended_ids(db: Session, site_id: uuid.UUID, now: datetime) -> Set[uuid.UUID]:
    """Cardholders of passes that are over: revoked, or past their window, more than a day ago. They are not sent any more."""
    rows = db.execute(select(VisitorPass).where(VisitorPass.site_id == site_id)).scalars().all()
    return {p.cardholder_id for p in rows if (p.revoked_at or p.valid_to) <= now - KEEP}


def _holder(h: Cardholder, group: str, creds: List[Credential]) -> Dict[str, Any]:
    from app.sitedoc import _holder as build_holder
    return build_holder(h, [group], creds)


def republish(db: Session, site: Site, by: uuid.UUID, now: datetime) -> List[Dict[str, Any]]:
    """The site as last published, with today's passes; stored for each controller whose settings changed. Raises PassError."""
    snap = db.get(SitePublication, site.id)
    if snap is None:
        raise PassError("not_published", "This site has never been published: an admin publishes it once, then passes can be issued", 409)
    passes = db.execute(select(VisitorPass).where(VisitorPass.site_id == site.id)).scalars().all()
    pass_holders = {p.cardholder_id for p in passes}
    over = ended_ids(db, site.id, now)
    doc = dict(snap.document)
    groups = {g["id"] for g in doc.get("access_groups", [])}
    keep = [c for c in doc.get("cardholders", []) if uuid.UUID(c["id"]) not in pass_holders]
    live = [p for p in passes if p.cardholder_id not in over and str(p.group_id) in groups]
    live_ids = [p.cardholder_id for p in live]
    holders = {h.id: h for h in db.execute(select(Cardholder).where(Cardholder.id.in_(live_ids))).scalars()}
    creds: Dict[uuid.UUID, List[Credential]] = {}
    for c in db.execute(select(Credential).where(Credential.cardholder_id.in_(live_ids))).scalars():
        creds.setdefault(c.cardholder_id, []).append(c)
    doc["cardholders"] = keep + [_holder(holders[p.cardholder_id], str(p.group_id), creds.get(p.cardholder_id, [])) for p in live]
    try:
        return publishing.store(db, site, SiteDocument.model_validate(doc), by)
    except publishing.PublishError as e:
        raise PassError("cannot_publish", f"The site's published settings cannot take the pass: {e.problems[0]}", 409)


def _credential(db: Session, tenant_id: uuid.UUID, holder: Cardholder, kind: str, rnd: Random, valid_from: datetime, valid_to: datetime) -> Credential:
    """A PIN or a card number no one else in the organization holds (fingerprints are unique per organization: try again on a clash)."""
    for _ in range(20):
        if kind == "pin":
            value = str(rnd(10 ** PIN_DIGITS)).zfill(PIN_DIGITS)
            fp, extra, hint = crypto.fingerprint("pin", value), {}, ""
        else:
            value = str(rnd(2 ** 32))
            fp, extra, hint = crypto.fingerprint("card", f"w34:None:{value}"), {"card_format": "w34", "card_facility": None}, "…" + value[-3:]
        c = Credential(id=uuid.uuid4(), tenant_id=tenant_id, cardholder_id=holder.id, kind=kind, value_sealed=crypto.seal(value), fingerprint=fp,
                       hint=hint, enabled=True, valid_from=valid_from, valid_to=valid_to, **extra)
        try:
            with db.begin_nested():
                db.add(c)
                db.flush()
            return c
        except IntegrityError:
            continue
    raise PassError("no_number", "Could not find a free PIN or card number: try again", 503)


def issue(db: Session, *, site: Site, group_id: uuid.UUID, visitor_name: str, visitor_email: str, valid_from: datetime, valid_to: datetime,
          host_id: uuid.UUID, host_label: str, actor_source: str, now: datetime, rnd: Random = secrets.randbelow) -> tuple:
    """Write the pass (in the system's session `db`), publish it, record it. Returns (pass, token). The caller commits."""
    group = db.get(AccessGroup, group_id)
    if group is None or group.site_id != site.id or not group.for_visitors:
        raise PassError("group_not_for_visitors", "Choose one of this site's access groups that admins opened to visitors")
    if valid_to <= valid_from:
        raise PassError("bad_window", "A pass ends after it starts")
    if valid_to <= now:
        raise PassError("bad_window", "That pass would be over already")
    if valid_from < now - timedelta(minutes=10):
        raise PassError("bad_window", "A pass cannot start in the past")
    if valid_to - valid_from > timedelta(days=MAX_DAYS):
        raise PassError("bad_window", f"A pass lasts at most {MAX_DAYS} days")
    holder = Cardholder(id=uuid.uuid4(), tenant_id=site.tenant_id, name=visitor_name, email=visitor_email, valid_from=valid_from, valid_to=valid_to)
    db.add(holder)
    db.flush()
    db.add(CardholderGroup(cardholder_id=holder.id, group_id=group.id, tenant_id=site.tenant_id, site_id=site.id))
    _credential(db, site.tenant_id, holder, "pin", rnd, valid_from, valid_to)
    _credential(db, site.tenant_id, holder, "card", rnd, valid_from, valid_to)
    token = secrets.token_urlsafe(24)
    p = VisitorPass(id=uuid.uuid4(), tenant_id=site.tenant_id, site_id=site.id, cardholder_id=holder.id, group_id=group.id, visitor_name=visitor_name,
                    visitor_email=visitor_email, host_person_id=host_id, host_label=host_label, valid_from=valid_from, valid_to=valid_to,
                    token_hash=token_hash(token), token_sealed=crypto.seal(token), created_at=now)
    db.add(p)
    db.flush()
    republish(db, site, host_id, now)
    audit.record(db, actor_id=host_id, actor_label=host_label, actor_source=actor_source, action="pass.issue", tenant_id=site.tenant_id,
                 site_id=site.id, target_type="visitor_pass", target_id=p.id, visitor=visitor_name, group=group.name,
                 valid_from=valid_from.isoformat(), valid_to=valid_to.isoformat())
    return p, token


def revoke(db: Session, p: VisitorPass, site: Site, *, by_id: uuid.UUID, by_label: str, actor_source: str, now: datetime) -> None:
    """End a pass now: its cardholder is suspended (the controller refuses its PIN and card at once) and the site republished."""
    if p.revoked_at is not None:
        return
    p.revoked_at, p.revoked_by_label = now, by_label[:200]
    holder = db.get(Cardholder, p.cardholder_id)
    holder.suspended = True
    db.flush()
    republish(db, site, by_id, now)
    audit.record(db, actor_id=by_id, actor_label=by_label, actor_source=actor_source, action="pass.revoke", tenant_id=site.tenant_id,
                 site_id=site.id, target_type="visitor_pass", target_id=p.id, visitor=p.visitor_name)


def state(p: VisitorPass, now: datetime) -> str:
    if p.revoked_at is not None:
        return "revoked"
    if now < p.valid_from:
        return "upcoming"
    if now >= p.valid_to:
        return "over"
    return "active"


def secret_values(db: Session, p: VisitorPass) -> Dict[str, Optional[str]]:
    """The pass's PIN and card number, for the visitor's own page (and the host's)."""
    out: Dict[str, Optional[str]] = {"pin": None, "card_number": None}
    for c in db.execute(select(Credential).where(Credential.cardholder_id == p.cardholder_id)).scalars():
        out["pin" if c.kind == "pin" else "card_number"] = crypto.unseal(c.value_sealed)
    return out

"""Cardholders (people who open doors: PhotonEntry's own records, decision 10), their access groups, and their credentials; bulk import from CSV.

Cardholders belong to the organization: admins add and change them (`entry.cardholders.manage`), operators may read their names. A cardholder
joins a site's access group only through an admin of that site, so a site-limited admin can never give anyone another site's doors.
Credentials (`entry.credential.issue`, sensitive) are readable by admins only. Card numbers and PINs are sealed, never returned (a card shows
its last digits, a PIN nothing), and fingerprinted so that a card or PIN cannot belong to two cardholders of one organization.
"""
from __future__ import annotations

import csv
import io
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Tuple

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, ValidationError, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import crypto
from app.db import get_db
from app.deps import Ctx, require, tenant_ctx
from app.document import Card
from app.models import Access, AccessGroup, Cardholder, CardholderGroup, Credential
from app.routes.common import log, not_found, problem, site_of

router = APIRouter(prefix="/tenants/{tenant_id}")
MAX_IMPORT_ROWS = 5000


class CardholderIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    ref: Optional[str] = Field(default=None, min_length=1, max_length=80)
    email: str = Field(default="", max_length=320)
    person_id: Optional[uuid.UUID] = None
    suspended: bool = False
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None


class CardholderPatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    ref: Optional[str] = Field(default=None, min_length=1, max_length=80)
    email: Optional[str] = Field(default=None, max_length=320)
    person_id: Optional[uuid.UUID] = None
    suspended: Optional[bool] = None
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None


class GroupsIn(BaseModel):
    group_ids: List[uuid.UUID] = Field(max_length=200)


class CredentialIn(BaseModel):
    kind: Literal["card", "pin"]
    card: Optional[Card] = None
    pin: Optional[str] = Field(default=None, pattern=r"^\d{4,8}$")
    enabled: bool = True
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None

    @model_validator(mode="after")
    def _shape(self) -> "CredentialIn":
        if (self.kind == "card") != (self.card is not None) or (self.kind == "pin") != (self.pin is not None):
            raise ValueError("a card credential has a card, a PIN credential a PIN, and nothing else")
        return self


class CredentialPatch(BaseModel):
    enabled: Optional[bool] = None
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None


def holder_view(h: Cardholder, groups: List[uuid.UUID]) -> Dict[str, Any]:
    return {"id": str(h.id), "name": h.name, "ref": h.ref, "email": h.email, "person_id": str(h.person_id) if h.person_id else None,
            "suspended": h.suspended, "valid_from": h.valid_from.isoformat() if h.valid_from else None,
            "valid_to": h.valid_to.isoformat() if h.valid_to else None, "groups": sorted(str(g) for g in groups)}


def credential_view(c: Credential) -> Dict[str, Any]:
    return {"id": str(c.id), "kind": c.kind, "card_format": c.card_format, "card_facility": c.card_facility, "hint": c.hint, "enabled": c.enabled,
            "valid_from": c.valid_from.isoformat() if c.valid_from else None, "valid_to": c.valid_to.isoformat() if c.valid_to else None}


def _groups_of(db: Session, holder_ids: List[uuid.UUID]) -> Dict[uuid.UUID, List[uuid.UUID]]:
    out: Dict[uuid.UUID, List[uuid.UUID]] = {h: [] for h in holder_ids}
    if holder_ids:
        for m in db.execute(select(CardholderGroup).where(CardholderGroup.cardholder_id.in_(holder_ids))).scalars():
            out[m.cardholder_id].append(m.group_id)
    return out


def _holder(db: Session, ctx: Ctx, holder_id: uuid.UUID) -> Cardholder:
    h = db.get(Cardholder, holder_id)
    if h is None or h.tenant_id != ctx.tenant_id:
        raise not_found()
    return h


def _check_person(db: Session, ctx: Ctx, person_id: Optional[uuid.UUID], holder_id: Optional[uuid.UUID] = None) -> None:
    """A cardholder is linked only to a person who has PhotonEntry access in this organization (photonid: an active member with an Entry role),
    and a person to one cardholder of the organization at most (their app opens that record's doors)."""
    if person_id is None:
        return
    if db.execute(select(Access).where(Access.tenant_id == ctx.tenant_id, Access.person_id == person_id)).scalar_one_or_none() is None:
        raise problem({"code": "not_a_member", "detail": "That person has no PhotonEntry access in this organization"})
    other = db.execute(select(Cardholder).where(Cardholder.tenant_id == ctx.tenant_id, Cardholder.person_id == person_id,
                                                Cardholder.id != (holder_id or uuid.uuid4()))).scalars().first()
    if other is not None:
        raise problem({"code": "person_linked", "detail": f"That person is already linked to {other.name}"}, 409)


def _check_validity(valid_from: Optional[datetime], valid_to: Optional[datetime]) -> None:
    for t in (valid_from, valid_to):
        if t is not None and t.tzinfo is None:
            raise problem({"code": "invalid", "detail": "Times need a time zone"})
    if valid_from and valid_to and valid_to <= valid_from:
        raise problem({"code": "invalid", "detail": "valid_to must be after valid_from"})


@router.get("/cardholders")
def list_cardholders(ctx: Ctx = Depends(require("entry.cardholders.view")), db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    rows = db.execute(select(Cardholder).where(Cardholder.tenant_id == ctx.tenant_id).order_by(Cardholder.name)).scalars().all()
    groups = _groups_of(db, [h.id for h in rows])
    return [holder_view(h, groups[h.id]) for h in rows]


@router.post("/cardholders", status_code=201)
def add_cardholder(body: CardholderIn, ctx: Ctx = Depends(require("entry.cardholders.manage")), db: Session = Depends(get_db)) -> Dict[str, Any]:
    _check_validity(body.valid_from, body.valid_to)
    _check_person(db, ctx, body.person_id)
    h = Cardholder(id=uuid.uuid4(), tenant_id=ctx.tenant_id, **body.model_dump())
    db.add(h)
    try:
        db.flush()
    except IntegrityError:
        raise problem({"code": "ref_exists", "detail": "Another cardholder has that reference"}, 409)
    log(db, ctx, "cardholder.add", target_type="cardholder", target_id=h.id, name=h.name)
    db.commit()
    return holder_view(h, [])


@router.get("/cardholders/{holder_id}")
def get_cardholder(holder_id: uuid.UUID, ctx: Ctx = Depends(require("entry.cardholders.view")), db: Session = Depends(get_db)) -> Dict[str, Any]:
    h = _holder(db, ctx, holder_id)
    return holder_view(h, _groups_of(db, [h.id])[h.id])


@router.patch("/cardholders/{holder_id}")
def patch_cardholder(holder_id: uuid.UUID, body: CardholderPatch, ctx: Ctx = Depends(require("entry.cardholders.manage")),
                     db: Session = Depends(get_db)) -> Dict[str, Any]:
    h = _holder(db, ctx, holder_id)
    changes = body.model_dump(exclude_unset=True)
    if "person_id" in changes:
        _check_person(db, ctx, changes["person_id"], h.id)
    for k, v in changes.items():
        setattr(h, k, v)
    _check_validity(h.valid_from, h.valid_to)
    try:
        db.flush()
    except IntegrityError:
        raise problem({"code": "ref_exists", "detail": "Another cardholder has that reference"}, 409)
    log(db, ctx, "cardholder.change", target_type="cardholder", target_id=h.id, fields=sorted(changes))
    db.commit()
    return holder_view(h, _groups_of(db, [h.id])[h.id])


@router.delete("/cardholders/{holder_id}", status_code=204)
def remove_cardholder(holder_id: uuid.UUID, ctx: Ctx = Depends(require("entry.cardholders.manage")), db: Session = Depends(get_db)) -> None:
    h = _holder(db, ctx, holder_id)
    memberships = db.execute(select(CardholderGroup).where(CardholderGroup.cardholder_id == h.id)).scalars().all()
    for m in memberships:
        ctx.need("entry.cardholders.manage", m.site_id)   # a site-limited admin cannot take away another site's access
        db.delete(m)
    if db.execute(select(Credential.id).where(Credential.cardholder_id == h.id)).first():
        if not ctx.can("entry.credential.issue"):
            raise problem({"code": "not_allowed", "detail": "Removing this cardholder revokes their credentials"}, 403)
        for c in db.execute(select(Credential).where(Credential.cardholder_id == h.id)).scalars():
            db.delete(c)
    db.delete(h)
    log(db, ctx, "cardholder.remove", target_type="cardholder", target_id=h.id, name=h.name)
    db.commit()


@router.put("/cardholders/{holder_id}/groups")
def set_groups(holder_id: uuid.UUID, body: GroupsIn, ctx: Ctx = Depends(require("entry.cardholders.manage")),
               db: Session = Depends(get_db)) -> Dict[str, Any]:
    """The cardholder's access groups, all sites together. Every group added or removed must be at a site where the person manages cardholders."""
    h = _holder(db, ctx, holder_id)
    current = {m.group_id: m for m in db.execute(select(CardholderGroup).where(CardholderGroup.cardholder_id == h.id)).scalars()}
    wanted = set(body.group_ids)
    added, removed = [], []
    for gid in wanted - set(current):
        g = db.get(AccessGroup, gid)
        if g is None or g.tenant_id != ctx.tenant_id:
            raise problem({"code": "no_such_group", "detail": "One of the groups does not exist"})
        ctx.need("entry.cardholders.manage", g.site_id)
        db.add(CardholderGroup(cardholder_id=h.id, group_id=g.id, tenant_id=ctx.tenant_id, site_id=g.site_id))
        added.append(str(g.id))
    for gid in set(current) - wanted:
        ctx.need("entry.cardholders.manage", current[gid].site_id)
        db.delete(current[gid])
        removed.append(str(gid))
    log(db, ctx, "cardholder.groups", target_type="cardholder", target_id=h.id, added=sorted(added), removed=sorted(removed))
    db.commit()
    return holder_view(h, sorted(wanted))


# ---- credentials ----


def _seal(body: CredentialIn) -> Tuple[str, str, str]:
    """(sealed value, fingerprint, hint)."""
    if body.card is not None:
        number = str(body.card.number)
        return (crypto.seal(number), crypto.fingerprint("card", f"{body.card.format}:{body.card.facility}:{number}"), "…" + number[-3:])
    return crypto.seal(body.pin or ""), crypto.fingerprint("pin", body.pin or ""), ""


@router.get("/cardholders/{holder_id}/credentials")
def list_credentials(holder_id: uuid.UUID, ctx: Ctx = Depends(require("entry.credential.issue")), db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    h = _holder(db, ctx, holder_id)
    return [credential_view(c) for c in db.execute(select(Credential).where(Credential.cardholder_id == h.id).order_by(Credential.created_at)).scalars()]


@router.post("/cardholders/{holder_id}/credentials", status_code=201)
def add_credential(holder_id: uuid.UUID, body: CredentialIn, ctx: Ctx = Depends(require("entry.credential.issue")),
                   db: Session = Depends(get_db)) -> Dict[str, Any]:
    h = _holder(db, ctx, holder_id)
    _check_validity(body.valid_from, body.valid_to)
    c = _new_credential(ctx, h, body)
    db.add(c)
    try:
        db.flush()
    except IntegrityError:
        raise problem({"code": "credential_exists", "detail": "That card or PIN already belongs to someone in this organization"}, 409)
    log(db, ctx, "credential.issue", target_type="credential", target_id=c.id, cardholder=str(h.id), kind=c.kind, hint=c.hint)
    db.commit()
    return credential_view(c)


def _new_credential(ctx: Ctx, h: Cardholder, body: CredentialIn) -> Credential:
    sealed, fingerprint, hint = _seal(body)
    return Credential(id=uuid.uuid4(), tenant_id=ctx.tenant_id, cardholder_id=h.id, kind=body.kind,
                      card_format=body.card.format if body.card else None, card_facility=body.card.facility if body.card else None,
                      value_sealed=sealed, fingerprint=fingerprint, hint=hint, enabled=body.enabled, valid_from=body.valid_from,
                      valid_to=body.valid_to)


def _credential(db: Session, ctx: Ctx, holder_id: uuid.UUID, credential_id: uuid.UUID) -> Credential:
    c = db.get(Credential, credential_id)
    if c is None or c.tenant_id != ctx.tenant_id or c.cardholder_id != holder_id:
        raise not_found()
    return c


@router.patch("/cardholders/{holder_id}/credentials/{credential_id}")
def patch_credential(holder_id: uuid.UUID, credential_id: uuid.UUID, body: CredentialPatch, ctx: Ctx = Depends(require("entry.credential.issue")),
                     db: Session = Depends(get_db)) -> Dict[str, Any]:
    c = _credential(db, ctx, holder_id, credential_id)
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(c, k, v)
    _check_validity(c.valid_from, c.valid_to)
    log(db, ctx, "credential.change", target_type="credential", target_id=c.id, fields=sorted(changes))
    db.commit()
    return credential_view(c)


@router.delete("/cardholders/{holder_id}/credentials/{credential_id}", status_code=204)
def revoke_credential(holder_id: uuid.UUID, credential_id: uuid.UUID, ctx: Ctx = Depends(require("entry.credential.issue")),
                      db: Session = Depends(get_db)) -> None:
    c = _credential(db, ctx, holder_id, credential_id)
    db.delete(c)
    log(db, ctx, "credential.revoke", target_type="credential", target_id=c.id, kind=c.kind, hint=c.hint)
    db.commit()


# ---- bulk import ----


class ImportIn(BaseModel):
    site_id: uuid.UUID = Field(description="The site whose access groups the `groups` column names")
    csv: str = Field(max_length=2_000_000)
    dry_run: bool = True


COLUMNS = {"name", "ref", "email", "card_format", "card_facility", "card_number", "pin", "groups"}


@router.post("/cardholders/import")
def import_cardholders(body: ImportIn, ctx: Ctx = Depends(require("entry.cardholders.manage")), db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Cardholders from a spreadsheet: columns `name` (required), `ref`, `email`, `card_format` (h10301, w34, raw; default h10301),
    `card_facility`, `card_number`, `pin`, `groups` (names of the site's access groups, separated by `;`).

    A row with a `ref` that already exists updates that cardholder (name, email; groups and credentials are added, never removed). Every row is
    checked first; if any row has a problem nothing is written and every problem is listed with its line. `dry_run` (the default) only checks."""
    site = site_of(db, ctx, body.site_id, "entry.cardholders.manage")
    issue = ctx.can("entry.credential.issue", site.id)
    reader = csv.DictReader(io.StringIO(body.csv.lstrip("﻿")))
    headers = {(h or "").strip().lower() for h in reader.fieldnames or []}
    if "name" not in headers or headers - COLUMNS:
        raise problem({"code": "bad_columns", "detail": f"Columns must include name and may be: {', '.join(sorted(COLUMNS))}"})
    groups = {g.name.lower(): g for g in db.execute(select(AccessGroup).where(AccessGroup.site_id == site.id)).scalars()}
    existing = {h.ref: h for h in db.execute(select(Cardholder).where(Cardholder.tenant_id == ctx.tenant_id, Cardholder.ref.is_not(None))).scalars()}
    known_prints = set(db.execute(select(Credential.fingerprint).where(Credential.tenant_id == ctx.tenant_id)).scalars()) if issue else set()

    plan: List[Dict[str, Any]] = []
    errors: List[str] = []
    seen_refs, seen_prints = set(), set()
    for line, raw in enumerate(reader, start=2):
        if line - 1 > MAX_IMPORT_ROWS:
            raise problem({"code": "too_many_rows", "detail": f"At most {MAX_IMPORT_ROWS} rows per import"})
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        try:
            plan.append(_plan_row(row, groups, existing, issue, known_prints, seen_refs, seen_prints))
        except ValueError as e:
            errors.append(f"line {line}: {e}")
    if errors:
        raise problem({"code": "invalid_rows", "problems": errors})
    summary = {"rows": len(plan), "new": sum(1 for p in plan if p["holder"] is None), "updated": sum(1 for p in plan if p["holder"] is not None),
               "credentials": sum(len(p["credentials"]) for p in plan)}
    if body.dry_run:
        return {"dry_run": True, **summary}
    for p in plan:
        h = p["holder"]
        if h is None:
            h = Cardholder(id=uuid.uuid4(), tenant_id=ctx.tenant_id, name=p["name"], ref=p["ref"], email=p["email"])
            db.add(h)
            db.flush()
        else:
            h.name, h.email = p["name"], p["email"] or h.email
        have = {m.group_id for m in db.execute(select(CardholderGroup).where(CardholderGroup.cardholder_id == h.id)).scalars()}
        for g in p["groups"]:
            if g.id not in have:
                db.add(CardholderGroup(cardholder_id=h.id, group_id=g.id, tenant_id=ctx.tenant_id, site_id=site.id))
        for cred in p["credentials"]:
            db.add(_new_credential(ctx, h, cred))
    db.flush()
    log(db, ctx, "cardholder.import", site_id=site.id, target_type="site", target_id=site.id, **summary)
    db.commit()
    return {"dry_run": False, **summary}


def _plan_row(row: Dict[str, str], groups: Dict[str, AccessGroup], existing: Dict[str, Cardholder], issue: bool, known_prints: set,
              seen_refs: set, seen_prints: set) -> Dict[str, Any]:
    name = row.get("name", "")
    if not name or len(name) > 128:
        raise ValueError("a name is required (at most 128 characters)")
    ref = row.get("ref") or None
    if ref:
        if ref in seen_refs:
            raise ValueError(f"ref {ref} appears twice")
        seen_refs.add(ref)
    names = [g.strip().lower() for g in (row.get("groups") or "").split(";") if g.strip()]
    missing = [n for n in names if n not in groups]
    if missing:
        raise ValueError(f"no access group named {', '.join(missing)} at this site")
    creds: List[CredentialIn] = []
    try:
        if row.get("card_number"):
            facility = row.get("card_facility") or None
            creds.append(CredentialIn(kind="card", card=Card(format=row.get("card_format") or "h10301",
                                                             facility=int(facility) if facility else None, number=int(row["card_number"]))))
        if row.get("pin"):
            creds.append(CredentialIn(kind="pin", pin=row["pin"]))
    except (ValidationError, ValueError) as e:
        raise ValueError(_first_error(e)) from e
    if creds and not issue:
        raise ValueError("you may not issue credentials")
    for c in creds:
        _, fp, _ = _seal(c)
        if fp in known_prints or fp in seen_prints:
            raise ValueError(f"that {'card' if c.kind == 'card' else 'PIN'} already belongs to someone")
        seen_prints.add(fp)
    return {"name": name, "ref": ref, "email": row.get("email", ""), "holder": existing.get(ref) if ref else None,
            "groups": [groups[n] for n in names], "credentials": creds}


def _first_error(e: Exception) -> str:
    if isinstance(e, ValidationError):
        msg = e.errors()[0]["msg"]
        return re.sub(r"^Value error, ", "", msg)
    return "a number is not a number"

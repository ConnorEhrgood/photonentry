"""PhotonEntry's data model.

1. **The directory copy** (organizations, sites, people, access), written by the sync only, as in every Photon product (suite §5). The
   organization is called a tenant here and holds the directory's organization id. No foreign keys between the four kinds: they arrive in any
   order.
2. **Controllers and the link**: claimed controllers, the settings versions published to them, the commands waiting for them, and their door
   events. Written by the link service (system role) and, for publishing and commands, by the API's routes (app role, under row-level security).
3. **The access configuration**: per site, its doors, schedules, holiday calendar and access groups; per organization, its cardholders and
   their credentials (card numbers and PINs sealed, with a keyed fingerprint so one card cannot have two holders).

Every tenant table has `tenant_id` and row-level security from migration 0001; tests/db/test_rls.py fails when a table has no policy.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import (BigInteger, Boolean, CheckConstraint, DateTime, Float, Index, Integer, LargeBinary, SmallInteger, String, Text,
                        UniqueConstraint, text)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


UUIDT = UUID(as_uuid=True)

# ---- 1. the directory copy ----


class Tenant(Base):
    __tablename__ = "tenant"
    id: Mapped[uuid.UUID] = mapped_column(UUIDT, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    partner_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDT)
    plan_key: Mapped[str] = mapped_column(String(60), default="")
    status: Mapped[str] = mapped_column(String(20), default="active")       # active | suspended | removed
    home_region: Mapped[str] = mapped_column(String(40), default="us-east")
    products: Mapped[List[str]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Site(Base):
    __tablename__ = "site"
    id: Mapped[uuid.UUID] = mapped_column(UUIDT, primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUIDT, index=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    address: Mapped[str] = mapped_column(Text, default="")
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    latitude: Mapped[Optional[float]] = mapped_column(Float)
    longitude: Mapped[Optional[float]] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20), default="active")


class Person(Base):
    __tablename__ = "person"
    id: Mapped[uuid.UUID] = mapped_column(UUIDT, primary_key=True)
    sub: Mapped[Optional[str]] = mapped_column(String(200), unique=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    email: Mapped[str] = mapped_column(String(320), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Photon staff: the directory's `platform_admin`, or a member of the partner with slug "photon" (photonid projection.py).
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    partners: Mapped[List[Dict[str, Any]]] = mapped_column(JSONB, default=list)


class Access(Base):
    __tablename__ = "access"
    person_id: Mapped[uuid.UUID] = mapped_column(UUIDT, primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUIDT, primary_key=True, index=True)
    role: Mapped[str] = mapped_column(String(20))
    scope_all: Mapped[bool] = mapped_column(Boolean, default=True)
    site_ids: Mapped[List[uuid.UUID]] = mapped_column(ARRAY(UUIDT), default=list, server_default=text("'{}'"))
    source: Mapped[str] = mapped_column(String(10), default="direct")
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    others: Mapped[List[Dict[str, Any]]] = mapped_column(JSONB, default=list, server_default=text("'[]'"))


class SyncState(Base):
    __tablename__ = "sync_state"
    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, default=1)
    cursor: Mapped[int] = mapped_column(BigInteger, default=0)
    last_pull_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_ok_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    roles_published_hash: Mapped[str] = mapped_column(String(64), default="")


class AuditLog(Base):
    """Append-only (decision 18): the app and system roles may add and read rows, never change or delete them."""
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    tenant_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDT)
    site_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDT)
    actor_person_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDT)
    actor_label: Mapped[str] = mapped_column(String(320), default="")
    actor_source: Mapped[str] = mapped_column(String(10), default="direct")
    action: Mapped[str] = mapped_column(String(60))
    target_type: Mapped[str] = mapped_column(String(40), default="")
    target_id: Mapped[str] = mapped_column(String(80), default="")
    detail: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict)
    __table_args__ = (Index("ix_audit_tenant_at", "tenant_id", "at"), {"implicit_returning": False})


# ---- 2. controllers and the link ----


class Controller(Base):
    """A door controller running entry-link. Pending ones (said hello, not claimed) belong to no organization and only the system role sees them."""
    __tablename__ = "controller"
    id: Mapped[uuid.UUID] = mapped_column(UUIDT, primary_key=True, default=uuid.uuid4)
    key_id: Mapped[str] = mapped_column(String(16), unique=True)
    public_key: Mapped[bytes] = mapped_column(LargeBinary)
    claim_code: Mapped[str] = mapped_column(String(9), default="")
    state: Mapped[str] = mapped_column(String(10), default="pending")      # pending | claimed | disabled
    tenant_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDT, index=True)
    site_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDT, index=True)
    name: Mapped[str] = mapped_column(String(64), default="")
    device: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict)
    inventory: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB)
    applied_version: Mapped[int] = mapped_column(Integer, default=0)
    failed_version: Mapped[int] = mapped_column(Integer, default=0)
    apply_error: Mapped[str] = mapped_column(Text, default="")
    ack_seq: Mapped[int] = mapped_column(BigInteger, default=0)
    last_seen: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    health: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict)
    claimed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SettingsVersion(Base):
    __tablename__ = "settings_version"
    controller_id: Mapped[uuid.UUID] = mapped_column(UUIDT, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUIDT, index=True)
    site_id: Mapped[uuid.UUID] = mapped_column(UUIDT)
    document: Mapped[Dict[str, Any]] = mapped_column(JSONB)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDT)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = ({"implicit_returning": False},)


class LinkCommand(Base):
    __tablename__ = "link_command"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUIDT, index=True)
    site_id: Mapped[uuid.UUID] = mapped_column(UUIDT)
    controller_id: Mapped[uuid.UUID] = mapped_column(UUIDT, index=True)
    kind: Mapped[str] = mapped_column(String(20))
    door: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(200), default="")
    actor_person_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDT)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    ok: Mapped[Optional[bool]] = mapped_column(Boolean)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = ({"implicit_returning": False},)


class DoorEvent(Base):
    """What a controller reported, exactly once per (controller, seq). Plain Postgres for now; a TimescaleDB hypertable when volume calls for it."""
    __tablename__ = "door_event"
    controller_id: Mapped[uuid.UUID] = mapped_column(UUIDT, primary_key=True)
    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUIDT)
    site_id: Mapped[uuid.UUID] = mapped_column(UUIDT)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    topic: Mapped[str] = mapped_column(String(200))
    source: Mapped[Dict[str, str]] = mapped_column(JSONB, default=dict)
    data: Mapped[Dict[str, str]] = mapped_column(JSONB, default=dict)
    ref: Mapped[str] = mapped_column(String(64), default="")
    __table_args__ = (Index("ix_door_event_site_time", "site_id", "occurred_at"),)


# ---- 3. the access configuration ----


class Door(Base):
    __tablename__ = "door"
    id: Mapped[uuid.UUID] = mapped_column(UUIDT, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUIDT, index=True)
    site_id: Mapped[uuid.UUID] = mapped_column(UUIDT, index=True)
    controller_id: Mapped[uuid.UUID] = mapped_column(UUIDT)
    controller_door: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(64))
    access_time_s: Mapped[int] = mapped_column(Integer, default=7)
    open_too_long_s: Mapped[int] = mapped_column(Integer, default=30)
    pre_alarm_s: Mapped[int] = mapped_column(Integer, default=5)
    unlock_schedule_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDT)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("controller_id", "controller_door", name="uq_door_controller_door"),)


class Schedule(Base):
    __tablename__ = "schedule"
    id: Mapped[uuid.UUID] = mapped_column(UUIDT, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUIDT, index=True)
    site_id: Mapped[uuid.UUID] = mapped_column(UUIDT, index=True)
    name: Mapped[str] = mapped_column(String(64))
    windows: Mapped[List[Dict[str, Any]]] = mapped_column(JSONB)        # app/document.py Window
    on_holidays: Mapped[str] = mapped_column(String(10), default="off")


class HolidayCalendar(Base):
    """The site's calendar (one per site): the days its schedules are off when they say so."""
    __tablename__ = "holiday_calendar"
    site_id: Mapped[uuid.UUID] = mapped_column(UUIDT, primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUIDT, index=True)
    days: Mapped[List[Dict[str, Any]]] = mapped_column(JSONB, default=list)   # [{"day": "2026-12-25", "name": "Christmas"}]


class AccessGroup(Base):
    __tablename__ = "access_group"
    id: Mapped[uuid.UUID] = mapped_column(UUIDT, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUIDT, index=True)
    site_id: Mapped[uuid.UUID] = mapped_column(UUIDT, index=True)
    name: Mapped[str] = mapped_column(String(64))
    rules: Mapped[List[Dict[str, Any]]] = mapped_column(JSONB)          # [{"doors": [door id], "schedule_id": id or null}]


class Cardholder(Base):
    """A person who can open doors (decision 10): PhotonEntry's own record, linked to a PhotonID person only when they will sign in."""
    __tablename__ = "cardholder"
    id: Mapped[uuid.UUID] = mapped_column(UUIDT, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUIDT, index=True)
    name: Mapped[str] = mapped_column(String(128))
    ref: Mapped[Optional[str]] = mapped_column(String(80))               # the customer's own id (employee number): bulk imports match on it
    email: Mapped[str] = mapped_column(String(320), default="")
    person_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDT)
    suspended: Mapped[bool] = mapped_column(Boolean, default=False)
    valid_from: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("tenant_id", "ref", name="uq_cardholder_ref"),)


class CardholderGroup(Base):
    __tablename__ = "cardholder_group"
    cardholder_id: Mapped[uuid.UUID] = mapped_column(UUIDT, primary_key=True)
    group_id: Mapped[uuid.UUID] = mapped_column(UUIDT, primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUIDT, index=True)
    site_id: Mapped[uuid.UUID] = mapped_column(UUIDT, index=True)


class Credential(Base):
    __tablename__ = "credential"
    id: Mapped[uuid.UUID] = mapped_column(UUIDT, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUIDT, index=True)
    cardholder_id: Mapped[uuid.UUID] = mapped_column(UUIDT, index=True)
    kind: Mapped[str] = mapped_column(String(10))                        # card | pin
    card_format: Mapped[Optional[str]] = mapped_column(String(10))       # h10301 | w34 | raw
    card_facility: Mapped[Optional[int]] = mapped_column(Integer)
    value_sealed: Mapped[str] = mapped_column(Text)                      # the card number or the PIN (app/crypto.py)
    fingerprint: Mapped[str] = mapped_column(String(64))
    hint: Mapped[str] = mapped_column(String(20), default="")            # what screens show: the last digits of a card, never of a PIN
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    valid_from: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("tenant_id", "fingerprint", name="uq_credential_fingerprint"),
                      CheckConstraint("kind in ('card', 'pin')", name="ck_credential_kind"))


# ---- 4. integrations: PhotonGuard and PhotonConsole ----


class GuardLink(Base):
    """An organization's connection to PhotonGuard: the ingest token its Guard admin made (scope guard:events:write), sealed. Guard's address is
    PhotonEntry's configuration (GUARD_API_URL), never the organization's, so the sender cannot be pointed anywhere else."""
    __tablename__ = "guard_link"
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUIDT, primary_key=True)
    token_sealed: Mapped[str] = mapped_column(Text)
    token_hint: Mapped[str] = mapped_column(String(12), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDT)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_ok_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str] = mapped_column(Text, default="")
    last_error_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    sent: Mapped[int] = mapped_column(BigInteger, default=0)


class GuardCursor(Base):
    """How far each controller's events have been offered to Guard (the system's own bookkeeping)."""
    __tablename__ = "guard_cursor"
    controller_id: Mapped[uuid.UUID] = mapped_column(UUIDT, primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUIDT, index=True)
    seq: Mapped[int] = mapped_column(BigInteger, default=0)


class DoorAlarm(Base):
    """A door alarm Guard was told has started (forced, held open, tampered with) and not yet that it ended: the end goes under the same key."""
    __tablename__ = "door_alarm"
    door_id: Mapped[uuid.UUID] = mapped_column(UUIDT, primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), primary_key=True)        # alarm | tamper
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUIDT, index=True)
    dedup_key: Mapped[str] = mapped_column(String(120))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ConsoleFeedToken(Base):
    """A PhotonConsole data source's token (`pent_...`): made by an admin, shown once, stored hashed, revocable; names the Console tenant it is
    for (Console refuses a document that names another, as with PhotonBoard's and PhotonEdge's feeds)."""
    __tablename__ = "console_feed_token"
    id: Mapped[uuid.UUID] = mapped_column(UUIDT, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUIDT, index=True)
    console_tenant_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDT)
    name: Mapped[str] = mapped_column(String(100))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDT)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


# ---- 5. intercoms (Step 5) ----


class Intercom(Base):
    """An intercom at a door (ARCHITECTURE §3.4): it reads cards for the door's controller by Wiegand, takes calls through PhotonVox, and opens
    the door from a call through `entry-link` on that controller ("web relay"). Its settings come from our provisioning server
    (app/akuvox.py): the device fetches `<MAC>.cfg` from its own address, which holds `provision_token`. Every secret is random, made here, and
    sealed (app/crypto.py); admins at the site see them, nobody else."""
    __tablename__ = "intercom"
    id: Mapped[uuid.UUID] = mapped_column(UUIDT, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUIDT, index=True)
    site_id: Mapped[uuid.UUID] = mapped_column(UUIDT, index=True)
    door_id: Mapped[uuid.UUID] = mapped_column(UUIDT)
    name: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(32))                              # app/akuvox.py MODELS
    mac: Mapped[str] = mapped_column(String(12), unique=True)                   # 12 upper-case hex digits
    relay_address: Mapped[str] = mapped_column(String(80), default="")          # entry-link as the intercom reaches it; "" = the controller's report
    sip_server: Mapped[str] = mapped_column(String(255), default="")
    sip_port: Mapped[int] = mapped_column(Integer, default=5061)
    sip_transport: Mapped[str] = mapped_column(String(3), default="tls")        # udp | tcp | tls
    sip_user: Mapped[str] = mapped_column(String(64), default="")
    sip_password_sealed: Mapped[str] = mapped_column(Text, default="")
    relay_secret_sealed: Mapped[str] = mapped_column(Text)                      # the web relay's password, also the action URLs' key
    admin_password_sealed: Mapped[str] = mapped_column(Text)                    # the intercom's web page (user admin)
    provision_token_sealed: Mapped[str] = mapped_column(Text)
    provision_token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDT)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_fetch_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_fetch_ip: Mapped[str] = mapped_column(String(64), default="")
    __table_args__ = (CheckConstraint("sip_transport in ('udp', 'tcp', 'tls')", name="ck_intercom_transport"),
                      CheckConstraint("mac ~ '^[0-9A-F]{12}$'", name="ck_intercom_mac"))

"""The link protocol's messages (ARCHITECTURE §3.2, contract/link/). `scripts/contract.py` writes the JSON Schemas in contract/link/ from these
models, and a test fails when the two differ, so the C side (acap/entry-link) and the cloud read one definition.

Two calls, both signed (app/link/signing.py):

    POST /link/v1/hello   a controller introduces itself; unknown keys are recorded as pending with the claim code the controller shows
    POST /link/v1/sync    a claimed controller sends what it has (applied settings version, inventory, events, command results) and receives
                          what it should do (newer settings, commands). Held open up to `wait_s` when there is nothing to say either way.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

MAX_EVENTS_PER_SYNC = 500


class _Msg(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Device(_Msg):
    model: str = Field(max_length=64)
    serial: str = Field(max_length=64)
    firmware: str = Field(max_length=64)
    app_version: str = Field(max_length=32)


class HelloRequest(_Msg):
    public_key: str = Field(description="Ed25519 public key, raw 32 bytes, base64url without padding", max_length=64)
    claim_code: str = Field(pattern=r"^[0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4}$",
                            description="The code the controller shows its installer (Crockford base32, random, made on the controller)")
    device: Device


class HelloResponse(_Msg):
    state: Literal["pending", "claimed", "disabled"]
    controller_id: Optional[str] = None


class InventoryDoor(_Msg):
    token: str = Field(max_length=64)
    name: str = Field(default="", max_length=128)
    access_points: List[str] = Field(default_factory=list, description="The access points (reader sides) that open this door")


class Inventory(_Msg):
    """What the controller has, read from its door-control and access-point services. Doors in PhotonEntry are mapped to these tokens."""
    doors: List[InventoryDoor] = Field(default_factory=list)


class Event(_Msg):
    seq: int = Field(ge=1, description="Per controller, from 1, never reused: the controller's queue order")
    occurred_at: datetime = Field(description="The controller's time")
    topic: str = Field(max_length=200, description="The controller's event topic, e.g. tns1:AccessControl/AccessGranted/Credential")
    source: Dict[str, str] = Field(default_factory=dict, description="e.g. AccessPointToken, DoorToken")
    data: Dict[str, str] = Field(default_factory=dict, description="e.g. CredentialToken, CredentialHolderName, Reason, State")
    ref: str = Field(default="", max_length=64, description="The controller's own id for the event, when it has one")


class CommandResult(_Msg):
    id: str = Field(max_length=40)
    ok: bool
    error: str = Field(default="", max_length=500)


class Health(_Msg):
    uptime_s: int = Field(default=0, ge=0)
    queued_events: int = Field(default=0, ge=0, description="Events read from the controller and not yet acknowledged")
    clock: Optional[datetime] = None


class SyncRequest(_Msg):
    applied_version: int = Field(default=0, ge=0, description="The settings version now applied on the controller (0: none)")
    failed_version: int = Field(default=0, ge=0, description="A version the controller received and could not apply (0: none). Not sent "
                                "again until a newer one exists; the controller retries the copy it has on its own")
    apply_error: str = Field(default="", max_length=1000, description="Why `failed_version` could not be applied")
    inventory: Optional[Inventory] = Field(default=None, description="Sent at start and whenever it changes")
    events: List[Event] = Field(default_factory=list, max_length=MAX_EVENTS_PER_SYNC)
    results: List[CommandResult] = Field(default_factory=list, max_length=100)
    health: Health = Field(default_factory=Health)
    wait: bool = Field(default=False, description="Hold the request open until there is something to send, or the wait ends")


class Settings(_Msg):
    version: int = Field(ge=1)
    document: Dict[str, Any] = Field(description="The compiled settings for this controller (contract/settings/axis-settings.schema.json)")


class Command(_Msg):
    id: str
    kind: Literal["access", "lock", "unlock", "lockdown", "lockdown_release"]
    door: str = Field(description="The controller's door token")
    expires_at: datetime = Field(description="Not carried out after this time: a late unlock is worse than none")
    actor: str = Field(default="", description="Who asked, for the controller's own log")


class SyncResponse(_Msg):
    ack_seq: int = Field(ge=0, description="Every event up to this sequence number is stored; send from the next one")
    settings: Optional[Settings] = None
    commands: List[Command] = Field(default_factory=list)
    poll_after_ms: int = Field(default=0, ge=0, description="Wait this long before the next sync")

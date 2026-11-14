from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict

import jwt
import pytest
from alembic import command
from alembic.config import Config
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import rls, sync
from app.config import settings
from app.db import SessionLocal, SystemSession, owner_engine
from app.deps import get_directory, get_verifier, resolve_throttle
from app.link.pgstore import Listener, PgStore, conninfo
from app.link.service import Link
from app.main import create_app
from app.models import Base
from app.oidc import TokenVerifier
from app.routes import directory_notify
from tests.fake_directory import FakeDirectory

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
VERIFIER = TokenVerifier(settings.oidc_issuer, settings.oidc_audience, ["RS256"], lambda _t: KEY.public_key())
ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


@pytest.fixture(scope="session", autouse=True)
def schema():
    """The real migration, as the owner: the tests also prove the migration."""
    cfg = Config(os.path.join(ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(ROOT, "alembic"))
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(scope="session")
def listener(schema):
    l = Listener(conninfo(settings.system_database_url)).start()
    yield l
    l.stop()


@pytest.fixture(autouse=True)
def clean(schema):
    with owner_engine.begin() as c:
        c.execute(text(f"TRUNCATE {', '.join(t.name for t in Base.metadata.sorted_tables)} RESTART IDENTITY CASCADE"))
    resolve_throttle.hits.clear()
    directory_notify.notify_throttle.hits.clear()


@pytest.fixture()
def db():
    """The database as the system sees it (entry_system's all-access policies)."""
    with SystemSession() as s:
        yield s


def as_person(person_id, platform_admin: bool = False):
    """A session as the API has one for a signed-in person: entry_app with that person's context."""
    s = SessionLocal()
    rls.as_person(s, person_id, platform_admin)
    return s


@pytest.fixture()
def fake() -> FakeDirectory:
    return FakeDirectory()


@pytest.fixture()
def link(listener) -> Link:
    return Link(store=PgStore(SystemSession, listener), wait_s=1.0, poll_s=0.02)


@pytest.fixture()
def client(fake, link):
    app = create_app(link)
    app.dependency_overrides[get_verifier] = lambda: VERIFIER
    app.dependency_overrides[get_directory] = lambda: fake.factory()
    with TestClient(app) as c:
        yield c


def token_for(sub: str, **over) -> str:
    claims = {"sub": sub, "iss": settings.oidc_issuer, "aud": settings.oidc_audience, "exp": datetime.now(timezone.utc) + timedelta(minutes=5)}
    claims.update(over)
    return jwt.encode(claims, KEY, algorithm="RS256")


def auth(sub: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token_for(sub)}"}


def pull(fake: FakeDirectory) -> sync.PullResult:
    with SystemSession() as s:
        return sync.pull(s, fake.factory(), datetime.now(timezone.utc))


class World:
    """Two customers of one partner, already synced into our copy.

    Cedar Works (A): sites a1 (main), a2 (annex).
      a-owner (owner), a-admin (admin), a-admin-s1 (admin of a1 only), a-op (operator), a-viewer (viewer), a-viewer-s2 (viewer of a2 only).
    Birch Co (B): site b1; b-owner.
    `tech`: the partner's technician, admin of both through the partner grant. `stranger`: in the directory with no access.
    `staff`: Photon platform staff, no access row anywhere.
    """

    def __init__(self, fake: FakeDirectory) -> None:
        self.fake = fake
        self.partner = str(uuid.uuid4())
        self.a = fake.add_org("Cedar Works", partner_id=self.partner)
        self.b = fake.add_org("Birch Co", partner_id=self.partner)
        self.a1 = fake.add_site(self.a, "cw-main", "Main office")
        self.a2 = fake.add_site(self.a, "cw-annex", "Annex")
        self.b1 = fake.add_site(self.b, "bc-shop", "Shop")
        self.people: Dict[str, str] = {}
        for sub, org, role, sites in (
            ("a-owner", self.a, "owner", None), ("a-admin", self.a, "admin", None), ("a-admin-s1", self.a, "admin", [self.a1]),
            ("a-op", self.a, "operator", None), ("a-viewer", self.a, "viewer", None), ("a-viewer-s2", self.a, "viewer", [self.a2]),
            ("b-owner", self.b, "owner", None),
        ):
            pid = fake.add_person(sub, name=sub.replace("-", " ").title())
            fake.grant(pid, org, role, sites)
            self.people[sub] = pid
        self.people["tech"] = fake.add_person("tech", name="Tech")
        for org in (self.a, self.b):
            fake.grant(self.people["tech"], org, "admin", source="partner")
        self.people["stranger"] = fake.add_person("stranger", name="Stranger")
        self.people["staff"] = fake.add_person("staff", name="Staff", platform_admin=True)
        assert pull(fake).ok

    def pid(self, sub: str) -> uuid.UUID:
        return uuid.UUID(self.people[sub])


@pytest.fixture()
def world(fake) -> World:
    return World(fake)


def commission_site(site_id) -> None:
    """Sign every door at the site off (a commissioning record each, as an installer would), so the customer's real settings reach them
    (decision 27). Tests about publishing people's access start from commissioned doors; tests about holding doors back do not call this."""
    import uuid as _uuid
    from sqlalchemy import select as _select
    from app.db import SystemSession
    from app.models import Commissioning, Door
    with SystemSession() as s:
        for d in s.execute(_select(Door).where(Door.site_id == _uuid.UUID(str(site_id)))).scalars():
            s.add(Commissioning(id=_uuid.uuid4(), tenant_id=d.tenant_id, site_id=d.site_id, door_id=d.id, controller_door=d.controller_door,
                                jurisdiction="ZZ", lock_type="strike_fail_secure", failure_state="fail_secure", egress="Lever",
                                special_locking="none", fire_release="none_present", rex_checked=True, contact_checked=True,
                                ahj_reference="Test", installer="Test installer", signed_by=_uuid.uuid4(), signed_by_label="Test"))
        s.commit()

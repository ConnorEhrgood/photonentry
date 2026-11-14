from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, Optional

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import access, rls
from app.access import Grant
from app.config import settings
from app.db import SystemSession, get_db
from app.models import Access, Person, utcnow
from app.oidc import TokenError, TokenVerifier, default_verifier
from app.sync import DirectoryFactory, resolve
from app.throttle import Throttle
from photonid_directory_client import DirectoryClient, DirectoryError
from photonid_directory_client.projection import Projection


def get_verifier() -> TokenVerifier:  # overridden in tests
    return default_verifier()


def _make_directory_client(projection: Projection, timeout_s: Optional[float] = None) -> DirectoryClient:
    return DirectoryClient(settings.directory_url, f"{settings.directory_client_id}.{settings.directory_client_secret}", projection,
                           notice_secrets=settings.notice_secrets, timeout_s=timeout_s or settings.directory_timeout_s)


def get_directory() -> Optional[DirectoryFactory]:  # overridden in tests
    """A function that builds the directory client over a projection, or None where no directory is configured (a developer's machine with nothing
    to sync from). The projection is a database session's business, so the client is built where the session is."""
    return _make_directory_client if settings.directory_url else None


def _bearer(authorization: Optional[str]) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token", headers={"WWW-Authenticate": "Bearer"})
    return authorization[7:].strip()


@dataclass(frozen=True)
class Who:
    """The signed-in person, as far as a request needs to know them."""
    id: uuid.UUID
    sub: str
    name: str
    email: str
    is_platform_admin: bool

    @property
    def label(self) -> str:
        return self.name or self.email or str(self.id)


# A first sign-in asks the directory who this is. A person we cannot place asks again every few seconds from the sign-in page; this keeps that
# from becoming a stream of requests to the directory. Keyed by the verified `sub`, which a stranger cannot choose.
resolve_throttle = Throttle(limit=6, window_s=60)


def _pending(detail: str = "Your access is being set up. Try again in a minute.") -> HTTPException:
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail={"code": "access_pending", "detail": detail}, headers={"Retry-After": "30"})


def _no_access() -> HTTPException:
    return HTTPException(status.HTTP_403_FORBIDDEN, detail={"code": "no_access", "detail": "This account has no access to PhotonEntry."})


def _known(sub: str) -> Optional[Person]:
    with SystemSession() as s:   # nobody is identified yet, so the lookup is the system's
        return s.execute(select(Person).where(Person.sub == sub)).scalar_one_or_none()


def _unauthorized() -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token", headers={"WWW-Authenticate": "Bearer"})


def another_app(claims: Dict[str, Any]) -> bool:
    """Was the token issued to another app than PhotonEntry's web client? PhotonID names the client in `client_id` (access tokens) or `azp`."""
    client = claims.get("client_id") or claims.get("azp")
    return bool(settings.oidc_web_client_id and client and client != settings.oidc_web_client_id)


def _person(authorization: Optional[str], db: Session, verifier: TokenVerifier, directory: Optional[DirectoryFactory], any_app: bool) -> Who:
    try:
        claims = verifier.verify(_bearer(authorization))
    except TokenError:
        raise _unauthorized()
    if another_app(claims) and not any_app:
        raise _unauthorized()
    sub = str(claims["sub"])
    person = _known(sub)
    if person is None:
        # Never seen: the directory may have invited them a moment ago and its notice not yet arrived. Ask once, briefly.
        if directory is None or not resolve_throttle.allow(sub):
            raise _pending()
        try:
            with SystemSession() as s:
                known = resolve(s, directory, sub, settings.directory_resolve_timeout_s)
        except DirectoryError:
            raise _pending()
        person = _known(sub) if known else None
        if person is None:
            raise _no_access()
    if not person.active:
        raise _no_access()
    staff = person.is_platform_admin       # the directory says who Photon's staff are (photonid projection.py)
    rls.as_person(db, person.id, staff)
    return Who(person.id, sub, person.name, person.email, staff)


def current_person(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
    verifier: TokenVerifier = Depends(get_verifier),
    directory: Optional[DirectoryFactory] = Depends(get_directory),
) -> Who:
    """The signed-in person, with a token PhotonEntry's own web client asked for."""
    return _person(authorization, db, verifier, directory, any_app=False)


def current_person_any_app(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
    verifier: TokenVerifier = Depends(get_verifier),
    directory: Optional[DirectoryFactory] = Depends(get_directory),
) -> Who:
    """The same, also with a token another suite app asked for (it still has to carry our audience). For GET /v1/summary only."""
    return _person(authorization, db, verifier, directory, any_app=True)




@dataclass(frozen=True)
class Ctx:
    """What a tenant-scoped request knows about the person: their grant in that organization."""
    who: Who
    tenant_id: uuid.UUID
    grant: Grant

    def can(self, capability: str, site_id: Optional[uuid.UUID] = None) -> bool:
        return access.allowed(self.grant, capability, utcnow(), site_id)

    @property
    def source(self) -> str:
        """How the person has this access, for the audit trail: platform staff, partner staff ("Partner support") or the customer's own."""
        return "platform" if self.who.is_platform_admin and self.grant.source != "direct" else self.grant.source

    def need(self, capability: str, site_id: uuid.UUID) -> None:
        """403 unless the person's role at this site has the capability."""
        if not self.can(capability, site_id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed")

    @property
    def capabilities(self) -> FrozenSet[str]:
        return access.capabilities(self.grant, utcnow())


def load_ctx(db: Session, who: Who, tenant_id: uuid.UUID) -> Optional[Ctx]:
    """The person's context in a tenant, or None if they have no live access there."""
    row = db.execute(select(Access).where(Access.person_id == who.id, Access.tenant_id == tenant_id)).scalar_one_or_none()
    if row is None or not access.is_active(Grant.from_row(row), utcnow()):
        return None
    return Ctx(who, tenant_id, Grant.from_row(row))


def tenant_ctx(tenant_id: uuid.UUID, who: Who = Depends(current_person), db: Session = Depends(get_db)) -> Ctx:
    """404 (not 403) for organizations the caller has no access to, so organization ids can't be probed."""
    ctx = load_ctx(db, who, tenant_id)
    if ctx is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return ctx


def require(capability: str):
    """A dependency: the tenant context, provided the person's role has `capability` (403 otherwise). Site checks happen where a site is named."""
    def dep(ctx: Ctx = Depends(tenant_ctx)) -> Ctx:
        if not ctx.can(capability):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed")
        return ctx
    return dep

"""The PhotonEntry API: the integrator's and customer's routes (PhotonID sign-in, row-level security) and the link service for controllers
(`/link/v1/...`, served on link.entry.photonind.com; signed by each controller's own key)."""
from __future__ import annotations

from typing import Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import DataError

from app.config import settings
from app.link.service import Link, router as link_router

CORS_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


class SummaryCors:
    """CORS for the account app's home dashboard on GET /v1/summary only (the web app's own origins are CORSMiddleware's). Plain ASGI: it answers the
    preflight itself and adds the header to the answer; every other request passes through untouched."""

    def __init__(self, app, path: str, origin: str) -> None:
        self.app, self.path, self.origin = app, path, origin

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] != self.path or dict(scope["headers"]).get(b"origin", b"").decode() != self.origin:
            return await self.app(scope, receive, send)
        allow = [(b"access-control-allow-origin", self.origin.encode()), (b"vary", b"Origin")]
        if scope["method"] == "OPTIONS":
            await send({"type": "http.response.start", "status": 204, "headers": allow + [
                (b"access-control-allow-methods", b"GET"), (b"access-control-allow-headers", b"Authorization"), (b"access-control-max-age", b"600")]})
            return await send({"type": "http.response.body", "body": b""})

        async def with_cors(message):
            if message["type"] == "http.response.start":
                message = {**message, "headers": list(message.get("headers", [])) + allow}
            await send(message)
        await self.app(scope, receive, with_cors)


def create_app(link: Link, routes: bool = True) -> FastAPI:
    """`routes=False`: the link service alone (the Step 1 tests run it on the in-memory store, with no database)."""
    problem = settings.production_safe()
    if problem:
        raise RuntimeError(f"Unsafe production configuration: {problem}")
    prod = settings.environment == "production"
    app = FastAPI(title="PhotonEntry API", docs_url=None if prod else "/docs", redoc_url=None, openapi_url=None if prod else "/openapi.json")
    app.state.link = link
    app.include_router(link_router(link))

    @app.get("/healthz")
    def healthz():
        """Liveness: the process answers (no dependencies)."""
        return {"ok": True}

    if not routes:
        return app

    from app.db import engine, system_engine
    from app.routes import actions, cardholders, config, controllers, directory_notify, integrations, intercoms, me, provision, summary, tenants
    for r in (me, tenants, directory_notify, controllers, config, cardholders, actions, integrations, intercoms, provision, summary):
        app.include_router(r.router)
    app.include_router(tenants.catalog_router)
    if settings.cors_list:
        app.add_middleware(CORSMiddleware, allow_origins=settings.cors_list, allow_methods=CORS_METHODS,
                           allow_headers=["Authorization", "Content-Type"], max_age=600)
    app.add_middleware(SummaryCors, path=summary.PATH, origin=settings.account_origin)      # added last: outside CORSMiddleware, sees its preflight first

    @app.on_event("startup")
    def startup_checks() -> None:
        if prod:
            refuse_logins_that_bypass_row_level_security(engine, system_engine)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        return resp

    @app.exception_handler(DataError)
    async def unstorable_value(request: Request, exc: DataError):
        return JSONResponse({"detail": "The request holds a value that can't be stored"}, status_code=422)

    @app.get("/readyz")
    def readyz():
        with system_engine.connect() as c:
            c.execute(text("SELECT 1"))
        return {"ok": True}

    return app


def refuse_logins_that_bypass_row_level_security(app_engine, system_engine) -> None:
    """Neither login may be a superuser, have BYPASSRLS, or own the tables (an owner skips its tables' policies too, without either flag):
    any of them would make row-level security decoration."""
    for name, eng in (("DATABASE_URL", app_engine), ("SYSTEM_DATABASE_URL", system_engine)):
        with eng.connect() as c:
            if c.execute(text("SELECT rolsuper OR rolbypassrls OR EXISTS (SELECT 1 FROM pg_tables WHERE schemaname = 'public' "
                              "AND tableowner = current_user) FROM pg_roles WHERE rolname = current_user")).scalar():
                raise RuntimeError(f"{name} connects as a role that bypasses row-level security. Use entry_app / entry_system")


def production_link() -> Link:
    from app.db import SystemSession
    from app.link.pgstore import Listener, PgStore, conninfo
    listener = Listener(conninfo(settings.system_database_url or settings.database_url)).start()
    return Link(store=PgStore(SystemSession, listener), wait_s=settings.link_wait_s)


_app: Optional[FastAPI] = None


def __getattr__(name: str):
    """`app.main:app` for uvicorn, built on first use (importing this module for tests builds nothing and connects to nothing)."""
    global _app
    if name == "app":
        if _app is None:
            _app = create_app(production_link())
        return _app
    raise AttributeError(name)

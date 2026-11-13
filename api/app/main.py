"""The PhotonEntry API. Step 1 serves only the link (controllers) on an in-memory store; Step 2 adds the database, PhotonID sign-in and the
integrator's routes (BUILD-GUIDE §2)."""
from __future__ import annotations

from fastapi import FastAPI

from app.link.service import Link, router
from app.link.store import MemoryStore


def create_app(link: Link) -> FastAPI:
    app = FastAPI(title="PhotonEntry API", docs_url=None, redoc_url=None, openapi_url=None)
    app.include_router(router(link))

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    return app


link = Link(store=MemoryStore())
app = create_app(link)

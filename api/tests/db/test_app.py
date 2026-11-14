"""The app itself: health, headers, start-up guards, CORS, the lazily built production app, the link listener's recovery."""
from __future__ import annotations

import time
import uuid

import pytest
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from sqlalchemy.exc import DataError

import app.main as main
from app.config import settings
from app.db import SessionLocal, SystemSession, engine, owner_engine, system_engine
from app.link.pgstore import Listener, PgStore, conninfo
from app.link.service import Link
from app.link.store import MemoryStore


def test_healthz_readyz_and_security_headers(client, db):
    r = client.get("/healthz")
    assert r.json() == {"ok": True}
    # No worker yet: not ready, and it says why.
    r = client.get("/readyz")
    assert r.status_code == 503 and r.json()["problems"] == ["the worker has not been heard from in two minutes"]
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["referrer-policy"] == "no-referrer"
    from app import worker
    worker.heartbeat()
    r = client.get("/readyz")
    assert r.status_code == 200 and r.json()["ok"] is True and r.json()["version"] == "dev" and r.json()["started_at"]
    # Migrations behind this release's head.
    from app import main
    real = main.MIGRATIONS_HEAD
    main.MIGRATIONS_HEAD = "9999"
    try:
        assert client.get("/readyz").json()["problems"] == ["migrations are not at this release's head"]
    finally:
        main.MIGRATIONS_HEAD = real


def test_every_answer_carries_a_request_id(client):
    r = client.get("/healthz", headers={"X-Request-ID": "abc12345-from-console"})
    assert r.headers["x-request-id"] == "abc12345-from-console"
    made = client.get("/healthz", headers={"X-Request-ID": "bad id with spaces"}).headers["x-request-id"]
    assert len(made) == 32 and made != "bad id with spaces"


def test_a_database_that_does_not_answer_is_not_ready(client, monkeypatch):
    from app import db as dbmod

    class Broken:
        def connect(self):
            raise OSError("down")
    import app.main as main
    monkeypatch.setattr(dbmod, "system_engine", Broken())
    app = main.create_app(client.app.state.link)
    from fastapi.testclient import TestClient
    r = TestClient(app).get("/readyz")
    assert r.status_code == 503 and r.json()["problems"] == ["the database does not answer"]


def test_a_value_the_database_refuses_is_a_422_not_a_500(client):
    def bad():
        raise DataError("x", {}, Exception("NUL"))
    client.app.add_api_route("/__test_dataerror", bad)
    r = client.get("/__test_dataerror")
    assert r.status_code == 422 and "can't be stored" in r.json()["detail"]


def test_logins_that_bypass_row_level_security_are_refused():
    main.refuse_logins_that_bypass_row_level_security(engine, system_engine)          # the real logins are restricted
    with pytest.raises(RuntimeError, match="^DATABASE_URL"):
        main.refuse_logins_that_bypass_row_level_security(owner_engine, system_engine)
    with pytest.raises(RuntimeError, match="SYSTEM_DATABASE_URL"):
        main.refuse_logins_that_bypass_row_level_security(engine, owner_engine)


def test_production_runs_the_start_up_check(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(main, "settings", SimpleNamespace(environment="production", production_safe=lambda: None, cors_list=[],
                                                        account_origin="https://account.photonind.com"))
    called = []
    monkeypatch.setattr(main, "refuse_logins_that_bypass_row_level_security", lambda a, b: called.append((a, b)))
    with TestClient(main.create_app(Link(store=MemoryStore()))):
        pass
    assert called == [(engine, system_engine)]


def test_an_unsafe_production_configuration_stops_the_app(monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    with pytest.raises(RuntimeError, match="Unsafe production configuration"):
        main.create_app(Link(store=MemoryStore()))


def test_cors_only_when_origins_are_configured(monkeypatch):
    assert not any(m.cls is CORSMiddleware for m in main.create_app(Link(store=MemoryStore())).user_middleware)
    monkeypatch.setattr(settings, "cors_origins", "https://entry.photonind.com")
    assert any(m.cls is CORSMiddleware for m in main.create_app(Link(store=MemoryStore())).user_middleware)


def test_the_link_alone_has_no_routes_of_the_integrator():
    app = main.create_app(Link(store=MemoryStore()), routes=False)
    with TestClient(app) as c:
        assert c.get("/healthz").status_code == 200 and c.get("/me").status_code == 404 and c.post("/link/v1/sync").status_code == 401


def test_the_production_app_is_built_once_on_first_use(monkeypatch):
    monkeypatch.setattr(main, "_app", None)
    built = main.app
    assert main.app is built and isinstance(built.state.link.store, PgStore)
    built.state.link.store.listener.stop()
    monkeypatch.setattr(main, "_app", None)
    with pytest.raises(AttributeError):
        main.nothing_here


def test_the_listener_recovers_from_a_database_it_cannot_reach():
    bad = Listener("postgresql://nobody:wrong@127.0.0.1:1/none").start()
    assert bad.ready.is_set()                     # it tried, failed, and does not hold up start-up
    bad.stop()
    good = Listener(conninfo(settings.system_database_url)).start()
    epoch = good.mark("x")
    with SystemSession() as s:
        from app.link.pgstore import notify
        notify(s, "x")
        s.commit()
    for _ in range(100):
        if good.mark("x") > epoch:
            break
        time.sleep(0.02)
    assert good.mark("x") > epoch
    good.stop()


def test_a_store_without_a_listener_never_wakes_a_sync():
    assert PgStore(SystemSession).mark(str(uuid.uuid4())) == 0

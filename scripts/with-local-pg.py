"""Run a command with a throwaway local Postgres 16 (pip package `pgserver`, development only) and the database test environment set.

    ~/.venvs/photonentry/bin/python scripts/with-local-pg.py -- python -m pytest api/tests/db

Fast iteration on the runner, which has no Docker. The authoritative run is `scripts/remote-test.sh` (Postgres 16 in Docker on LXC 800).
As there: a plain (non-superuser) owner role runs the migrations; the routes connect as `entry_app` (row-level security applies), the link and
the sync as `entry_system`.
"""
import os
import subprocess
import sys
import tempfile

os.environ.setdefault("LANG", "C.UTF-8")
os.environ.setdefault("LC_ALL", "C.UTF-8")
import pgserver  # noqa: E402

if "--" not in sys.argv:
    sys.exit(__doc__)
cmd = sys.argv[sys.argv.index("--") + 1:]
with tempfile.TemporaryDirectory(prefix="pe-entry-pg-") as data:
    server = pgserver.get_server(data, cleanup_mode="stop")
    try:
        server.psql("CREATE ROLE entry_owner LOGIN CREATEROLE PASSWORD 'owner-test-password'")
        server.psql("CREATE DATABASE entry_test OWNER entry_owner")
        host = server.get_uri().split("host=")[1]
        env = dict(os.environ)
        env.update(
            PHOTONENTRY_DB_TESTS="1",
            DATABASE_URL=f"postgresql+psycopg://entry_app:apptestpassword0123456789@/entry_test?host={host}",
            SYSTEM_DATABASE_URL=f"postgresql+psycopg://entry_system:systemtestpassword0123456789@/entry_test?host={host}",
            MIGRATE_DATABASE_URL=f"postgresql+psycopg://entry_owner:owner-test-password@/entry_test?host={host}",
            APP_DB_PASSWORD="apptestpassword0123456789",
            SYSTEM_DB_PASSWORD="systemtestpassword0123456789",
        )
        sys.exit(subprocess.call(cmd, env=env))
    finally:
        server.cleanup()

# PhotonEntry: working on it

Layout:
- `api/`: the cloud (FastAPI): the integrator's routes, the link service, the site document and the compiler, the directory copy, Postgres (Alembic).
- `web/`: the integrator's and customer's web app (React 19 + Vite, photon-ui vendored, the shared PhotonID sign-in). Dev port 5193.
- `acap/entry-link/`: the app on the controller (C).
- `sim/`: the Axis controller simulator, with its reference.
- `contract/`: JSON Schemas, samples and the signing vector.
- `tests/e2e/`: the end-to-end tests.
- `scripts/`, `docs/`.

## Tools (the runner loses everything outside /home/connor)

```
python3 -m venv ~/.venvs/photonentry
~/.venvs/photonentry/bin/pip install -r api/requirements-dev.txt -r api/requirements-local.txt
```

The C build needs gcc, make, the libcurl and OpenSSL headers. The runner has them; they come with the system image. cJSON is vendored
(`acap/vendor/cjson`).

## Tests

| What | Command |
|---|---|
| Everything, with the 100% gate on the CRITICAL modules | `scripts/test-all.sh` (a throwaway local Postgres on the runner; about three minutes) |
| The authoritative run | `scripts/test-all.sh --remote`, or `COVERAGE=1 scripts/remote-test.sh` (LXC 800, Postgres 16 in Docker) |
| Python, no database | `~/.venvs/photonentry/bin/python -m pytest -p no:warnings` (from the repo root; the database suite is skipped) |
| Python with the database | `~/.venvs/photonentry/bin/python scripts/with-local-pg.py -- ~/.venvs/photonentry/bin/python -m pytest -p no:warnings` |
| One part | `... -m pytest api/tests`, `sim/tests`, `tests/e2e` |
| entry-link | `make -C acap/entry-link` (host build, `-Werror`) |
| The web app | `cd web && npx vitest run --coverage` (a ratchet: raise the thresholds, never lower them); `node scripts/screenshots.mjs [name]` shoots every page at 1440×900, 820×1180 and 390×844 into `web/screenshots/` (look at them) |
| Sign-in against the dev PhotonID | `cd web && VITE_API_URL=https://api.test npx vite build --mode development && node scripts/signin-contract.mjs <dir>` (real PhotonID at 10.10.0.80:8085, the API faked in the browser; needs `~/keys/zitadel-dev-provisioner.pat`; makes one test person and deletes it) |
| photon-ui copies | `node ../photon-ui/scripts/sync-vendored.mjs web/src --css --base --auth` (never edit `web/src/shell`, `ph-auth`, `tokens.css`, `ph-*.css`) |
| The contract files | `~/.venvs/photonentry/bin/python scripts/contract.py` writes them; `--check` (run by the tests) fails if they are stale |

`KEEP_E2E_LOGS=1` copies the last end-to-end run's `entry-link` log to `entry-link-e2e.log` at the repo root.

## Running the pieces by hand

```
# the simulator (an A1610 on 127.0.0.1:8134, login root/pass)
cd sim && ~/.venvs/photonentry/bin/python -c "from axis_sim.device import Device; from axis_sim.server import run, SimClock; import time; run(Device(clock=SimClock())); time.sleep(1e9)"
# the link service alone, in memory, on 127.0.0.1:8133 (the full API needs Postgres: DATABASE_URL and friends, see app/config.py)
cd api && ~/.venvs/photonentry/bin/python -c "import uvicorn; from app.main import create_app; from app.link.service import Link; from app.link.store import MemoryStore; uvicorn.run(create_app(Link(store=MemoryStore()), routes=False), port=8133)"
# entry-link between them
ENTRY_LINK_CLOUD=http://127.0.0.1:8133 ENTRY_LINK_VAPIX=http://127.0.0.1:8134 ENTRY_LINK_VAPIX_USER=root ENTRY_LINK_VAPIX_PASS=pass \
  ENTRY_LINK_STATE_DIR=/tmp/entry-link acap/entry-link/build/entry-link
```

`entry-link` prints its claim code. With the full API, an admin claims it with `POST /tenants/{org}/controllers/claim`; with the link alone,
the tests claim through the store (`store.claim`).

## Conventions

- **Tokens on the controller:** PhotonEntry owns only objects whose token starts with `pe-`:
  - `pe-s-` schedule, `pe-g-` access profile (group), `pe-u-` user, `pe-c-` credential, `pe-d-` door schedule.
  - `entry-link` never touches anything else, apart from the timing fields and the schedule link of the doors the settings name.
- **The order of changes on a controller:**
  - Set: schedules, access profiles, users, credentials, door schedules; then doors.
  - Remove, in reverse: door schedules, credentials, users, access profiles, schedules.
  - The controller checks references when an object is stored, and the simulator checks them strictly.
- **Events:**
  - **Sequence numbers** are assigned by `entry-link` when it reads an event from the controller's log. They are stored on disk before the
    row cursor moves.
  - **The cloud** stores events exactly once, in order, and acknowledges with `ack_seq`.
  - **After a crash,** duplicates are possible and losses are not. `ref` (the controller's event token) identifies a duplicate.
- **Commands** carry `expires_at`. `entry-link` refuses one that arrives late and remembers the last 64 ids it carried out.

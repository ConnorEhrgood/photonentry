# PhotonEntry: working on it

Layout:
- `api/`: the cloud (FastAPI). Today the link service, the site document and the compiler; the database arrives in Step 2.
- `acap/entry-link/`: the app on the controller (C).
- `sim/`: the Axis controller simulator, with its reference.
- `contract/`: JSON Schemas, samples and the signing vector.
- `tests/e2e/`: the end-to-end tests.
- `scripts/`, `docs/`.

## Tools (the runner loses everything outside /home/connor)

```
python3 -m venv ~/.venvs/photonentry
~/.venvs/photonentry/bin/pip install -r api/requirements-dev.txt
```

The C build needs gcc, make, the libcurl and OpenSSL headers. The runner has them; they come with the system image. cJSON is vendored
(`acap/vendor/cjson`).

## Tests

| What | Command |
|---|---|
| Everything, with the 100% gate on the CRITICAL modules | `scripts/test-all.sh` |
| Python only | `~/.venvs/photonentry/bin/python -m pytest -p no:warnings` (from the repo root; about a minute, most of it end to end) |
| One part | `... -m pytest api/tests`, `sim/tests`, `tests/e2e` |
| entry-link | `make -C acap/entry-link` (host build, `-Werror`) |
| The contract files | `~/.venvs/photonentry/bin/python scripts/contract.py` writes them; `--check` (run by the tests) fails if they are stale |

`KEEP_E2E_LOGS=1` copies the last end-to-end run's `entry-link` log to `entry-link-e2e.log` at the repo root.

## Running the pieces by hand

```
# the simulator (an A1610 on 127.0.0.1:8134, login root/pass)
cd sim && ~/.venvs/photonentry/bin/python -c "from axis_sim.device import Device; from axis_sim.server import run, SimClock; import time; run(Device(clock=SimClock())); time.sleep(1e9)"
# the link service (in memory) on 127.0.0.1:8133
cd api && ~/.venvs/photonentry/bin/uvicorn app.main:app --port 8133
# entry-link between them
ENTRY_LINK_CLOUD=http://127.0.0.1:8133 ENTRY_LINK_VAPIX=http://127.0.0.1:8134 ENTRY_LINK_VAPIX_USER=root ENTRY_LINK_VAPIX_PASS=pass \
  ENTRY_LINK_STATE_DIR=/tmp/entry-link acap/entry-link/build/entry-link
```

`entry-link` prints its claim code. Step 1 has no claim API, so claiming happens in the tests (`store.claim`). Step 2 adds the integrator's
route for it.

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

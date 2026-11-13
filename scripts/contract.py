"""Write the contract files that are generated from code:  ~/.venvs/photonentry/bin/python scripts/contract.py [--check]

- contract/link/*.schema.json from the link protocol's models (api/app/link/protocol.py);
- contract/settings/sample.json: the compiled settings of the test site's controller A (api/tests/fixtures/site.py), which the C side's tests
  apply to the simulator;
- contract/templates/catalog.json: the site templates as GET /templates returns them, which the web app's tests and screenshots use;
- contract/guard/samples/*.json: what PhotonEntry sends PhotonGuard for a grant, a denial, a forced door and its end (app/guard.py).

`--check` writes nothing and exits 1 if a file would change (tests run it, so the contract can never drift from the code).
"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "api")]

from app.compiler.axis import compile_controller  # noqa: E402
from app import templates  # noqa: E402
from app.link import protocol  # noqa: E402
from tests.fixtures.site import INVENTORY_A, site  # noqa: E402

MODELS = {"hello.request": protocol.HelloRequest, "hello.response": protocol.HelloResponse,
          "sync.request": protocol.SyncRequest, "sync.response": protocol.SyncResponse}


def guard_samples() -> dict:
    """Fixed events through the real sender (app/guard.message), with fixed ids, so the samples change only when the sender does."""
    import uuid
    from datetime import datetime, timezone
    from app.events import normalize
    from app.guard import message
    from app.models import Door, DoorEvent
    cid = uuid.UUID("0c000000-0000-4000-8000-000000000001")
    door = Door(id=uuid.UUID("0d000000-0000-4000-8000-000000000001"), site_id=uuid.UUID("05000000-0000-4000-8000-000000000001"), name="Side door")
    at = datetime(2026, 11, 16, 15, 0, tzinfo=timezone.utc)

    def ev(seq, topic, data, ref):
        return DoorEvent(controller_id=cid, seq=seq, occurred_at=at, topic=topic, source={}, data=data, ref=ref)
    granted = ev(1, "AccessControl/AccessGranted/Credential", {}, "Axis-b8a44f:1700000000.000000001")
    denied = ev(2, "AccessControl/Denied/Credential", {"Reason": "NotPermittedAtThisTime"}, "Axis-b8a44f:1700000000.000000002")
    forced = ev(3, "Door/State/DoorAlarm", {"State": "DoorForcedOpen"}, "Axis-b8a44f:1700000000.000000003")
    cleared = ev(4, "Door/State/DoorAlarm", {"State": "Normal"}, "Axis-b8a44f:1700000000.000000004")
    started = message(forced, normalize(forced.topic, forced.data), door, None, {})
    return {
        "granted": message(granted, normalize(granted.topic, granted.data), door, "Bob Jones", {}).payload,
        "denied": message(denied, normalize(denied.topic, denied.data), door, "Bob Jones", {}).payload,
        "forced-started": started.payload,
        "forced-ended": message(cleared, normalize(cleared.topic, cleared.data), door, None, {"alarm": started.opens[1]}).payload,
    }


def files() -> dict:
    out = {}
    for name, model in MODELS.items():
        out[f"contract/link/{name}.schema.json"] = json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n"
    out["contract/settings/sample.json"] = json.dumps(compile_controller(site(), "ctl-a", INVENTORY_A), indent=2) + "\n"
    out["contract/templates/catalog.json"] = json.dumps(templates.catalog(), indent=2) + "\n"
    for name, payload in guard_samples().items():
        out[f"contract/guard/samples/{name}.json"] = json.dumps(payload, indent=2) + "\n"
    return out


def main(check: bool) -> int:
    stale = []
    for rel, text in files().items():
        path = os.path.join(ROOT, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        current = open(path).read() if os.path.exists(path) else None
        if current != text:
            stale.append(rel)
            if not check:
                with open(path, "w") as f:
                    f.write(text)
    if stale:
        print(("out of date: " if check else "wrote: ") + ", ".join(stale))
    return 1 if (check and stale) else 0


if __name__ == "__main__":
    sys.exit(main("--check" in sys.argv))

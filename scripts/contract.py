"""Write the contract files that are generated from code:  ~/.venvs/photonentry/bin/python scripts/contract.py [--check]

- contract/link/*.schema.json from the link protocol's models (api/app/link/protocol.py);
- contract/settings/sample.json: the compiled settings of the test site's controller A (api/tests/fixtures/site.py), which the C side's tests
  apply to the simulator;
- contract/templates/catalog.json: the site templates as GET /templates returns them, which the web app's tests and screenshots use.

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


def files() -> dict:
    out = {}
    for name, model in MODELS.items():
        out[f"contract/link/{name}.schema.json"] = json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n"
    out["contract/settings/sample.json"] = json.dumps(compile_controller(site(), "ctl-a", INVENTORY_A), indent=2) + "\n"
    out["contract/templates/catalog.json"] = json.dumps(templates.catalog(), indent=2) + "\n"
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

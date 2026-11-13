"""The contract files generated from code (scripts/contract.py) must match the code."""
from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "..")


def test_contract_is_current():
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "contract.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr

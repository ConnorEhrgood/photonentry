"""The C signer (acap/entry-link/app/sign.c) produces exactly the header the cloud's signer does for the shared vector."""
from __future__ import annotations

import json
import os
import subprocess

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def test_c_signer_matches_the_vector():
    subprocess.run(["make", "-s", "-C", os.path.join(ROOT, "acap", "entry-link")], check=True, capture_output=True)
    path = os.path.join(ROOT, "contract", "link", "vectors.json")
    out = subprocess.run([os.path.join(ROOT, "acap", "entry-link", "build", "entry-link"), "--sign-vector", path],
                         capture_output=True, text=True, check=True).stdout.split()
    v = json.load(open(path))
    assert out == [v["header"], v["public_key"]]

from __future__ import annotations

import pytest

from axis_sim.testing import Sim


@pytest.fixture()
def sim() -> Sim:
    return Sim()

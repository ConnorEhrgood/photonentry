"""`python -m demo_sim run`: the demo's simulators (docs/DEMO.md). Settings from the environment:

    DEMO_STATE        the state folder (a volume)                       default /state
    DEMO_CLOUD        PhotonEntry's link, as a controller dials it       default https://link.entry.photonind.com
    DEMO_PROVISION    PhotonEntry's provisioning server, for intercoms   default https://prov.entry.photonind.com
    DEMO_ENTRY_LINK   the entry-link program                             default /usr/local/bin/entry-link
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from demo_sim.run import Runner


def main(argv: list[str]) -> int:
    if argv[1:] != ["run"]:
        print(__doc__, file=sys.stderr)
        return 2
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    Runner(Path(os.environ.get("DEMO_STATE", "/state")), os.environ.get("DEMO_CLOUD", "https://link.entry.photonind.com"),
           os.environ.get("DEMO_PROVISION", "https://prov.entry.photonind.com"),
           os.environ.get("DEMO_ENTRY_LINK", "/usr/local/bin/entry-link")).main()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

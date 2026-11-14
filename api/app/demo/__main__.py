"""`python -m app.demo seed < claims.json > roster.json`, `remove`, `status` (docs/DEMO.md; run by scripts/demo.sh in the stack's
one-shot `demo` service, as the database owner). The roster holds the simulators' cards and the intercoms' provisioning addresses: it goes
only to the demo simulators, through the pipe, never to a file on the PhotonEntry host."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

from sqlalchemy.orm import sessionmaker

from app.demo import seed as demo_seed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.demo")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("seed", help="set the demo up from the simulators' claim codes on stdin; the roster to stdout")
    s.add_argument("--timeout", type=float, default=180.0)
    sub.add_parser("remove", help="delete every PhotonEntry row of the demo organization")
    sub.add_parser("status", help="what the demo holds now")
    args = ap.parse_args(argv)

    from app.db import owner_engine
    with sessionmaker(bind=owner_engine, autoflush=False, expire_on_commit=False)() as db:
        try:
            if args.cmd == "seed":
                claims = json.load(sys.stdin)
                roster = demo_seed.seed(db, claims, datetime.now(timezone.utc), timeout_s=args.timeout)
                json.dump(roster, sys.stdout)
                print(f"demo seeded: {json.dumps(demo_seed.summary(db))}", file=sys.stderr)
            elif args.cmd == "remove":
                print(f"demo removed: {json.dumps(demo_seed.remove(db))}", file=sys.stderr)
            else:
                print(json.dumps(demo_seed.summary(db)))
        except demo_seed.SeedError as e:
            print(f"demo: {e}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

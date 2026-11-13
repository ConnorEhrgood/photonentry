#!/usr/bin/env bash
# Every suite, stopping at the first failure:  scripts/test-all.sh
#   the contract check, entry-link built with -Werror, then all Python tests (cloud unit tests, the simulator, and end to end: the real C
#   entry-link between the simulator and the link service) with branch coverage and the 100% gate on the CRITICAL modules.
# No hardware, no database, no Docker: everything runs on the runner. (Step 2 adds the Postgres suite on LXC 800.)
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PHOTONENTRY_VENV:-$HOME/.venvs/photonentry}/bin/python
step() { printf '\n\033[1m== %s\033[0m\n' "$*"; }

step "contract: generated files match the code"; "$PY" scripts/contract.py --check
step "entry-link: host build (-Wall -Wextra -Werror)"; make -s -C acap/entry-link
step "tests, with branch coverage"
"$PY" -m pytest -p no:warnings --cov=app --cov=axis_sim --cov-branch --cov-report= 2>&1 | tail -2
step "the 100% gate on CRITICAL modules"
"$PY" -m coverage report --fail-under=100 --include='api/app/link/signing.py,api/app/link/service.py,api/app/link/store.py,api/app/compiler/*,api/app/document.py' | tail -3
printf '\n\033[1mall green\033[0m\n'

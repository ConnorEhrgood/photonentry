#!/usr/bin/env bash
# Every suite, stopping at the first failure:  scripts/test-all.sh [--remote]
#   the contract check, entry-link built with -Werror, then the whole Python suite (cloud, simulator, end to end with the real C entry-link,
#   and the database suite on a throwaway local Postgres 16) with branch coverage and the 100% gate on the CRITICAL modules.
#   --remote   the authoritative run instead: the same suite on LXC 800, Postgres 16 in Docker (scripts/remote-test.sh)
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PHOTONENTRY_VENV:-$HOME/.venvs/photonentry}/bin/python
step() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
COV=$(mktemp)
trap 'rm -f "$COV"' EXIT

step "contract: generated files match the code"; "$PY" scripts/contract.py --check
step "entry-link: host build (-Wall -Wextra -Werror)"; make -s -C acap/entry-link
if [ "${1:-}" = "--remote" ]; then
  step "everything on LXC 800, with coverage"; COVERAGE=1 scripts/remote-test.sh 2>&1 | tail -3
else
  step "everything, on a local Postgres, with branch coverage"
  "$PY" scripts/with-local-pg.py -- "$PY" -m pytest -p no:warnings --cov=app --cov-branch --cov-report= --cov-report=json:"$COV" 2>&1 \
    | grep -v RuntimeDir | tail -1
  step "the 100% gate on CRITICAL modules"; "$PY" api/tests/check_critical.py "$COV"
fi
printf '\n\033[1mall green\033[0m\n'

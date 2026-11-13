#!/usr/bin/env bash
# The whole suite on LXC 800 (Docker lives there, not on the runner), against Postgres 16 in Docker:
#   scripts/remote-test.sh [pytest args]            e.g. scripts/remote-test.sh api/tests/db/test_rls_entry.py -x
#   COVERAGE=1 scripts/remote-test.sh               with branch coverage and the critical-module check
# Its own folder (/root/entry-test/suite) and Compose project (photonentry-test); takes everything down afterwards. LXC 800 is shared and
# short of disk: this never prunes Docker globally (remove the image with `docker image rm photonentry-test-tests` when done for a while).
set -euo pipefail
cd "$(dirname "$0")/.."
HOST=${ENTRY_TEST_SSH:-lxc800}
DIR=${ENTRY_TEST_DIR:-/root/entry-test/suite}
PROJECT=photonentry-test
ARGS="$(printf '%q ' "$@")"
if [ "${COVERAGE:-}" = 1 ]; then
  PYTEST="sh -c 'python -m pytest -p no:warnings --cov=app --cov-branch --cov-report=term-missing:skip-covered --cov-report=json:/tmp/cov.json $ARGS && python api/tests/check_critical.py /tmp/cov.json'"
else
  PYTEST="python -m pytest -p no:warnings $ARGS"
fi

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
tar --exclude='__pycache__' --exclude='.pytest_cache' --exclude='.coverage' --exclude='.env' --exclude='acap/entry-link/build' --exclude='.git' \
    -czf "$TMP/suite.tgz" api sim acap contract tests scripts conftest.py pytest.ini Dockerfile.test docker-compose.test.yml
cat > "$TMP/run.sh" <<RUN
#!/bin/bash
cd $DIR
rm -f run.done run.out
if docker compose -p $PROJECT -f docker-compose.test.yml build --quiet tests > build.out 2>&1; then
  docker compose -p $PROJECT -f docker-compose.test.yml run --rm tests $PYTEST > run.out 2>&1
else
  cp build.out run.out; false
fi
echo \$? > run.done
docker compose -p $PROJECT -f docker-compose.test.yml down -v --remove-orphans > /dev/null 2>&1
RUN
scp -q "$TMP/suite.tgz" "$HOST":/tmp/$PROJECT.tgz
scp -q "$TMP/run.sh" "$HOST":/tmp/$PROJECT-run.sh
ssh "$HOST" "rm -rf $DIR && mkdir -p $DIR && tar -xzf /tmp/$PROJECT.tgz -C $DIR && rm -f /tmp/$PROJECT.tgz && mv /tmp/$PROJECT-run.sh $DIR/run.sh && systemd-run --unit=$PROJECT-\$(date +%s) --collect bash $DIR/run.sh" > /dev/null
for _ in $(seq 1 240); do
  sleep 5
  if ssh "$HOST" test -f $DIR/run.done 2>/dev/null; then
    ssh "$HOST" cat $DIR/run.out
    exit "$(ssh "$HOST" cat $DIR/run.done)"
  fi
done
echo "timed out waiting for tests" >&2
exit 1

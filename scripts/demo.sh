#!/usr/bin/env bash
# The demo organization's PhotonEntry part (docs/DEMO.md). Run on the runner; hosts are SSH aliases:
#   <sim>    the demo simulator host (the operator's decision: never a production host)
#   <entry>  the host running the PhotonEntry stack (prod, staging, or a test host)
#
#   scripts/demo.sh build  <sim> [<ref>]          ship the commit (default origin/main) to <sim> and build the simulators' image there
#   scripts/demo.sh seed   <sim> <entry>
#                                                 fresh simulators, their claim codes into the seed, the seed's roster back to them;
#                                                 then they write the history and go live. Idempotent: the seed removes any earlier demo first
#   scripts/demo.sh reset  <sim> <entry>          remove, then seed
#   scripts/demo.sh remove <sim> <entry>          stop the simulators, delete their volume, delete the demo's PhotonEntry rows
#   scripts/demo.sh status <sim> <entry>
#
# The roster (cards, the intercoms' provisioning addresses) goes from the seed straight into the simulators through the pipe: it is never
# written on the runner or the PhotonEntry host. Nothing here prints a secret. DEMO_CLOUD and DEMO_PROVISION override the public names, DEMO_SIM_BASE
# and DEMO_ENTRY_BASE the folders (a test host).
set -euo pipefail
cd "$(dirname "$0")/.."

CMD=${1:?usage: scripts/demo.sh build|seed|reset|remove|status <sim> [<entry>]}
SIM=${2:?the demo simulator host (an SSH alias)}
SIM_BASE=${DEMO_SIM_BASE:-/opt/photon/photonentry-demo}       # overridable for a test host
ENTRY_BASE=${DEMO_ENTRY_BASE:-/opt/photon/photonentry}

sim() {   # run a compose command for the simulators on <sim>
  ssh "$SIM" "cd $SIM_BASE/src && BUILD_SHA=\$(cat $SIM_BASE/BUILD_SHA) DEMO_CLOUD='${DEMO_CLOUD:-https://link.entry.photonind.com}' \
    DEMO_PROVISION='${DEMO_PROVISION:-https://prov.entry.photonind.com}' docker compose -f deploy/demo/compose.yml $*"
}
entry() { # run the stack's one-shot demo service on <entry>, in the release that is running
  ssh "$ENTRY" "cd $ENTRY_BASE/current && BUILD_SHA=\$(basename \$(readlink -f $ENTRY_BASE/current)) \
    docker compose --env-file $ENTRY_BASE/.env -f docker-compose.yml --profile demo run --rm -T demo $*"
}

case "$CMD" in
  build)
    git fetch -q origin main
    SHA=$(git rev-parse --verify "${3:-origin/main}^{commit}")
    echo "== shipping $SHA to $SIM"
    git archive --format=tar.gz "$SHA" | ssh "$SIM" "set -e; rm -rf $SIM_BASE/src.tmp; mkdir -p $SIM_BASE/src.tmp; tar -xzf - -C $SIM_BASE/src.tmp
      rm -rf $SIM_BASE/src; mv $SIM_BASE/src.tmp $SIM_BASE/src; echo $SHA > $SIM_BASE/BUILD_SHA"
    sim build --pull
    ;;
  seed)
    ENTRY=${3:?the PhotonEntry host (an SSH alias)}
    echo "== fresh simulators on $SIM (new keys, new history)"
    sim down -v --remove-orphans
    sim up -d
    echo "== waiting for their claim codes"
    for i in $(seq 1 60); do
      CLAIMS=$(sim exec -T sim cat /state/claims.json 2>/dev/null || true)
      [ "$(echo "$CLAIMS" | grep -o '"[a-z-]*": *"[0-9A-Z-]*"' | wc -l)" = 6 ] && break
      [ "$i" = 60 ] && { echo "the simulators have not all said hello after 5 minutes" >&2; sim logs --tail 50 sim >&2; exit 1; }
      sleep 5
    done
    echo "== seeding on $ENTRY; the roster goes straight to the simulators"
    # Written only whole and non-empty: a seed that fails leaves the simulators waiting, not reading half a roster.
    echo "$CLAIMS" | entry seed | sim exec -T sim sh -c "'cat > /state/roster.json.tmp && test -s /state/roster.json.tmp && mv /state/roster.json.tmp /state/roster.json'"
    echo "== waiting for the history (about ten minutes)"
    for i in $(seq 1 120); do
      sim exec -T sim test -f /state/history.done && break
      [ "$i" = 120 ] && { echo "no history after 20 minutes" >&2; sim logs --tail 50 sim >&2; exit 1; }
      sleep 10
    done
    sim exec -T sim cat /state/history.done; echo
    entry status
    ;;
  reset)
    "$0" remove "$SIM" "${3:?the PhotonEntry host}"
    "$0" seed "$SIM" "$3"
    ;;
  remove)
    ENTRY=${3:?the PhotonEntry host (an SSH alias)}
    sim down -v --remove-orphans
    entry remove
    ;;
  status)
    ENTRY=${3:?the PhotonEntry host (an SSH alias)}
    sim ps
    entry status
    ;;
  *) echo "usage: scripts/demo.sh build|seed|reset|remove|status <sim> [<entry>]" >&2; exit 2 ;;
esac

#!/usr/bin/env bash
# Deploys PhotonEntry (photon-suite OPERATIONS.md §2.2). Run on the runner:
#   scripts/deploy.sh <env> [<ref>]        env: prod or staging (the SSH alias of the same name); ref: a commit or tag, default origin/main
#
#   1. refuses a dirty tree, and (prod) a commit that is not on origin/main;
#   2. exports exactly that commit (git archive), never the working tree;
#   3. ships it to /opt/photon/photonentry/releases/<sha>/ and points /opt/photon/photonentry/current at it (.env stays outside releases);
#   4. builds there, runs the one-shot migrate service, starts the stack, waits for every health check;
#   5. checks /readyz on the public name reports this commit, then tags it deploy/<env>/<UTC date>-<n> and pushes the tag;
#   6. keeps the last three releases. Rolling back: scripts/deploy.sh <env> <the previous deploy tag> (plus a restore if a migration changed data).
#
# Nothing here prints a secret. The host needs Docker with Compose, /opt/photon/photonentry/.env (mode 600) and the entry-edge network.
set -euo pipefail
cd "$(dirname "$0")/.."

ENV=${1:?usage: scripts/deploy.sh <prod|staging> [<ref>]}
case "$ENV" in prod|staging) ;; *) echo "env is prod or staging" >&2; exit 2 ;; esac
HOST=$ENV                                      # the SSH alias; no addresses in scripts (§2.2)
BASE=/opt/photon/photonentry
PUBLIC=${PUBLIC_API:-$([ "$ENV" = prod ] && echo https://api.entry.photonind.com || echo https://api.entry.staging.photonind.com)}

[ -z "$(git status --porcelain)" ] || { echo "the working tree is not clean: commit or stash first" >&2; exit 1; }
git fetch -q origin main --tags
REF=${2:-origin/main}
SHA=$(git rev-parse --verify "$REF^{commit}")
if [ "$ENV" = prod ] && ! git merge-base --is-ancestor "$SHA" origin/main; then
  echo "$SHA is not on origin/main: production runs main only" >&2; exit 1
fi
echo "== deploying $SHA to $ENV"

echo "== shipping the commit"
git archive --format=tar.gz "$SHA" | ssh "$HOST" "set -e; d=$BASE/releases/$SHA; rm -rf \$d.tmp; mkdir -p \$d.tmp; tar -xzf - -C \$d.tmp; rm -rf \$d; mv \$d.tmp \$d; ln -sfn ../../.env \$d/.env; test -s $BASE/.env"

echo "== building, migrating, starting (on $HOST)"
ssh "$HOST" "set -e; cd $BASE/releases/$SHA
  export BUILD_SHA=$SHA
  c() { docker compose --env-file $BASE/.env -f docker-compose.yml \"\$@\"; }
  c build --pull
  ln -sfn releases/$SHA $BASE/current.new && mv -Tf $BASE/current.new $BASE/current
  c up -d --remove-orphans
  for s in api worker web; do
    for i in \$(seq 1 60); do
      st=\$(docker inspect -f '{{.State.Health.Status}}' photonentry-\$s-1 2>/dev/null || echo missing)
      [ \"\$st\" = healthy ] && break
      [ \$i = 60 ] && { echo \"photonentry-\$s-1 is \$st after 5 minutes\" >&2; c logs --tail 50 \$s >&2; exit 1; }
      sleep 5
    done
    echo \"   \$s healthy\"
  done
  # Keep the three newest releases (and whatever current points at).
  cur=\$(readlink -f $BASE/current)
  ls -1dt $BASE/releases/*/ | tail -n +4 | while read -r old; do [ \"\$(readlink -f \$old)\" = \"\$cur\" ] || rm -rf \"\$old\"; done"

echo "== smoke: $PUBLIC/readyz"
for i in $(seq 1 24); do
  body=$(curl -fsS --max-time 10 "$PUBLIC/readyz" 2>/dev/null || true)
  echo "$body" | grep -q "\"version\":\"$SHA\"" && echo "$body" | grep -q '"ok":true' && break
  [ "$i" = 24 ] && { echo "the public /readyz does not report $SHA as ready: $body" >&2; exit 1; }
  sleep 5
done
echo "   ready, version $SHA"

n=1; day=$(date -u +%Y%m%d)
while git rev-parse -q --verify "refs/tags/deploy/$ENV/$day-$n" >/dev/null; do n=$((n+1)); done
TAG="deploy/$ENV/$day-$n"
git tag "$TAG" "$SHA"
git push origin "$TAG"
echo "== deployed $SHA to $ENV as $TAG"

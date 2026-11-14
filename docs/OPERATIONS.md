# PhotonEntry: operations

The suite's standard is `photon-suite/OPERATIONS.md` Part 2; this is PhotonEntry's page of it (§2.11's shape). **Not deployed yet**: production
waits for GATE P (BUILD-GUIDE Step 8: the names, `entry` in the directory's catalog with its product credentials, Connor's go-ahead).

## 1. Where it runs

| | |
|---|---|
| Host | The PhotonGuard VPS (BUILD-GUIDE Step 8), behind that host's Caddy; SSH alias `prod` (`staging` for staging) |
| Folder | `/opt/photon/photonentry/`: `releases/<sha>/` (the last three), `current` → the running one, `.env` (mode 600, outside releases) |
| Compose project | `photonentry` (`docker-compose.yml`): `db` (TimescaleDB on Postgres 16, the host's pinned image), `migrate` (one-shot), `api`, `worker`, `web` |
| Names | `entry.photonind.com` (web), `api.entry.photonind.com` (API), `link.entry.photonind.com` (controllers' link, `/link/v1` only), `prov.entry.photonind.com` (intercoms' settings, `/provision/v1` only): `deploy/caddy/entry.caddy` in the host Caddy's sites folder |
| Network | The external `entry-edge` network joins the host's Caddy to `photonentry-api-1` and `photonentry-web-1`. No published ports |
| Controllers | Dial out to `link.` (HTTPS long-poll, held up to a minute: the site file's 90 s read timeout). Intercoms fetch from `prov.` hourly |

## 2. Deploy and roll back

```
scripts/deploy.sh prod                 # origin/main: refuses a dirty tree or a commit not on main; git archive → releases/<sha>; build there;
                                        # migrate (one-shot), start, wait for every health check; /readyz on the public name must report the
                                        # commit; tag deploy/prod/<date>-<n> and push the tag; keep three releases
scripts/deploy.sh prod deploy/prod/20261120-1   # roll back: deploy the previous tag (and restore the database first if a migration changed data)
```

- **First time on a host:** `docker network create entry-edge`; add the host Caddy to `entry-edge` and copy `deploy/caddy/entry.caddy` into its
  sites folder (it uses the host's `secure` snippet); write `/opt/photon/photonentry/.env` from `.env.example` (§3); then the deploy.
- **Migrations** run in `migrate` before the API and worker start, as the database owner (the only service with its password). Expand, then
  contract (OPERATIONS.md §2.3); a migration that drops or rewrites data says `-- DESTRUCTIVE` in its docstring, and the deploy takes a backup first.
- **Checked 2026-11-14 on LXC 800** (not a deploy): both images build, the stack starts with every service healthy (read-only, all
  capabilities dropped), migrations reach head, `/readyz` reports ready with its version, `/config.js` is served from the environment, logs are
  JSON; both Caddyfiles validate. Everything was removed afterwards.

## 3. Configuration (names only; `.env.example` has them all)

`POSTGRES_PASSWORD`, `APP_DB_PASSWORD`, `SYSTEM_DB_PASSWORD` · `OIDC_ISSUER`, `OIDC_AUDIENCE`, `OIDC_WEB_CLIENT_ID`, `CORS_ORIGINS`, `ACCOUNT_ORIGIN`
· `DIRECTORY_URL`, `DIRECTORY_CLIENT_ID`, `DIRECTORY_CLIENT_SECRET`, `DIRECTORY_NOTICE_SECRET` · `SECRETS_KEY` (Fernet, comma separated: the
first encrypts), `FINGERPRINT_KEY` · `WEB_URL`, `PROVISION_URL`, `GUARD_API_URL`, `VOX_API_URL` · `POSTMARK_TOKEN`, `MAIL_FROM` · the web
app's `VITE_OIDC_CLIENT_ID`, `VITE_OIDC_AUDIENCE_PROJECT` (and optional `VITE_*` overrides). The API and worker refuse to start on an unsafe
production configuration (`app/config.py production_safe`).

**A test or staging stack points at the development PhotonID** (`OIDC_ISSUER`, `DIRECTORY_URL`) and at no other product's production address:
the template's values are production's. (On 2026-11-14 a check stack on LXC 800 kept the template's `DIRECTORY_URL` and its worker asked the
production directory a few times with made-up credentials; the directory refused them. Nothing was changed; it is why this line is here.)

## 4. Backups and restore

- Tier **High** (OPERATIONS.md §2.7): who may open which door, every door event and the audit trail. Nightly encrypted dump through the host's
  backup manifest (an entry for `photonentry-db-1`, database `photonentry`), both off-site copies; WAL archiving with the rest of tier High.
- **Restore:** stop `api` and `worker`; restore the dump into a fresh `db`; start; `/readyz`. Controllers keep deciding on their own throughout
  (they hold their settings), and their events wait in `entry-link`'s queue and arrive once the link is back.
- **To add at the first deploy:** the manifest entry, and a restore drill onto LXC 800.

## 5. What is watched

| What | How |
|---|---|
| `https://api.entry.photonind.com/readyz` | 200 with `ok: true` (database, migrations at head, worker heard from within 2 minutes) and the running `version` |
| Containers | `api`, `worker`, `web` health checks; `db` `pg_isready` |
| Certificates | the four names (the host Caddy's) |
| Controllers | in PhotonEntry itself: offline, settings refused, backlog (the Overview page, the PhotonConsole feed, the home dashboard's summary) |
| To add at the first deploy | the host's watch manifest entries; the dead-man's switch; platform health to Photon's own PhotonConsole organization |

## 6. Troubleshooting

| Symptom | Look at | Usually |
|---|---|---|
| `/readyz` 503 "migrations are not at this release's head" | `docker logs photonentry-migrate-1` | a migration failed: fix, redeploy; nothing else changed |
| `/readyz` 503 "the worker has not been heard from" | `docker logs photonentry-worker-1` | the worker is restarting (a configuration error is in its first lines) |
| Controllers "Offline" all at once | `link.` in the host Caddy; `docker logs photonentry-api-1` | the proxy, or the API restarting; controllers keep working and catch up |
| An intercom never "Set up" | the intercom's Autop address; `prov.` reachable from the site | a mistyped address, or the site's firewall |
| Sign-in loops or "We couldn't sign you in" | `OIDC_*`, the PhotonID application's redirect URIs | a wrong audience or client id |
| Directory changes not arriving | worker logs (`photonentry.sync`) | the product credential, or the directory's notice secret |

## 7. Secrets and rotation

- In `.env` (mode 600) on the host, and (O1) encrypted in git with sops + age. Never printed, never logged.
- **`SECRETS_KEY`:** add a new key first in the list (the old one stays to decrypt), deploy; re-seal is a later, separate job.
- **The directory's product credential and notice secret:** issued by id1; rotate in the directory, then `.env`, then restart the worker.
- **Database logins:** the first migration sets them from `.env`; to rotate, `ALTER ROLE … PASSWORD` as the owner, then `.env`, then restart.
- **Expiring:** none of PhotonEntry's own; the directory credential follows the directory's rules.

## 8. Capacity

- Small: an API with long-polls held by every controller (one open request each, ~25 s), a worker, and a database growing mostly by door events
  (a few hundred bytes each). Memory ceilings: api 384 MB, worker 256 MB, web 64 MB, db 512 MB.
- **The first limit** is the number of long-polls per API process (each holds a thread while it waits): at a few hundred controllers, more API
  replicas behind the proxy (the link's state is in Postgres, LISTEN/NOTIFY wakes the right one), then door events as a TimescaleDB hypertable.

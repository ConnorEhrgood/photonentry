"""PhotonGuard and PhotonConsole: the Guard link and its bookkeeping, Console feed tokens; the `feed` mode of row-level security

Revision ID: 0002
Revises: 0001

The feed mode: a PhotonConsole data source signs in with a feed token, not as a person. The API then sets `app.mode = 'feed'` and
`app.tenant_id`, and the feed policies below show that one organization's tenant, sites, doors, controllers and door events, and nothing
else, whatever the feed's code asks for (PhotonEdge's hub does the same).
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

TABLES = r"""
CREATE TABLE guard_link (
  tenant_id uuid PRIMARY KEY, token_sealed text NOT NULL, token_hint varchar(12) NOT NULL DEFAULT '', enabled boolean NOT NULL DEFAULT true,
  created_by uuid, created_at timestamptz NOT NULL DEFAULT now(), last_ok_at timestamptz, last_error text NOT NULL DEFAULT '',
  last_error_at timestamptz, sent bigint NOT NULL DEFAULT 0);
CREATE TABLE guard_cursor (controller_id uuid PRIMARY KEY, tenant_id uuid NOT NULL, seq bigint NOT NULL DEFAULT 0);
CREATE INDEX ix_guard_cursor_tenant_id ON guard_cursor (tenant_id);
CREATE TABLE door_alarm (
  door_id uuid NOT NULL, kind varchar(20) NOT NULL CHECK (kind IN ('alarm', 'tamper')), tenant_id uuid NOT NULL, dedup_key varchar(120) NOT NULL,
  started_at timestamptz NOT NULL, PRIMARY KEY (door_id, kind));
CREATE INDEX ix_door_alarm_tenant_id ON door_alarm (tenant_id);
CREATE TABLE console_feed_token (
  id uuid PRIMARY KEY, tenant_id uuid NOT NULL, console_tenant_id uuid, name varchar(100) NOT NULL, token_hash varchar(64) NOT NULL UNIQUE,
  created_by uuid, created_at timestamptz NOT NULL DEFAULT now(), last_used_at timestamptz, revoked_at timestamptz);
CREATE INDEX ix_console_feed_token_tenant_id ON console_feed_token (tenant_id);
"""

FEED = "CREATE FUNCTION en_feed_tenant() RETURNS uuid LANGUAGE sql STABLE AS $$ " \
       "SELECT CASE WHEN en_mode() = 'feed' THEN nullif(current_setting('app.tenant_id', true), '')::uuid END $$"
ADMIN_TENANTS = "tenant_id IN (SELECT en_tenants_with(ARRAY['admin', 'owner']))"
APP_POLICIES = {
    "guard_link": [("read", "SELECT", ADMIN_TENANTS, None), ("add", "INSERT", None, f"{ADMIN_TENANTS} AND created_by = en_pid()"),
                   ("change", "UPDATE", ADMIN_TENANTS, ADMIN_TENANTS), ("remove", "DELETE", ADMIN_TENANTS, None)],
    "console_feed_token": [("read", "SELECT", ADMIN_TENANTS, None), ("add", "INSERT", None, f"{ADMIN_TENANTS} AND created_by = en_pid()"),
                           ("change", "UPDATE", ADMIN_TENANTS, ADMIN_TENANTS)],
    "guard_cursor": [],
    "door_alarm": [],
}
APP_GRANTS = {"guard_link": "SELECT, INSERT, UPDATE (token_sealed, token_hint, enabled), DELETE",
              "console_feed_token": "SELECT, INSERT, UPDATE (revoked_at)"}
FEED_POLICIES = {"tenant": "id = en_feed_tenant()", "site": "tenant_id = en_feed_tenant()", "door": "tenant_id = en_feed_tenant()",
                 "controller": "tenant_id = en_feed_tenant()", "door_event": "tenant_id = en_feed_tenant()"}


def upgrade() -> None:
    for statement in TABLES.split(";"):
        if statement.strip():
            op.execute(statement)
    op.execute(FEED)
    op.execute("GRANT EXECUTE ON FUNCTION en_feed_tenant() TO entry_app, entry_system")
    for table, grants in APP_GRANTS.items():
        op.execute(f'GRANT {grants} ON "{table}" TO entry_app')
    for table in APP_POLICIES:
        op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON "{table}" TO entry_system')
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'CREATE POLICY "{table}_system" ON "{table}" FOR ALL TO entry_system USING (true) WITH CHECK (true)')
    for table, pols in APP_POLICIES.items():
        for name, cmd, using, check in pols:
            clause = (f"USING ({using}) " if using else "") + (f"WITH CHECK ({check})" if check else "")
            op.execute(f'CREATE POLICY "{table}_{name}" ON "{table}" FOR {cmd} TO entry_app {clause}')
    for table, using in FEED_POLICIES.items():
        op.execute(f'CREATE POLICY "{table}_feed" ON "{table}" FOR SELECT TO entry_app USING ({using})')


def downgrade() -> None:
    for table in FEED_POLICIES:
        op.execute(f'DROP POLICY IF EXISTS "{table}_feed" ON "{table}"')
    for table in reversed(list(APP_POLICIES)):
        op.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE')
    op.execute("DROP FUNCTION IF EXISTS en_feed_tenant()")

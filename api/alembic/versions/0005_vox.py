"""PhotonVox (Step 5, part 2; docs/VOX.md): the connection, an intercom's door station, and who answered a door's call

Revision ID: 0005
Revises: 0004

`vox_link` is like `guard_link`: admins of the organization read and write it. `call_match` is written by the worker (the system) and read by
whoever reads the door's events. The intercom's door station is an admin's to set, like the rest of the intercom.
"""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

TABLES = r"""
ALTER TABLE intercom ADD COLUMN vox_station_id varchar(64) NOT NULL DEFAULT '';
ALTER TABLE intercom ADD COLUMN sip_synced_at timestamptz;
CREATE TABLE vox_link (
  tenant_id uuid PRIMARY KEY, token_sealed text NOT NULL, token_hint varchar(12) NOT NULL DEFAULT '', created_by uuid,
  created_at timestamptz NOT NULL DEFAULT now(), last_ok_at timestamptz, last_error text NOT NULL DEFAULT '', last_error_at timestamptz);
CREATE TABLE call_match (
  controller_id uuid NOT NULL, seq bigint NOT NULL, tenant_id uuid NOT NULL, state varchar(10) NOT NULL CHECK (state IN ('found', 'none')),
  call_id varchar(128) NOT NULL DEFAULT '', extension varchar(32) NOT NULL DEFAULT '', name varchar(128) NOT NULL DEFAULT '', person_id uuid,
  matched_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY (controller_id, seq));
CREATE INDEX ix_call_match_tenant_id ON call_match (tenant_id)
"""
ADMIN_TENANTS = "tenant_id IN (SELECT en_tenants_with(ARRAY['admin', 'owner']))"
EVENT_READERS = "tenant_id IN (SELECT en_tenants_with(ARRAY['viewer', 'operator', 'admin', 'owner']))"
POLICIES = {
    "vox_link": [("read", "SELECT", ADMIN_TENANTS, None), ("add", "INSERT", None, f"{ADMIN_TENANTS} AND created_by = en_pid()"),
                 ("change", "UPDATE", ADMIN_TENANTS, ADMIN_TENANTS), ("remove", "DELETE", ADMIN_TENANTS, None)],
    "call_match": [("read", "SELECT", EVENT_READERS, None)],
}
APP_GRANTS = {"vox_link": "SELECT, INSERT, UPDATE (token_sealed, token_hint), DELETE", "call_match": "SELECT"}


def upgrade() -> None:
    for statement in TABLES.split(";"):
        if statement.strip():
            op.execute(statement)
    op.execute("GRANT UPDATE (vox_station_id, sip_synced_at) ON intercom TO entry_app")
    for table, grants in APP_GRANTS.items():
        op.execute(f'GRANT {grants} ON "{table}" TO entry_app')
        op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON "{table}" TO entry_system')
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'CREATE POLICY "{table}_system" ON "{table}" FOR ALL TO entry_system USING (true) WITH CHECK (true)')
        for name, cmd, using, check in POLICIES[table]:
            clause = (f"USING ({using}) " if using else "") + (f"WITH CHECK ({check})" if check else "")
            op.execute(f'CREATE POLICY "{table}_{name}" ON "{table}" FOR {cmd} TO entry_app {clause}')


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS call_match CASCADE")
    op.execute("DROP TABLE IF EXISTS vox_link CASCADE")
    op.execute("ALTER TABLE intercom DROP COLUMN IF EXISTS sip_synced_at")
    op.execute("ALTER TABLE intercom DROP COLUMN IF EXISTS vox_station_id")

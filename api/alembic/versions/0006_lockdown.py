"""Lockdown as a record (Step 6; ARCHITECTURE §9.6): scope, reason, who started and ended it

Revision ID: 0006
Revises: 0005

Everyone at the site reads it (the banner is a safety notice); operators and up start and end it, in their own name. One active per site.
"""
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

TABLE = r"""
CREATE TABLE lockdown (
  id uuid PRIMARY KEY, tenant_id uuid NOT NULL, site_id uuid NOT NULL, door_ids jsonb NOT NULL DEFAULT '[]'::jsonb, whole_site boolean NOT NULL DEFAULT true,
  reason varchar(200) NOT NULL CHECK (length(btrim(reason)) > 0), source varchar(10) NOT NULL DEFAULT 'app' CHECK (source IN ('app', 'input')),
  started_by uuid, started_by_label varchar(200) NOT NULL DEFAULT '', started_by_source varchar(10) NOT NULL DEFAULT 'direct',
  started_at timestamptz NOT NULL DEFAULT now(), start_commands jsonb NOT NULL DEFAULT '[]'::jsonb,
  ended_at timestamptz, ended_by uuid, ended_by_label varchar(200) NOT NULL DEFAULT '', ended_by_source varchar(10) NOT NULL DEFAULT '',
  end_reason varchar(200) NOT NULL DEFAULT '', end_commands jsonb NOT NULL DEFAULT '[]'::jsonb,
  CHECK (ended_at IS NULL OR length(btrim(end_reason)) > 0))
"""
MY_SITES = "site_id IN (SELECT en_sites_with(ARRAY['viewer', 'operator', 'admin', 'owner']))"
OPERATOR_SITES = "site_id IN (SELECT en_sites_with(ARRAY['operator', 'admin', 'owner']))"
POLICIES = [("read", "SELECT", MY_SITES, None), ("add", "INSERT", None, f"{OPERATOR_SITES} AND started_by = en_pid()"),
            ("change", "UPDATE", OPERATOR_SITES, f"{OPERATOR_SITES} AND ended_by = en_pid()")]


def upgrade() -> None:
    op.execute(TABLE)
    op.execute("CREATE INDEX ix_lockdown_tenant_id ON lockdown (tenant_id)")
    op.execute("CREATE INDEX ix_lockdown_site_id ON lockdown (site_id)")
    op.execute("CREATE UNIQUE INDEX uq_lockdown_active ON lockdown (site_id) WHERE ended_at IS NULL")
    op.execute("GRANT SELECT, INSERT, UPDATE (ended_at, ended_by, ended_by_label, ended_by_source, end_reason, end_commands) ON lockdown TO entry_app")
    op.execute("GRANT SELECT, INSERT, UPDATE ON lockdown TO entry_system")
    op.execute("ALTER TABLE lockdown ENABLE ROW LEVEL SECURITY")
    op.execute('CREATE POLICY "lockdown_system" ON lockdown FOR ALL TO entry_system USING (true) WITH CHECK (true)')
    for name, cmd, using, check in POLICIES:
        clause = (f"USING ({using}) " if using else "") + (f"WITH CHECK ({check})" if check else "")
        op.execute(f'CREATE POLICY "lockdown_{name}" ON lockdown FOR {cmd} TO entry_app {clause}')


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS lockdown CASCADE")

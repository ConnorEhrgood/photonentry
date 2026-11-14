"""Visitors' passes (Step 6): the last published site document, passes, and access groups opened to visitors

Revision ID: 0008
Revises: 0007

Operators issue passes (`entry.visitors.manage`) in their own name at their sites. The pass's cardholder, credentials and the settings that
carry them are written by the system, after the API has checked the person (app/passes.py): operators cannot write cardholders,
credentials or settings themselves.
"""
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

TABLES = r"""
ALTER TABLE access_group ADD COLUMN for_visitors boolean NOT NULL DEFAULT false;
CREATE TABLE site_publication (
  site_id uuid PRIMARY KEY, tenant_id uuid NOT NULL, document jsonb NOT NULL, published_at timestamptz NOT NULL DEFAULT now(), published_by uuid);
CREATE INDEX ix_site_publication_tenant_id ON site_publication (tenant_id);
CREATE TABLE visitor_pass (
  id uuid PRIMARY KEY, tenant_id uuid NOT NULL, site_id uuid NOT NULL, cardholder_id uuid NOT NULL UNIQUE, group_id uuid NOT NULL,
  visitor_name varchar(128) NOT NULL, visitor_email varchar(320) NOT NULL DEFAULT '', host_person_id uuid NOT NULL, host_label varchar(200) NOT NULL,
  valid_from timestamptz NOT NULL, valid_to timestamptz NOT NULL, token_hash varchar(64) NOT NULL UNIQUE, token_sealed text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(), emailed_at timestamptz, revoked_at timestamptz, revoked_by_label varchar(200) NOT NULL DEFAULT '',
  CHECK (valid_to > valid_from));
CREATE INDEX ix_visitor_pass_tenant_id ON visitor_pass (tenant_id);
CREATE INDEX ix_visitor_pass_site_id ON visitor_pass (site_id, valid_to)
"""
ADMIN_SITES = "site_id IN (SELECT en_sites_with(ARRAY['admin', 'owner']))"
OPERATOR_SITES = "site_id IN (SELECT en_sites_with(ARRAY['operator', 'admin', 'owner']))"
POLICIES = {
    "site_publication": [("read", "SELECT", ADMIN_SITES, None), ("add", "INSERT", None, f"{ADMIN_SITES} AND published_by = en_pid()"),
                         ("change", "UPDATE", ADMIN_SITES, f"{ADMIN_SITES} AND published_by = en_pid()")],
    "visitor_pass": [("read", "SELECT", OPERATOR_SITES, None)],
}
GRANTS = {"site_publication": "SELECT, INSERT, UPDATE", "visitor_pass": "SELECT"}


def upgrade() -> None:
    for statement in TABLES.split(";"):
        if statement.strip():
            op.execute(statement)
    op.execute("GRANT UPDATE (for_visitors) ON access_group TO entry_app")
    for table, pols in POLICIES.items():
        op.execute(f'GRANT {GRANTS[table]} ON "{table}" TO entry_app')
        op.execute(f'GRANT SELECT, INSERT, UPDATE ON "{table}" TO entry_system')
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'CREATE POLICY "{table}_system" ON "{table}" FOR ALL TO entry_system USING (true) WITH CHECK (true)')
        for name, cmd, using, check in pols:
            clause = (f"USING ({using}) " if using else "") + (f"WITH CHECK ({check})" if check else "")
            op.execute(f'CREATE POLICY "{table}_{name}" ON "{table}" FOR {cmd} TO entry_app {clause}')


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS visitor_pass CASCADE")
    op.execute("DROP TABLE IF EXISTS site_publication CASCADE")
    op.execute("ALTER TABLE access_group DROP COLUMN IF EXISTS for_visitors")

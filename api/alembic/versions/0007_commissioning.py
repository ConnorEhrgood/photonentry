"""Commissioning (Step 6; ARCHITECTURE §7.2, §7.7): installers' licenses and each door's signed commissioning record

Revision ID: 0007
Revises: 0006

- **license:** a partner's (its staff manage it; every customer it serves reads it) or an organization's own (its admins manage it). Removed
  licenses are kept, marked, because records name them.
- **commissioning:** append-only, signed in the admin's own name at their sites; read by everyone at the site. Only the void fields change.
"""
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

TABLES = r"""
CREATE TABLE license (
  id uuid PRIMARY KEY, partner_id uuid, tenant_id uuid, state varchar(2) NOT NULL CHECK (state IN ('PA', 'OH', 'WV')),
  kind varchar(40) NOT NULL, holder varchar(128) NOT NULL, number varchar(64) NOT NULL, expires_on date, created_by uuid,
  created_at timestamptz NOT NULL DEFAULT now(), removed_at timestamptz, CHECK ((partner_id IS NULL) <> (tenant_id IS NULL)));
CREATE INDEX ix_license_partner_id ON license (partner_id);
CREATE INDEX ix_license_tenant_id ON license (tenant_id);
CREATE TABLE commissioning (
  id uuid PRIMARY KEY, tenant_id uuid NOT NULL, site_id uuid NOT NULL, door_id uuid NOT NULL, controller_door varchar(64) NOT NULL,
  jurisdiction varchar(2) NOT NULL CHECK (jurisdiction IN ('PA', 'OH', 'WV', 'ZZ')), lock_type varchar(40) NOT NULL,
  failure_state varchar(12) NOT NULL CHECK (failure_state IN ('fail_secure', 'fail_safe')), egress varchar(200) NOT NULL,
  special_locking varchar(20) NOT NULL CHECK (special_locking IN ('none', 'delayed_egress', 'controlled_egress', 'sensor_release')),
  fire_release varchar(12) NOT NULL CHECK (fire_release IN ('tested', 'none_present')), fire_tested_on date, fire_tested_by varchar(128) NOT NULL DEFAULT '',
  rex_checked boolean NOT NULL, contact_checked boolean NOT NULL, reader_ul_verified boolean NOT NULL DEFAULT false, ahj_reference varchar(128) NOT NULL,
  installer varchar(128) NOT NULL, license_id uuid, license_text varchar(200) NOT NULL DEFAULT '', notes text NOT NULL DEFAULT '',
  signed_by uuid NOT NULL, signed_by_label varchar(200) NOT NULL, signed_by_source varchar(10) NOT NULL DEFAULT 'direct',
  signed_at timestamptz NOT NULL DEFAULT now(), voided_at timestamptz, voided_by_label varchar(200) NOT NULL DEFAULT '',
  void_reason varchar(200) NOT NULL DEFAULT '',
  CHECK (fire_release <> 'tested' OR (fire_tested_on IS NOT NULL AND length(btrim(fire_tested_by)) > 0)),
  CHECK (special_locking = 'none' OR reader_ul_verified),
  CHECK (voided_at IS NULL OR length(btrim(void_reason)) > 0));
CREATE INDEX ix_commissioning_tenant_id ON commissioning (tenant_id);
CREATE INDEX ix_commissioning_site_id ON commissioning (site_id);
CREATE INDEX ix_commissioning_door_id ON commissioning (door_id, signed_at)
"""
# The partners whose staff this person is (an admin or owner grant from the partner, still current): they manage the partner's licenses.
PARTNER_ADMIN = (
    "CREATE FUNCTION en_partners_staffed() RETURNS SETOF uuid LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$ "
    "SELECT DISTINCT t.partner_id FROM access a JOIN tenant t ON t.id = a.tenant_id WHERE a.person_id = en_pid() AND a.source = 'partner' "
    "AND a.role IN ('admin', 'owner') AND (a.expires_at IS NULL OR a.expires_at > now()) AND t.partner_id IS NOT NULL $$")
ANY = "ARRAY['viewer', 'operator', 'admin', 'owner']"
ADMIN = "ARRAY['admin', 'owner']"
READ_LICENSE = (f"tenant_id IN (SELECT en_tenants_with({ANY})) OR partner_id IN (SELECT partner_id FROM tenant WHERE id IN "
                f"(SELECT en_tenants_with({ANY})))")
WRITE_LICENSE = f"tenant_id IN (SELECT en_tenants_with({ADMIN})) OR partner_id IN (SELECT en_partners_staffed())"
POLICIES = {
    "license": [("read", "SELECT", READ_LICENSE, None), ("add", "INSERT", None, f"({WRITE_LICENSE}) AND created_by = en_pid()"),
                ("change", "UPDATE", WRITE_LICENSE, WRITE_LICENSE)],
    "commissioning": [("read", "SELECT", f"site_id IN (SELECT en_sites_with({ANY}))", None),
                      ("add", "INSERT", None, f"site_id IN (SELECT en_sites_with({ADMIN})) AND signed_by = en_pid()"),
                      ("change", "UPDATE", f"site_id IN (SELECT en_sites_with({ADMIN}))", f"site_id IN (SELECT en_sites_with({ADMIN}))")],
}
GRANTS = {"license": "SELECT, INSERT, UPDATE (holder, number, expires_on, removed_at)",
          "commissioning": "SELECT, INSERT, UPDATE (voided_at, voided_by_label, void_reason)"}


def upgrade() -> None:
    for statement in TABLES.split(";"):
        if statement.strip():
            op.execute(statement)
    op.execute(PARTNER_ADMIN)
    op.execute("REVOKE ALL ON FUNCTION en_partners_staffed() FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION en_partners_staffed() TO entry_app, entry_system")
    for table, pols in POLICIES.items():
        op.execute(f'GRANT {GRANTS[table]} ON "{table}" TO entry_app')
        op.execute(f'GRANT SELECT, INSERT, UPDATE ON "{table}" TO entry_system')
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'CREATE POLICY "{table}_system" ON "{table}" FOR ALL TO entry_system USING (true) WITH CHECK (true)')
        for name, cmd, using, check in pols:
            clause = (f"USING ({using}) " if using else "") + (f"WITH CHECK ({check})" if check else "")
            op.execute(f'CREATE POLICY "{table}_{name}" ON "{table}" FOR {cmd} TO entry_app {clause}')


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS commissioning CASCADE")
    op.execute("DROP TABLE IF EXISTS license CASCADE")
    op.execute("DROP FUNCTION IF EXISTS en_partners_staffed()")

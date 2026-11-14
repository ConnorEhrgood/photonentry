"""Intercoms (Step 5): Akuvox intercoms at doors, provisioned from PhotonEntry, opening doors through entry-link

Revision ID: 0003
Revises: 0002

Admins at the intercom's site read and write it (it holds sealed secrets, like credentials); nobody else sees it. The provisioning server
looks an intercom up by the hash of the token in its address and records the fetch, as the system.
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

TABLE = r"""
CREATE TABLE intercom (
  id uuid PRIMARY KEY, tenant_id uuid NOT NULL, site_id uuid NOT NULL, door_id uuid NOT NULL, name varchar(64) NOT NULL, model varchar(32) NOT NULL,
  mac varchar(12) NOT NULL UNIQUE CONSTRAINT ck_intercom_mac CHECK (mac ~ '^[0-9A-F]{12}$'), relay_address varchar(80) NOT NULL DEFAULT '',
  sip_server varchar(255) NOT NULL DEFAULT '', sip_port integer NOT NULL DEFAULT 5061,
  sip_transport varchar(3) NOT NULL DEFAULT 'tls' CONSTRAINT ck_intercom_transport CHECK (sip_transport IN ('udp', 'tcp', 'tls')),
  sip_user varchar(64) NOT NULL DEFAULT '', sip_password_sealed text NOT NULL DEFAULT '', relay_secret_sealed text NOT NULL,
  admin_password_sealed text NOT NULL, provision_token_sealed text NOT NULL,
  provision_token_hash varchar(64) NOT NULL UNIQUE, created_by uuid, created_at timestamptz NOT NULL DEFAULT now(), last_fetch_at timestamptz,
  last_fetch_ip varchar(64) NOT NULL DEFAULT '')
"""
ADMIN_SITES = "site_id IN (SELECT en_sites_with(ARRAY['admin', 'owner']))"
POLICIES = [("read", "SELECT", ADMIN_SITES, None), ("add", "INSERT", None, f"{ADMIN_SITES} AND created_by = en_pid()"),
            ("change", "UPDATE", ADMIN_SITES, ADMIN_SITES), ("remove", "DELETE", ADMIN_SITES, None)]
APP_UPDATE = ("name, door_id, model, mac, relay_address, sip_server, sip_port, sip_transport, sip_user, sip_password_sealed, relay_secret_sealed, "
              "admin_password_sealed, provision_token_sealed, provision_token_hash")


def upgrade() -> None:
    op.execute(TABLE)
    op.execute("CREATE INDEX ix_intercom_tenant_id ON intercom (tenant_id)")
    op.execute("CREATE INDEX ix_intercom_site_id ON intercom (site_id)")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ({APP_UPDATE}), DELETE ON intercom TO entry_app")
    op.execute("GRANT SELECT, UPDATE ON intercom TO entry_system")
    op.execute("ALTER TABLE intercom ENABLE ROW LEVEL SECURITY")
    op.execute('CREATE POLICY "intercom_system" ON intercom FOR ALL TO entry_system USING (true) WITH CHECK (true)')
    for name, cmd, using, check in POLICIES:
        clause = (f"USING ({using}) " if using else "") + (f"WITH CHECK ({check})" if check else "")
        op.execute(f'CREATE POLICY "intercom_{name}" ON intercom FOR {cmd} TO entry_app {clause}')


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS intercom CASCADE")

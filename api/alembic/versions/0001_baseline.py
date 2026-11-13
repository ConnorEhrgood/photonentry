"""directory copy, audit log, controllers and the link, the access configuration; the three database roles; row-level security

Revision ID: 0001
Revises:

Roles: the OWNER running this migration owns the tables and is never used by the app. `entry_app` is the routes' login: every policy below applies
to it. `entry_system` is the link service's, the worker's and the directory sync's: it has its own all-access policies and cannot change the
schema. A session with no `app.mode` sees nothing through `entry_app`.

Who may write what, in the database (the routes check the same capabilities first; app/roles.py):
- configuration (doors, schedules, holiday calendars, access groups, group memberships) and publishing: admins and owners, at their sites;
- cardholders and credentials: admins and owners of the organization (credentials are not even readable by others);
- commands (remote unlock, lockdown): operators and up, at their sites, in their own name;
- controllers: renamed or disabled by admins at their sites; claimed only through the system role, after the route's checks (a pending
  controller belongs to no organization yet);
- door events and the link's bookkeeping: the system role only;
- the audit log: INSERT and SELECT, never UPDATE or DELETE, for anyone (decision 18).

Tables are written out here, not created from app/models.py, so this migration means the same thing forever.
"""
import os
import re

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TABLES = r"""
CREATE TABLE tenant (
  id uuid PRIMARY KEY, name varchar(200) NOT NULL, partner_id uuid, plan_key varchar(60) NOT NULL DEFAULT '',
  status varchar(20) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended', 'removed')),
  home_region varchar(40) NOT NULL DEFAULT 'us-east', products jsonb NOT NULL DEFAULT '[]',
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE site (
  id uuid PRIMARY KEY, tenant_id uuid NOT NULL, slug varchar(80) NOT NULL UNIQUE, name varchar(200) NOT NULL, address text NOT NULL DEFAULT '',
  timezone varchar(64) NOT NULL DEFAULT 'UTC', latitude double precision, longitude double precision,
  status varchar(20) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'removed')));
CREATE INDEX ix_site_tenant_id ON site (tenant_id);
CREATE TABLE person (
  id uuid PRIMARY KEY, sub varchar(200) UNIQUE, name varchar(200) NOT NULL DEFAULT '', email varchar(320) NOT NULL DEFAULT '',
  active boolean NOT NULL DEFAULT true, is_platform_admin boolean NOT NULL DEFAULT false, partners jsonb NOT NULL DEFAULT '[]');
CREATE TABLE access (
  person_id uuid NOT NULL, tenant_id uuid NOT NULL,
  role varchar(20) NOT NULL CHECK (role IN ('owner', 'admin', 'operator', 'viewer')),
  scope_all boolean NOT NULL DEFAULT true, site_ids uuid[] NOT NULL DEFAULT '{}',
  source varchar(10) NOT NULL DEFAULT 'direct' CHECK (source IN ('direct', 'partner')), expires_at timestamptz, others jsonb NOT NULL DEFAULT '[]',
  PRIMARY KEY (person_id, tenant_id), CHECK (scope_all OR cardinality(site_ids) > 0));
CREATE INDEX ix_access_tenant_id ON access (tenant_id);
CREATE TABLE sync_state (
  id smallint PRIMARY KEY DEFAULT 1 CHECK (id = 1), cursor bigint NOT NULL DEFAULT 0, last_pull_at timestamptz, last_ok_at timestamptz,
  last_error text, roles_published_hash varchar(64) NOT NULL DEFAULT '');
CREATE TABLE audit_log (
  id bigserial PRIMARY KEY, at timestamptz NOT NULL DEFAULT now(), tenant_id uuid, site_id uuid, actor_person_id uuid,
  actor_label varchar(320) NOT NULL DEFAULT '', actor_source varchar(10) NOT NULL DEFAULT 'direct', action varchar(60) NOT NULL,
  target_type varchar(40) NOT NULL DEFAULT '', target_id varchar(80) NOT NULL DEFAULT '', detail jsonb NOT NULL DEFAULT '{}');
CREATE INDEX ix_audit_tenant_at ON audit_log (tenant_id, at);

CREATE TABLE controller (
  id uuid PRIMARY KEY, key_id varchar(16) NOT NULL UNIQUE, public_key bytea NOT NULL, claim_code varchar(9) NOT NULL DEFAULT '',
  state varchar(10) NOT NULL DEFAULT 'pending' CHECK (state IN ('pending', 'claimed', 'disabled')),
  tenant_id uuid, site_id uuid, name varchar(64) NOT NULL DEFAULT '', device jsonb NOT NULL DEFAULT '{}', inventory jsonb,
  applied_version integer NOT NULL DEFAULT 0, failed_version integer NOT NULL DEFAULT 0, apply_error text NOT NULL DEFAULT '',
  ack_seq bigint NOT NULL DEFAULT 0, last_seen timestamptz, health jsonb NOT NULL DEFAULT '{}', claimed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (state = 'pending' OR (tenant_id IS NOT NULL AND site_id IS NOT NULL)));
CREATE INDEX ix_controller_tenant_id ON controller (tenant_id);
CREATE INDEX ix_controller_site_id ON controller (site_id);
CREATE TABLE settings_version (
  controller_id uuid NOT NULL, version integer NOT NULL, tenant_id uuid NOT NULL, site_id uuid NOT NULL, document jsonb NOT NULL,
  created_by uuid, created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY (controller_id, version));
CREATE INDEX ix_settings_version_tenant_id ON settings_version (tenant_id);
CREATE TABLE link_command (
  id varchar(40) PRIMARY KEY, tenant_id uuid NOT NULL, site_id uuid NOT NULL, controller_id uuid NOT NULL,
  kind varchar(20) NOT NULL CHECK (kind IN ('access', 'lock', 'unlock', 'lockdown', 'lockdown_release')), door varchar(64) NOT NULL,
  actor varchar(200) NOT NULL DEFAULT '', actor_person_id uuid, expires_at timestamptz NOT NULL, delivered_at timestamptz,
  done boolean NOT NULL DEFAULT false, ok boolean, error text NOT NULL DEFAULT '', created_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX ix_link_command_tenant_id ON link_command (tenant_id);
CREATE INDEX ix_link_command_controller_id ON link_command (controller_id) WHERE NOT done;
CREATE TABLE door_event (
  controller_id uuid NOT NULL, seq bigint NOT NULL, tenant_id uuid NOT NULL, site_id uuid NOT NULL, occurred_at timestamptz NOT NULL,
  received_at timestamptz NOT NULL DEFAULT now(), topic varchar(200) NOT NULL, source jsonb NOT NULL DEFAULT '{}', data jsonb NOT NULL DEFAULT '{}',
  ref varchar(64) NOT NULL DEFAULT '', PRIMARY KEY (controller_id, seq));
CREATE INDEX ix_door_event_site_time ON door_event (site_id, occurred_at);

CREATE TABLE door (
  id uuid PRIMARY KEY, tenant_id uuid NOT NULL, site_id uuid NOT NULL, controller_id uuid NOT NULL, controller_door varchar(64) NOT NULL,
  name varchar(64) NOT NULL, access_time_s integer NOT NULL DEFAULT 7, open_too_long_s integer NOT NULL DEFAULT 30,
  pre_alarm_s integer NOT NULL DEFAULT 5, unlock_schedule_id uuid, created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_door_controller_door UNIQUE (controller_id, controller_door));
CREATE INDEX ix_door_tenant_id ON door (tenant_id);
CREATE INDEX ix_door_site_id ON door (site_id);
CREATE TABLE schedule (
  id uuid PRIMARY KEY, tenant_id uuid NOT NULL, site_id uuid NOT NULL, name varchar(64) NOT NULL, windows jsonb NOT NULL,
  on_holidays varchar(10) NOT NULL DEFAULT 'off' CHECK (on_holidays IN ('off', 'normal')));
CREATE INDEX ix_schedule_tenant_id ON schedule (tenant_id);
CREATE INDEX ix_schedule_site_id ON schedule (site_id);
CREATE TABLE holiday_calendar (site_id uuid PRIMARY KEY, tenant_id uuid NOT NULL, days jsonb NOT NULL DEFAULT '[]');
CREATE INDEX ix_holiday_calendar_tenant_id ON holiday_calendar (tenant_id);
CREATE TABLE access_group (id uuid PRIMARY KEY, tenant_id uuid NOT NULL, site_id uuid NOT NULL, name varchar(64) NOT NULL, rules jsonb NOT NULL);
CREATE INDEX ix_access_group_tenant_id ON access_group (tenant_id);
CREATE INDEX ix_access_group_site_id ON access_group (site_id);
CREATE TABLE cardholder (
  id uuid PRIMARY KEY, tenant_id uuid NOT NULL, name varchar(128) NOT NULL, ref varchar(80), email varchar(320) NOT NULL DEFAULT '',
  person_id uuid, suspended boolean NOT NULL DEFAULT false, valid_from timestamptz, valid_to timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(), CONSTRAINT uq_cardholder_ref UNIQUE (tenant_id, ref));
CREATE INDEX ix_cardholder_tenant_id ON cardholder (tenant_id);
CREATE TABLE cardholder_group (
  cardholder_id uuid NOT NULL, group_id uuid NOT NULL, tenant_id uuid NOT NULL, site_id uuid NOT NULL, PRIMARY KEY (cardholder_id, group_id));
CREATE INDEX ix_cardholder_group_tenant_id ON cardholder_group (tenant_id);
CREATE INDEX ix_cardholder_group_site_id ON cardholder_group (site_id);
CREATE TABLE credential (
  id uuid PRIMARY KEY, tenant_id uuid NOT NULL, cardholder_id uuid NOT NULL, kind varchar(10) NOT NULL CHECK (kind IN ('card', 'pin')),
  card_format varchar(10), card_facility integer, value_sealed text NOT NULL, fingerprint varchar(64) NOT NULL, hint varchar(20) NOT NULL DEFAULT '',
  enabled boolean NOT NULL DEFAULT true, valid_from timestamptz, valid_to timestamptz, created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_credential_fingerprint UNIQUE (tenant_id, fingerprint));
CREATE INDEX ix_credential_tenant_id ON credential (tenant_id);
CREATE INDEX ix_credential_cardholder_id ON credential (cardholder_id);
"""

FUNCTIONS = [
    "CREATE FUNCTION en_mode() RETURNS text LANGUAGE sql STABLE AS $$ SELECT coalesce(current_setting('app.mode', true), '') $$",
    "CREATE FUNCTION en_pid() RETURNS uuid LANGUAGE sql STABLE AS $$ "
    "SELECT CASE WHEN en_mode() = 'user' THEN nullif(current_setting('app.person_id', true), '')::uuid END $$",
    "CREATE FUNCTION en_privileged() RETURNS boolean LANGUAGE sql STABLE AS $$ "
    "SELECT en_mode() = 'user' AND coalesce(current_setting('app.admin', true), '') = 'on' $$",
    # The helpers read the access table on the policies' behalf, so they run as the owner (SECURITY DEFINER) and do not recurse into its policy.
    # An expired grant counts for nothing. Organization-wide questions use the grant's own (strongest) role; site questions the strongest entry,
    # the grant's or one of its `others`, that covers the site (suite §5).
    "CREATE FUNCTION en_tenants_with(roles text[]) RETURNS SETOF uuid LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$ "
    "SELECT tenant_id FROM access WHERE person_id = en_pid() AND role = ANY (roles) AND (expires_at IS NULL OR expires_at > now()) $$",
    "CREATE FUNCTION en_sites_with(roles text[]) RETURNS SETOF uuid LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$ "
    "SELECT s.id FROM site s JOIN access a ON a.tenant_id = s.tenant_id WHERE a.person_id = en_pid() "
    "AND (a.expires_at IS NULL OR a.expires_at > now()) AND s.status = 'active' AND ("
    "(a.role = ANY (roles) AND (a.scope_all OR s.id = ANY (a.site_ids))) OR EXISTS ("
    "SELECT 1 FROM jsonb_array_elements(a.others) o WHERE o->>'role' = ANY (roles) "
    "AND (o->'scope'->>'type' = 'all' OR (o->'scope'->'site_ids') ? s.id::text))) $$",
]
FUNCTION_NAMES = ["en_sites_with(text[])", "en_tenants_with(text[])", "en_privileged()", "en_pid()", "en_mode()"]

ANY = "ARRAY['viewer', 'operator', 'admin', 'owner']"
OPERATOR = "ARRAY['operator', 'admin', 'owner']"
ADMIN = "ARRAY['admin', 'owner']"
MY_TENANTS = f"tenant_id IN (SELECT en_tenants_with({ANY}))"
MY_SITES = f"site_id IN (SELECT en_sites_with({ANY}))"
OPERATOR_SITES = f"site_id IN (SELECT en_sites_with({OPERATOR}))"
ADMIN_SITES = f"site_id IN (SELECT en_sites_with({ADMIN}))"
OPERATOR_TENANTS = f"tenant_id IN (SELECT en_tenants_with({OPERATOR}))"
ADMIN_TENANTS = f"tenant_id IN (SELECT en_tenants_with({ADMIN}))"


def _config(table):
    """Site configuration: read at your sites; written by admins at theirs."""
    return [("read", "SELECT", MY_SITES, None), ("add", "INSERT", None, ADMIN_SITES), ("change", "UPDATE", ADMIN_SITES, ADMIN_SITES),
            ("remove", "DELETE", ADMIN_SITES, None)]


# table -> [(policy, command, USING, WITH CHECK)], all for entry_app. Permissive policies for one command are OR'd together.
APP_POLICIES = {
    "tenant": [("read", "SELECT", f"en_privileged() OR id IN (SELECT en_tenants_with({ANY}))", None)],
    "site": [("read", "SELECT", f"id IN (SELECT en_sites_with({ANY}))", None)],
    "person": [("read", "SELECT", f"id = en_pid() OR id IN (SELECT person_id FROM access WHERE {ADMIN_TENANTS})", None)],
    "access": [("read", "SELECT", f"person_id = en_pid() OR {ADMIN_TENANTS}", None)],
    "sync_state": [],
    "audit_log": [
        ("write", "INSERT", None, f"en_mode() = 'user' AND actor_person_id = en_pid() AND (tenant_id IS NULL OR {MY_TENANTS})"),
        ("read", "SELECT", f"tenant_id IN (SELECT en_tenants_with(ARRAY['owner'])) OR (tenant_id IS NULL AND en_privileged())", None),
    ],
    "controller": [("read", "SELECT", MY_SITES, None), ("change", "UPDATE", ADMIN_SITES, f"{ADMIN_SITES} AND state <> 'pending'")],
    "settings_version": [("read", "SELECT", MY_SITES, None), ("add", "INSERT", None, f"{ADMIN_SITES} AND created_by = en_pid()")],
    "link_command": [("read", "SELECT", MY_SITES, None), ("add", "INSERT", None, f"{OPERATOR_SITES} AND actor_person_id = en_pid()")],
    "door_event": [("read", "SELECT", MY_SITES, None)],
    "door": _config("door"),
    "schedule": _config("schedule"),
    "holiday_calendar": _config("holiday_calendar"),
    "access_group": _config("access_group"),
    "cardholder_group": [("read", "SELECT", OPERATOR_TENANTS, None), ("add", "INSERT", None, f"{ADMIN_SITES} AND {ADMIN_TENANTS}"),
                         ("remove", "DELETE", ADMIN_SITES, None)],
    "cardholder": [("read", "SELECT", OPERATOR_TENANTS, None), ("add", "INSERT", None, ADMIN_TENANTS),
                   ("change", "UPDATE", ADMIN_TENANTS, ADMIN_TENANTS), ("remove", "DELETE", ADMIN_TENANTS, None)],
    "credential": [("read", "SELECT", ADMIN_TENANTS, None), ("add", "INSERT", None, ADMIN_TENANTS),
                   ("change", "UPDATE", ADMIN_TENANTS, ADMIN_TENANTS), ("remove", "DELETE", ADMIN_TENANTS, None)],
}
CONFIG = "SELECT, INSERT, UPDATE, DELETE"
APP_GRANTS = {
    "tenant": "SELECT", "site": "SELECT", "person": "SELECT", "access": "SELECT", "audit_log": "SELECT, INSERT",
    "controller": "SELECT, UPDATE (name, state)", "settings_version": "SELECT, INSERT", "link_command": "SELECT, INSERT", "door_event": "SELECT",
    "door": CONFIG, "schedule": CONFIG, "holiday_calendar": CONFIG, "access_group": CONFIG, "cardholder_group": "SELECT, INSERT, DELETE",
    "cardholder": CONFIG, "credential": CONFIG,
}
SYSTEM_GRANTS = {t: "SELECT, INSERT, UPDATE, DELETE" for t in APP_POLICIES}
SYSTEM_GRANTS["audit_log"] = "SELECT, INSERT"
SYSTEM_GRANTS["sync_state"] = "SELECT, INSERT, UPDATE"


def _password(var: str) -> str:
    value = os.environ.get(var, "")
    if value and not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", value):
        raise RuntimeError(f"{var} must be 16 to 128 letters, digits, '-' or '_'")
    return value


def _role(name: str, password: str) -> None:
    op.execute(f"DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{name}') THEN "
               f"CREATE ROLE {name} NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOLOGIN; END IF; END $$")
    if password:
        op.execute(f"ALTER ROLE {name} LOGIN PASSWORD '{password}'")


def upgrade() -> None:
    _role("entry_app", _password("APP_DB_PASSWORD"))
    _role("entry_system", _password("SYSTEM_DB_PASSWORD"))
    for statement in TABLES.split(";"):
        if statement.strip():
            op.execute(statement)
    for f in FUNCTIONS:
        op.execute(f)
    op.execute("GRANT USAGE ON SCHEMA public TO entry_app, entry_system")
    op.execute("REVOKE ALL ON alembic_version FROM entry_app, entry_system")
    for table, grants in APP_GRANTS.items():
        op.execute(f'GRANT {grants} ON "{table}" TO entry_app')
    for table, grants in SYSTEM_GRANTS.items():
        op.execute(f'GRANT {grants} ON "{table}" TO entry_system')
    op.execute("GRANT USAGE ON SEQUENCE audit_log_id_seq TO entry_app, entry_system")
    op.execute("GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO entry_app, entry_system")
    for table in SYSTEM_GRANTS:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'CREATE POLICY "{table}_system" ON "{table}" FOR ALL TO entry_system USING (true) WITH CHECK (true)')
    for table, pols in APP_POLICIES.items():
        for name, cmd, using, check in pols:
            clause = (f"USING ({using}) " if using else "") + (f"WITH CHECK ({check})" if check else "")
            op.execute(f'CREATE POLICY "{table}_{name}" ON "{table}" FOR {cmd} TO entry_app {clause}')


def downgrade() -> None:
    for table in reversed(list(SYSTEM_GRANTS)):
        op.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE')
    for f in FUNCTION_NAMES:
        op.execute(f"DROP FUNCTION IF EXISTS {f}")

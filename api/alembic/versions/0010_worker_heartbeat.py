"""The worker's heartbeat (photon-suite OPERATIONS.md §2.5): one row the worker touches every pass, read by the API's /readyz

Revision ID: 0010
Revises: 0009
"""
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE TABLE worker_heartbeat (id integer PRIMARY KEY DEFAULT 1 CHECK (id = 1), at timestamptz NOT NULL)")
    op.execute("GRANT SELECT, INSERT, UPDATE ON worker_heartbeat TO entry_system")
    op.execute("GRANT SELECT ON alembic_version TO entry_system")   # /readyz: are the migrations at this release's head?
    op.execute("ALTER TABLE worker_heartbeat ENABLE ROW LEVEL SECURITY")
    op.execute('CREATE POLICY "worker_heartbeat_system" ON worker_heartbeat FOR ALL TO entry_system USING (true) WITH CHECK (true)')


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS worker_heartbeat")

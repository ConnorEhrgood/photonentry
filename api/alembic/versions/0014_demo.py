"""The demo organization (photon-suite DEMO.md): the directory's `demo` flag on the tenant, and the `simulated` mark on controllers and intercoms

Revision ID: 0014
Revises: 0013
"""
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Only the directory sync (entry_system) writes a tenant, and only the demo seed (entry_system) marks a device simulated: no new grants to
    # entry_app, whose column grants do not include these.
    op.execute("ALTER TABLE tenant ADD COLUMN demo boolean NOT NULL DEFAULT false")
    op.execute("ALTER TABLE controller ADD COLUMN simulated boolean NOT NULL DEFAULT false")
    op.execute("ALTER TABLE intercom ADD COLUMN simulated boolean NOT NULL DEFAULT false")


def downgrade() -> None:
    op.execute("ALTER TABLE intercom DROP COLUMN simulated")
    op.execute("ALTER TABLE controller DROP COLUMN simulated")
    op.execute("ALTER TABLE tenant DROP COLUMN demo")

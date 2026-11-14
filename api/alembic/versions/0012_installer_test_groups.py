"""Installer test groups (decision 27): the only access a door that is not yet commissioned gets

Revision ID: 0012
Revises: 0011
"""
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE access_group ADD COLUMN installer_test boolean NOT NULL DEFAULT false")
    op.execute("GRANT UPDATE (installer_test) ON access_group TO entry_app")


def downgrade() -> None:
    op.execute("ALTER TABLE access_group DROP COLUMN installer_test")

"""Lockdown notices by email (ARCHITECTURE §9.6): when the start and the end of a lockdown were mailed to the site's admins and operators

Revision ID: 0011
Revises: 0010

The worker sends them (app/notify.py), never the request that locks the doors.
"""
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE lockdown ADD COLUMN start_notified_at timestamptz")
    op.execute("ALTER TABLE lockdown ADD COLUMN end_notified_at timestamptz")


def downgrade() -> None:
    op.execute("ALTER TABLE lockdown DROP COLUMN end_notified_at")
    op.execute("ALTER TABLE lockdown DROP COLUMN start_notified_at")

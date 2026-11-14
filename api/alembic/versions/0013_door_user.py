"""The door user role (decision 25): people who open, from the app, the doors their own cardholder record allows

Revision ID: 0013
Revises: 0012
"""
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE access DROP CONSTRAINT IF EXISTS access_role_check")
    op.execute("ALTER TABLE access ADD CONSTRAINT access_role_check CHECK (role IN ('owner', 'admin', 'operator', 'viewer', 'door_user'))")
    # A door user sees their own organization's row (its name, in the app), nothing else: the policies' role lists stay viewer and up, and the
    # door user's doors are read for them by the system, scoped to their own cardholder (app/unlock.py).
    op.execute('CREATE POLICY "tenant_read_door_user" ON tenant FOR SELECT TO entry_app USING (id IN (SELECT en_tenants_with(ARRAY[\'door_user\'])))')


def downgrade() -> None:
    op.execute('DROP POLICY IF EXISTS "tenant_read_door_user" ON tenant')
    op.execute("DELETE FROM access WHERE role = 'door_user'")
    op.execute("ALTER TABLE access DROP CONSTRAINT IF EXISTS access_role_check")
    op.execute("ALTER TABLE access ADD CONSTRAINT access_role_check CHECK (role IN ('owner', 'admin', 'operator', 'viewer'))")

"""Organization slugs: the suite's addresses, /org/<slug>/ (photon-suite ARCHITECTURE §6; photonid docs/HOME-PLAN.md)

Revision ID: 0004
Revises: 0003

Only the directory gives a slug; its organization documents carry `slug` and `former_slugs` (every slug it had, which redirect). Until the next
pull fills them, the slug is empty and the web app falls back to the organization's id.
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tenant ADD COLUMN slug varchar(63) NOT NULL DEFAULT ''")
    op.execute("ALTER TABLE tenant ADD COLUMN former_slugs jsonb NOT NULL DEFAULT '[]'::jsonb")
    op.execute("CREATE INDEX ix_tenant_slug ON tenant (slug)")


def downgrade() -> None:
    op.execute("ALTER TABLE tenant DROP COLUMN former_slugs")
    op.execute("ALTER TABLE tenant DROP COLUMN slug")

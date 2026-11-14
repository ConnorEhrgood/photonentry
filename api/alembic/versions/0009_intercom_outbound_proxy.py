"""An intercom's SIP outbound proxy, from its PhotonVox door station (docs/VOX.md: when the SIP domain does not resolve to the engine)

Revision ID: 0009
Revises: 0008
"""
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE intercom ADD COLUMN sip_outbound_proxy varchar(80) NOT NULL DEFAULT ''")
    op.execute("GRANT UPDATE (sip_outbound_proxy) ON intercom TO entry_app")


def downgrade() -> None:
    op.execute("ALTER TABLE intercom DROP COLUMN sip_outbound_proxy")

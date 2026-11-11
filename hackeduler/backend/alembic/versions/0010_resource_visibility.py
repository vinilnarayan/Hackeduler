"""Resources can be hidden from requesters (admin-only assignment).

security_resources.visible_to_requesters: FALSE = the resource does not appear in the requester calendar or resource
list, is never picked by automatic assignment and cannot be chosen by a requester; only admins can assign work to it.

Revision ID: 0010
Revises: 0009
"""
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE security_resources ADD COLUMN visible_to_requesters BOOLEAN NOT NULL DEFAULT TRUE;")


def downgrade() -> None:
    op.execute("ALTER TABLE security_resources DROP COLUMN visible_to_requesters;")

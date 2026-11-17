"""Per-email Cc addresses (e.g. the assigned engineer on the activity initiation email).

Adds one nullable column; no existing data changes. Idempotent.

Revision ID: 0016
Revises: 0015
"""
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE email_notification_logs ADD COLUMN IF NOT EXISTS cc TEXT;")


def downgrade() -> None:
    op.execute("ALTER TABLE email_notification_logs DROP COLUMN IF EXISTS cc;")

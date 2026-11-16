"""Record which mail service (smtp / ses) delivered each email, for the delivery log.

Safe to run on a database that already has the column (IF NOT EXISTS), so a database that moved between the
local and AWS deployments ends up identical either way.

Revision ID: 0014
Revises: 0013
"""
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE email_notification_logs ADD COLUMN IF NOT EXISTS provider TEXT;")


def downgrade() -> None:
    op.execute("ALTER TABLE email_notification_logs DROP COLUMN IF EXISTS provider;")

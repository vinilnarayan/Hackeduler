"""Record which mail service delivered each email (smtp / ses), for the delivery log.

Revision ID: 0012
Revises: 0011
"""
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE email_notification_logs ADD COLUMN provider TEXT;")


def downgrade() -> None:
    op.execute("ALTER TABLE email_notification_logs DROP COLUMN provider;")

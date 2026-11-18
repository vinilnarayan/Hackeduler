"""HTML version of queued emails.

Adds one nullable column to the email log; no existing data changes. Idempotent.

Revision ID: 0017
Revises: 0016
"""
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE email_notification_logs ADD COLUMN IF NOT EXISTS body_html TEXT;")


def downgrade() -> None:
    op.execute("ALTER TABLE email_notification_logs DROP COLUMN IF EXISTS body_html;")

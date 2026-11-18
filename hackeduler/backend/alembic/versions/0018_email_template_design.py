"""Email template design (visual editor).

Adds three columns with defaults to email_templates; existing templates keep working unchanged
(body_format 'text', classic layout, navy). Idempotent.

Revision ID: 0018
Revises: 0017
"""
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE email_templates ADD COLUMN IF NOT EXISTS body_format TEXT NOT NULL DEFAULT 'text';")
    op.execute("ALTER TABLE email_templates ADD COLUMN IF NOT EXISTS layout TEXT NOT NULL DEFAULT 'classic';")
    op.execute("ALTER TABLE email_templates ADD COLUMN IF NOT EXISTS accent TEXT NOT NULL DEFAULT '#0f2744';")


def downgrade() -> None:
    op.execute("ALTER TABLE email_templates DROP COLUMN IF EXISTS accent;")
    op.execute("ALTER TABLE email_templates DROP COLUMN IF EXISTS layout;")
    op.execute("ALTER TABLE email_templates DROP COLUMN IF EXISTS body_format;")

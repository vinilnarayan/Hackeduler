"""Audit log: who really acted when an admin used "Act as" on behalf of another user.

Two nullable columns; existing audit rows are untouched. Idempotent.

Revision ID: 0023
Revises: 0022
"""
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS acted_by_id UUID;")
    op.execute("ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS acted_by_email TEXT;")


def downgrade() -> None:
    op.execute("ALTER TABLE audit_logs DROP COLUMN IF EXISTS acted_by_email;")
    op.execute("ALTER TABLE audit_logs DROP COLUMN IF EXISTS acted_by_id;")

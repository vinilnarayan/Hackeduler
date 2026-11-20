"""Activity types: optional yearly booking limit.

Adds a nullable column (NULL = unlimited), so every existing activity type behaves exactly as before. Idempotent.

Revision ID: 0019
Revises: 0018
"""
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE activity_types ADD COLUMN IF NOT EXISTS yearly_limit INTEGER;")


def downgrade() -> None:
    op.execute("ALTER TABLE activity_types DROP COLUMN IF EXISTS yearly_limit;")

"""Users: team-lead flag for resource users (grants the read-only Team Calendar).

Adds a boolean column defaulting to false, so every existing user keeps exactly the access they have today. Idempotent.

Revision ID: 0021
Revises: 0020
"""
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_lead BOOLEAN NOT NULL DEFAULT false;")


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS is_lead;")

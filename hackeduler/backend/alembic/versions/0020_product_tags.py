"""Tags on products and implementations (grouping, dashboard filter).

Adds a text[] column (default empty) to both tables; existing rows simply have no tags. Idempotent.

Revision ID: 0020
Revises: 0019
"""
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS tags TEXT[] NOT NULL DEFAULT '{}';")
    op.execute("ALTER TABLE implementations ADD COLUMN IF NOT EXISTS tags TEXT[] NOT NULL DEFAULT '{}';")


def downgrade() -> None:
    op.execute("ALTER TABLE implementations DROP COLUMN IF EXISTS tags;")
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS tags;")

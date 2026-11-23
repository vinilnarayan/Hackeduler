"""Bookings: link to the shared report (e.g. a SharePoint URL).

Adds one nullable column; existing bookings and reports are untouched. Idempotent.

Revision ID: 0022
Revises: 0021
"""
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE bookings ADD COLUMN IF NOT EXISTS report_url TEXT;")


def downgrade() -> None:
    op.execute("ALTER TABLE bookings DROP COLUMN IF EXISTS report_url;")

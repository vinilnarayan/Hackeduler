"""Scheduled resource deactivation: a resource can be made inactive from a given date.

inactive_from = first date on which the resource is unavailable. Before that date it
behaves normally; on/after it, it cannot be booked. The worker flips is_active to false
when the date arrives. Immediate deactivation records today's date here as well.

Revision ID: 0003
Revises: 0002
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE security_resources ADD COLUMN inactive_from DATE;
        ALTER TABLE security_resources ADD COLUMN inactive_reason TEXT;
        UPDATE security_resources SET inactive_from = (deactivated_at AT TIME ZONE 'UTC')::date
            WHERE is_active = FALSE AND deactivated_at IS NOT NULL;
        CREATE INDEX ix_resources_inactive_from ON security_resources (inactive_from) WHERE inactive_from IS NOT NULL;
    """)


def downgrade() -> None:
    op.execute("""
        DROP INDEX IF EXISTS ix_resources_inactive_from;
        ALTER TABLE security_resources DROP COLUMN IF EXISTS inactive_reason;
        ALTER TABLE security_resources DROP COLUMN IF EXISTS inactive_from;
    """)

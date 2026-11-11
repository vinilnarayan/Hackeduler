"""Activity initiation email: per-activity-type settings and per-booking send tracking.

activity_types.initiation_email_enabled   FALSE = never send this email for the activity type
activity_types.initiation_days_before     NULL = use the global setting (initiation_email_days_before)
activity_types.initiation_details         NULL = built-in default checklist for the type of activity
bookings.initiation_email_sent_at         when it was last sent
bookings.initiation_email_for_start       the start date it was sent for (a new start date => sent again)

Revision ID: 0009
Revises: 0008
"""
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE activity_types ADD COLUMN initiation_email_enabled BOOLEAN NOT NULL DEFAULT TRUE;
        ALTER TABLE activity_types ADD COLUMN initiation_days_before INTEGER;
        ALTER TABLE activity_types ADD COLUMN initiation_details TEXT;
        ALTER TABLE activity_types ADD CONSTRAINT ck_activity_initiation_days
            CHECK (initiation_days_before IS NULL OR (initiation_days_before >= 0 AND initiation_days_before <= 365));
        ALTER TABLE bookings ADD COLUMN initiation_email_sent_at TIMESTAMPTZ;
        ALTER TABLE bookings ADD COLUMN initiation_email_for_start DATE;
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE bookings DROP COLUMN initiation_email_for_start;
        ALTER TABLE bookings DROP COLUMN initiation_email_sent_at;
        ALTER TABLE activity_types DROP CONSTRAINT ck_activity_initiation_days;
        ALTER TABLE activity_types DROP COLUMN initiation_details;
        ALTER TABLE activity_types DROP COLUMN initiation_days_before;
        ALTER TABLE activity_types DROP COLUMN initiation_email_enabled;
    """)

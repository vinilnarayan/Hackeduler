"""Activity types: hide from requesters, and remove (archive).

* visible_to_requesters: FALSE keeps the type usable by admins (Manual Allocation) but hides it from requesters.
* deleted_at: removed types are archived, never erased, when bookings reference them, so booking history keeps
  working. Removed types disappear from every list and cannot be booked. The (name, duration) uniqueness only
  applies to types that have not been removed, so a removed name can be created again.

Revision ID: 0007
Revises: 0006
"""
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE activity_types ADD COLUMN visible_to_requesters BOOLEAN NOT NULL DEFAULT TRUE;
        ALTER TABLE activity_types ADD COLUMN deleted_at TIMESTAMPTZ;
        ALTER TABLE activity_types DROP CONSTRAINT uq_activity_name_duration;
        CREATE UNIQUE INDEX uq_activity_name_duration ON activity_types (name, base_duration_days) WHERE deleted_at IS NULL;
    """)


def downgrade() -> None:
    # NOTE: fails if a removed (archived) type shares its name and duration with a live one - rename one first.
    op.execute("""
        DROP INDEX uq_activity_name_duration;
        ALTER TABLE activity_types ADD CONSTRAINT uq_activity_name_duration UNIQUE (name, base_duration_days);
        ALTER TABLE activity_types DROP COLUMN deleted_at;
        ALTER TABLE activity_types DROP COLUMN visible_to_requesters;
    """)

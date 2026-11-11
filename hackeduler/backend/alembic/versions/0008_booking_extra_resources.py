"""Bookings can hold additional security resources (admin multi-resource allocation).

The primary resource stays in bookings.resource_id. Every resource (primary and additional) still has its own
rows in booking_resource_locks, so availability, the calendar and double-booking protection need no change.

Revision ID: 0008
Revises: 0007
"""
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE booking_extra_resources (
            booking_id UUID NOT NULL REFERENCES bookings(id) ON DELETE CASCADE,
            resource_id UUID NOT NULL REFERENCES security_resources(id),
            PRIMARY KEY (booking_id, resource_id)
        );
        CREATE INDEX ix_booking_extra_resources_resource ON booking_extra_resources (resource_id);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE booking_extra_resources;")

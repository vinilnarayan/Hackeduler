"""Resource (security engineer) role, user -> resource link, and booking report-shared tracking.

roles: id 3 'resource' - sees only the bookings assigned to their own resource, records report sharing, manages leave.
users.resource_id: the security resource a 'resource' user represents (at most one active user per resource).
bookings.report_*: whether the report has been shared, which kind (V1 / Met) and free-text comments.

Revision ID: 0011
Revises: 0010
"""
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE roles DROP CONSTRAINT roles_name_check;
        ALTER TABLE roles ADD CONSTRAINT roles_name_check CHECK (name IN ('admin', 'requester', 'resource'));
        INSERT INTO roles (id, name, description) VALUES (3, 'resource', 'Security engineer: sees own assigned bookings, records report sharing, manages own leave')
            ON CONFLICT (id) DO NOTHING;
        ALTER TABLE users ADD COLUMN resource_id UUID REFERENCES security_resources(id);
        CREATE UNIQUE INDEX uq_users_resource ON users (resource_id) WHERE resource_id IS NOT NULL AND deleted_at IS NULL;
        ALTER TABLE bookings ADD COLUMN report_shared BOOLEAN NOT NULL DEFAULT FALSE;
        ALTER TABLE bookings ADD COLUMN report_type TEXT;
        ALTER TABLE bookings ADD COLUMN report_comments TEXT;
        ALTER TABLE bookings ADD COLUMN report_shared_at TIMESTAMPTZ;
        ALTER TABLE bookings ADD COLUMN report_updated_by UUID REFERENCES users(id);
        ALTER TABLE bookings ADD CONSTRAINT ck_booking_report_type CHECK (report_type IS NULL OR report_type IN ('V1', 'Met'));
        ALTER TABLE bookings ADD CONSTRAINT ck_booking_report_shared_type CHECK (NOT report_shared OR report_type IS NOT NULL);
    """)


def downgrade() -> None:
    # NOTE: users with the resource role must be changed or removed first (role id 3 is referenced).
    op.execute("""
        ALTER TABLE bookings DROP CONSTRAINT ck_booking_report_shared_type;
        ALTER TABLE bookings DROP CONSTRAINT ck_booking_report_type;
        ALTER TABLE bookings DROP COLUMN report_updated_by;
        ALTER TABLE bookings DROP COLUMN report_shared_at;
        ALTER TABLE bookings DROP COLUMN report_comments;
        ALTER TABLE bookings DROP COLUMN report_type;
        ALTER TABLE bookings DROP COLUMN report_shared;
        DROP INDEX uq_users_resource;
        ALTER TABLE users DROP COLUMN resource_id;
        DELETE FROM roles WHERE id = 3;
        ALTER TABLE roles DROP CONSTRAINT roles_name_check;
        ALTER TABLE roles ADD CONSTRAINT roles_name_check CHECK (name IN ('admin', 'requester'));
    """)

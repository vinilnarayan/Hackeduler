"""Delete users and resources.

Records with no history are removed outright. Records referenced by bookings,
audit history etc. are archived (deleted_at set) so historical data stays intact;
archived records are hidden everywhere and cannot sign in or be booked.
A deleted user's email address can be reused for a new account.

Revision ID: 0005
Revises: 0004
"""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE users ADD COLUMN deleted_at TIMESTAMPTZ;
        ALTER TABLE security_resources ADD COLUMN deleted_at TIMESTAMPTZ;
        DROP INDEX uq_users_email_lower;
        CREATE UNIQUE INDEX uq_users_email_lower ON users (lower(email)) WHERE deleted_at IS NULL;
    """)


def downgrade() -> None:
    op.execute("""
        DROP INDEX uq_users_email_lower;
        CREATE UNIQUE INDEX uq_users_email_lower ON users (lower(email));
        ALTER TABLE security_resources DROP COLUMN deleted_at;
        ALTER TABLE users DROP COLUMN deleted_at;
    """)

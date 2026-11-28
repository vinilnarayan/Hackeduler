"""'Booking Updated' email applies to a booking in ANY status: drop the word "approved" from the sentence.

Templates are copied into the database once, so this replaces ONLY the original sentence, and only where it is still
present; a template an administrator edited and that no longer contains it is left untouched. Idempotent.

Revision ID: 0025
Revises: 0024
"""
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None

OLD = "Your approved security assessment booking has been updated by"
NEW = "Your security assessment booking has been updated by"


def upgrade() -> None:
    op.execute(
        "UPDATE email_templates SET body_template = replace(body_template, '%s', '%s') "
        "WHERE key = 'booking_modified_poc' AND position('%s' in body_template) > 0" % (OLD, NEW, OLD))


def downgrade() -> None:
    op.execute(
        "UPDATE email_templates SET body_template = replace(body_template, '%s', '%s') "
        "WHERE key = 'booking_modified_poc'" % (NEW, OLD))

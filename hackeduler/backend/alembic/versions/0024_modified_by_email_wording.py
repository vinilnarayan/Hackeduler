"""'Booking Updated' email: say who made the change ("... has been updated by {{Modified By}}.").

Email templates are copied into the database once, so the new wording does not reach an existing template by itself.
This replaces ONLY the original sentence, and only where it is still present; a template that was edited by an
administrator and no longer contains it is left untouched. Idempotent.

Revision ID: 0024
Revises: 0023
"""
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None

OLD = "Your approved security assessment booking has been updated."
NEW = "Your approved security assessment booking has been updated by {{Modified By}}."


def upgrade() -> None:
    op.execute(
        "UPDATE email_templates SET body_template = replace(body_template, '%s', '%s') "
        "WHERE key = 'booking_modified_poc' AND position('%s' in body_template) > 0" % (OLD, NEW, OLD))


def downgrade() -> None:
    op.execute(
        "UPDATE email_templates SET body_template = replace(body_template, '%s', '%s') "
        "WHERE key = 'booking_modified_poc'" % (NEW, OLD))

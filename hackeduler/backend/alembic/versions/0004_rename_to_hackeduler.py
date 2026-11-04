"""Rename the application to Hackeduler in data stored by existing installations.

Email templates and the sender-name setting are stored in the database, so the
code rename alone would not change them. Only values still matching the old
defaults are touched; admin customisations are otherwise preserved.

Revision ID: 0004
Revises: 0003
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE email_templates SET
            subject_template = replace(subject_template, '[OffSec Scheduler]', '[Hackeduler]'),
            body_template = replace(body_template, 'OffSec Resource Planner', 'Hackeduler'),
            updated_at = now()
        WHERE subject_template LIKE '%[OffSec Scheduler]%' OR body_template LIKE '%OffSec Resource Planner%';

        UPDATE application_settings SET value = '"Hackeduler"'::jsonb, updated_at = now()
        WHERE key = 'email_sender_name' AND value = '"OffSec Resource Planner"'::jsonb;

        UPDATE application_settings SET value = '"hackeduler@example.com"'::jsonb, updated_at = now()
        WHERE key = 'email_sender_address' AND value = '"offsec-scheduler@example.com"'::jsonb;
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE email_templates SET
            subject_template = replace(subject_template, '[Hackeduler]', '[OffSec Scheduler]'),
            body_template = replace(body_template, 'Hackeduler', 'OffSec Resource Planner')
        WHERE subject_template LIKE '%[Hackeduler]%' OR body_template LIKE '%Hackeduler%';
        UPDATE application_settings SET value = '"OffSec Resource Planner"'::jsonb
        WHERE key = 'email_sender_name' AND value = '"Hackeduler"'::jsonb;
        UPDATE application_settings SET value = '"offsec-scheduler@example.com"'::jsonb
        WHERE key = 'email_sender_address' AND value = '"hackeduler@example.com"'::jsonb;
    """)

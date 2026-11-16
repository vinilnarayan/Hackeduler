"""Private day notes for resource users (shown on their dashboard calendar).

Revision ID: 0013
Revises: 0011
"""
from alembic import op

revision = "0013"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE resource_notes (
            id UUID PRIMARY KEY,
            resource_id UUID NOT NULL REFERENCES security_resources(id),
            note_date DATE NOT NULL,
            note TEXT NOT NULL,
            created_by UUID REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_resource_note_nonblank CHECK (length(btrim(note)) > 0)
        );
        CREATE INDEX ix_resource_notes_resource_date ON resource_notes (resource_id, note_date);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE resource_notes;")

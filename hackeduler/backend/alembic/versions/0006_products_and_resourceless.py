"""Products/implementations, auto-assigned resources, and activities without a resource.

* products 1-* implementations; users and bookings reference both. Requesters in the
  same product can see each other's bookings.
* activity_types.requires_resource: false for activities such as automated scans that
  need no security engineer. Their duration is optional.
* bookings.resource_id / dates / duration become nullable for such activities; a
  CHECK keeps them mandatory for resource-based bookings.

Revision ID: 0006
Revises: 0005
"""
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE products (
            id           UUID PRIMARY KEY,
            name         TEXT NOT NULL,
            description  TEXT,
            is_active    BOOLEAN NOT NULL DEFAULT TRUE,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE UNIQUE INDEX uq_products_name ON products (lower(name));

        CREATE TABLE implementations (
            id           UUID PRIMARY KEY,
            product_id   UUID NOT NULL REFERENCES products(id),
            name         TEXT NOT NULL,
            description  TEXT,
            is_active    BOOLEAN NOT NULL DEFAULT TRUE,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE UNIQUE INDEX uq_implementations_name ON implementations (product_id, lower(name));

        ALTER TABLE users ADD COLUMN product_id UUID REFERENCES products(id);
        ALTER TABLE users ADD COLUMN implementation_id UUID REFERENCES implementations(id);

        ALTER TABLE activity_types ADD COLUMN requires_resource BOOLEAN NOT NULL DEFAULT TRUE;
        ALTER TABLE activity_types ALTER COLUMN base_duration_days DROP NOT NULL;
        ALTER TABLE activity_types ADD CONSTRAINT ck_activity_duration_required
            CHECK (requires_resource = FALSE OR base_duration_days IS NOT NULL);

        ALTER TABLE bookings ADD COLUMN product_id UUID REFERENCES products(id);
        ALTER TABLE bookings ADD COLUMN implementation_id UUID REFERENCES implementations(id);
        ALTER TABLE bookings ADD COLUMN requires_resource BOOLEAN NOT NULL DEFAULT TRUE;
        ALTER TABLE bookings ALTER COLUMN resource_id DROP NOT NULL;
        ALTER TABLE bookings ALTER COLUMN start_date DROP NOT NULL;
        ALTER TABLE bookings ALTER COLUMN end_date DROP NOT NULL;
        ALTER TABLE bookings ALTER COLUMN duration_days DROP NOT NULL;
        ALTER TABLE bookings ALTER COLUMN base_duration_snapshot DROP NOT NULL;
        ALTER TABLE bookings ADD CONSTRAINT ck_booking_resource_fields
            CHECK (requires_resource = FALSE OR (resource_id IS NOT NULL AND start_date IS NOT NULL
                   AND end_date IS NOT NULL AND duration_days IS NOT NULL));
        CREATE INDEX ix_bookings_product ON bookings (product_id, submitted_at);
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM bookings WHERE requires_resource = FALSE;
        DROP INDEX IF EXISTS ix_bookings_product;
        ALTER TABLE bookings DROP CONSTRAINT IF EXISTS ck_booking_resource_fields;
        ALTER TABLE bookings DROP COLUMN requires_resource, DROP COLUMN implementation_id, DROP COLUMN product_id;
        ALTER TABLE activity_types DROP CONSTRAINT IF EXISTS ck_activity_duration_required;
        ALTER TABLE activity_types DROP COLUMN requires_resource;
        ALTER TABLE users DROP COLUMN implementation_id, DROP COLUMN product_id;
        DROP TABLE implementations;
        DROP TABLE products;
    """)

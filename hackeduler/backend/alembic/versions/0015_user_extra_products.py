"""Requesters can belong to several products.

users.product_id stays as the person's primary (default) product; this table holds the additional ones.
No existing data changes.

Revision ID: 0015
Revises: 0014
"""
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE user_products (
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            product_id UUID NOT NULL REFERENCES products(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (user_id, product_id)
        );
        CREATE INDEX ix_user_products_product ON user_products (product_id);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE user_products;")

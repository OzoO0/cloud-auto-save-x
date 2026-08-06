"""enable plugins by default

Revision ID: 6b5e9e7f9c2a
Revises: 20260509_extensions_runtime
Create Date: 2026-05-09 14:55:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "6b5e9e7f9c2a"
down_revision = "20260509_extensions_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("plugin_configs") as batch_op:
        batch_op.alter_column("enabled", existing_type=sa.Boolean(), existing_nullable=False, server_default="1")

    op.execute("UPDATE plugin_configs SET enabled = 1 WHERE enabled = 0")


def downgrade() -> None:
    op.execute("UPDATE plugin_configs SET enabled = 0 WHERE enabled = 1")

    with op.batch_alter_table("plugin_configs") as batch_op:
        batch_op.alter_column("enabled", existing_type=sa.Boolean(), existing_nullable=False, server_default="0")

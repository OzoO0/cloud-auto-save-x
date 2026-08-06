"""drive account profile snapshot

Revision ID: 3f2d8d9d1e11
Revises: 8c4b7f7f0e41
Create Date: 2026-05-09 18:20:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "3f2d8d9d1e11"
down_revision = "8c4b7f7f0e41"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("drive_accounts")}

    with op.batch_alter_table("drive_accounts") as batch_op:
        if "profile_json" not in columns:
            batch_op.add_column(sa.Column("profile_json", sa.Text(), nullable=True))
        if "capacity_warning_threshold" not in columns:
            batch_op.add_column(sa.Column("capacity_warning_threshold", sa.Integer(), nullable=False, server_default="85"))

    op.execute(
        """
        UPDATE drive_accounts
        SET capacity_warning_threshold = 85
        WHERE capacity_warning_threshold IS NULL
        """
    )


def downgrade() -> None:
    with op.batch_alter_table("drive_accounts") as batch_op:
        batch_op.drop_column("capacity_warning_threshold")
        batch_op.drop_column("profile_json")

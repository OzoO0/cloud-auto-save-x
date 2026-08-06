"""drive accounts config json

Revision ID: 8c4b7f7f0e41
Revises: 6b5e9e7f9c2a
Create Date: 2026-05-09 16:30:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "8c4b7f7f0e41"
down_revision = "6b5e9e7f9c2a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("drive_accounts")}
    if "config_json" not in columns:
        with op.batch_alter_table("drive_accounts") as batch_op:
            batch_op.add_column(sa.Column("config_json", sa.Text(), nullable=True))

    op.execute(
        """
        UPDATE drive_accounts
        SET config_json =
            CASE drive_type
                WHEN 'aliyun' THEN json_object('refresh_token', cookie)
                WHEN 'xunlei' THEN json_object('refresh_token', cookie)
                ELSE json_object('cookie', cookie)
            END
        WHERE config_json IS NULL
        """
    )


def downgrade() -> None:
    with op.batch_alter_table("drive_accounts") as batch_op:
        batch_op.drop_column("config_json")

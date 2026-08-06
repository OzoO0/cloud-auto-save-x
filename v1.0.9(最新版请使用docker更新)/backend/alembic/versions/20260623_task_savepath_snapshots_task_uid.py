"""task savepath snapshots task uid

Revision ID: 20260623_task_savepath_snapshots_task_uid
Revises: 20260622_task_savepath_snapshots
Create Date: 2026-06-23 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = "20260623_task_savepath_snapshots_task_uid"
down_revision = "20260622_task_savepath_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "task_savepath_snapshots" not in inspector.get_table_names():
        return
    if "task_savepath_snapshots__tmp" in inspector.get_table_names():
        op.drop_table("task_savepath_snapshots__tmp")

    cols = {c["name"] for c in inspector.get_columns("task_savepath_snapshots")}
    if "task_uid" in cols:
        return

    op.create_table(
        "task_savepath_snapshots__tmp",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("task_uid", sa.String(length=64), nullable=False),
        sa.Column("task_execution_id", sa.Integer(), nullable=True),
        sa.Column("drive_account_id", sa.Integer(), nullable=True),
        sa.Column("savepath", sa.String(length=255), nullable=False),
        sa.Column("files_json", sa.Text(), nullable=False),
        sa.Column("file_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_size", sa.BigInteger(), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["task_uid"], ["tasks.task_uid"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_execution_id"], ["task_executions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["drive_account_id"], ["drive_accounts.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("task_uid", name="uq_task_savepath_snapshots_task_uid"),
    )

    bind.execute(
        text(
            """
            INSERT INTO task_savepath_snapshots__tmp (
                id, task_uid, task_execution_id, drive_account_id, savepath, files_json, file_count, total_size, captured_at
            )
            SELECT
                s.id,
                t.task_uid,
                s.task_execution_id,
                s.drive_account_id,
                s.savepath,
                s.files_json,
                s.file_count,
                s.total_size,
                s.captured_at
            FROM task_savepath_snapshots s
            JOIN tasks t ON t.id = s.task_id
            """
        )
    )

    op.drop_table("task_savepath_snapshots")
    op.rename_table("task_savepath_snapshots__tmp", "task_savepath_snapshots")
    inspector = inspect(bind)
    existing = {idx["name"] for idx in inspector.get_indexes("task_savepath_snapshots")}
    if "ix_task_savepath_snapshots_task_execution_id" not in existing:
        op.create_index(
            "ix_task_savepath_snapshots_task_execution_id",
            "task_savepath_snapshots",
            ["task_execution_id"],
        )
    if "ix_task_savepath_snapshots_drive_account_id" not in existing:
        op.create_index(
            "ix_task_savepath_snapshots_drive_account_id",
            "task_savepath_snapshots",
            ["drive_account_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "task_savepath_snapshots" not in inspector.get_table_names():
        return
    if "task_savepath_snapshots__tmp" in inspector.get_table_names():
        op.drop_table("task_savepath_snapshots__tmp")

    cols = {c["name"] for c in inspector.get_columns("task_savepath_snapshots")}
    if "task_id" in cols:
        return

    op.create_table(
        "task_savepath_snapshots__tmp",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("task_execution_id", sa.Integer(), nullable=True),
        sa.Column("drive_account_id", sa.Integer(), nullable=True),
        sa.Column("savepath", sa.String(length=255), nullable=False),
        sa.Column("files_json", sa.Text(), nullable=False),
        sa.Column("file_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_size", sa.BigInteger(), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_execution_id"], ["task_executions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["drive_account_id"], ["drive_accounts.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("task_id", name="uq_task_savepath_snapshots_task_id"),
    )

    bind.execute(
        text(
            """
            INSERT INTO task_savepath_snapshots__tmp (
                id, task_id, task_execution_id, drive_account_id, savepath, files_json, file_count, total_size, captured_at
            )
            SELECT
                s.id,
                t.id,
                s.task_execution_id,
                s.drive_account_id,
                s.savepath,
                s.files_json,
                s.file_count,
                s.total_size,
                s.captured_at
            FROM task_savepath_snapshots s
            JOIN tasks t ON t.task_uid = s.task_uid
            """
        )
    )

    op.drop_table("task_savepath_snapshots")
    op.rename_table("task_savepath_snapshots__tmp", "task_savepath_snapshots")
    inspector = inspect(bind)
    existing = {idx["name"] for idx in inspector.get_indexes("task_savepath_snapshots")}
    if "ix_task_savepath_snapshots_task_execution_id" not in existing:
        op.create_index(
            "ix_task_savepath_snapshots_task_execution_id",
            "task_savepath_snapshots",
            ["task_execution_id"],
        )
    if "ix_task_savepath_snapshots_drive_account_id" not in existing:
        op.create_index(
            "ix_task_savepath_snapshots_drive_account_id",
            "task_savepath_snapshots",
            ["drive_account_id"],
        )

"""telegram bot state and sessions

Revision ID: 20260613_telegram_bot_state_and_sessions
Revises: 20260705_task_savepath_snapshots_saved_latest_progress
Create Date: 2026-06-13 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260613_telegram_bot_state_and_sessions"
down_revision = "20260705_task_savepath_snapshots_saved_latest_progress"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "telegram_bot_states" not in tables:
        op.create_table(
            "telegram_bot_states",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("last_update_id", sa.Integer(), server_default="0", nullable=False),
            sa.Column("last_error", sa.String(length=1024), nullable=True),
            sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_processed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.execute("INSERT INTO telegram_bot_states (id, last_update_id) VALUES (1, 0)")

    if "telegram_bot_sessions" not in tables:
        op.create_table(
            "telegram_bot_sessions",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("chat_id", sa.BigInteger(), nullable=False),
            sa.Column("user_id", sa.BigInteger(), nullable=False),
            sa.Column("scene", sa.String(length=64), server_default="home", nullable=False),
            sa.Column("step", sa.String(length=64), server_default="idle", nullable=False),
            sa.Column("context_json", sa.Text(), server_default="{}", nullable=False),
            sa.Column("last_message_id", sa.BigInteger(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("chat_id", "user_id", name="uq_telegram_bot_sessions_chat_user"),
        )
        op.create_index("ix_telegram_bot_sessions_chat_id", "telegram_bot_sessions", ["chat_id"], unique=False)
        op.create_index("ix_telegram_bot_sessions_user_id", "telegram_bot_sessions", ["user_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "telegram_bot_sessions" in tables:
        try:
            op.drop_index("ix_telegram_bot_sessions_chat_id", table_name="telegram_bot_sessions")
        except Exception:
            pass
        try:
            op.drop_index("ix_telegram_bot_sessions_user_id", table_name="telegram_bot_sessions")
        except Exception:
            pass
        op.drop_table("telegram_bot_sessions")

    if "telegram_bot_states" in tables:
        op.drop_table("telegram_bot_states")

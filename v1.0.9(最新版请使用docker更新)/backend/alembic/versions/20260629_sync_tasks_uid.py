"""sync tasks uid

Revision ID: 20260629_sync_tasks_uid
Revises: 20260628_sync_execution_files
Create Date: 2026-06-29 00:00:00.000000

"""

import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260629_sync_tasks_uid"
down_revision = "20260628_sync_execution_files"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())
    if "sync_tasks" not in existing_tables:
        return

    cols = {c["name"] for c in inspector.get_columns("sync_tasks")}
    if "uid" not in cols:
        op.add_column("sync_tasks", sa.Column("uid", sa.String(length=32), nullable=True))

    inspector = inspect(bind)
    indexes = inspector.get_indexes("sync_tasks")
    has_uid_index = any(str(i.get("name") or "") == "ux_sync_tasks_uid" for i in indexes)

    existing_uids: set[str] = set()
    try:
        rows = bind.execute(sa.text("SELECT uid FROM sync_tasks WHERE uid IS NOT NULL AND uid != ''")).fetchall()
        for (v,) in rows:
            if v:
                existing_uids.add(str(v))
    except Exception:
        existing_uids = set()

    try:
        rows = bind.execute(sa.text("SELECT id FROM sync_tasks WHERE uid IS NULL OR uid = ''")).fetchall()
    except Exception:
        rows = []

    for (sid,) in rows:
        new_uid = uuid.uuid4().hex
        while new_uid in existing_uids:
            new_uid = uuid.uuid4().hex
        existing_uids.add(new_uid)
        bind.execute(sa.text("UPDATE sync_tasks SET uid = :uid WHERE id = :id"), {"uid": new_uid, "id": int(sid)})

    if not has_uid_index:
        op.create_index("ux_sync_tasks_uid", "sync_tasks", ["uid"], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())
    if "sync_tasks" not in existing_tables:
        return

    indexes = inspector.get_indexes("sync_tasks")
    if any(str(i.get("name") or "") == "ux_sync_tasks_uid" for i in indexes):
        op.drop_index("ux_sync_tasks_uid", table_name="sync_tasks")

    cols = {c["name"] for c in inspector.get_columns("sync_tasks")}
    if "uid" in cols:
        op.drop_column("sync_tasks", "uid")


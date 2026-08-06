"""audit read permission

Revision ID: 20260619_audit_read_permission
Revises: 20260618_drive_account_probe_scheduler_setting
Create Date: 2026-06-19 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260619_audit_read_permission"
down_revision = "20260618_drive_account_probe_scheduler_setting"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if not {"permissions", "roles", "role_permissions"}.issubset(tables):
        return

    code = "audit:read"
    name = "审计日志查看"

    permission_id = bind.execute(sa.text("SELECT id FROM permissions WHERE code = :code"), {"code": code}).scalar()
    if permission_id is None:
        bind.execute(
            sa.text("INSERT INTO permissions (code, name, description) VALUES (:code, :name, :desc)"),
            {"code": code, "name": name, "desc": None},
        )
        permission_id = bind.execute(sa.text("SELECT id FROM permissions WHERE code = :code"), {"code": code}).scalar()

    admin_role_id = bind.execute(sa.text("SELECT id FROM roles WHERE name = :name"), {"name": "admin"}).scalar()
    if admin_role_id is None or permission_id is None:
        return

    exists = bind.execute(
        sa.text("SELECT 1 FROM role_permissions WHERE role_id = :rid AND permission_id = :pid"),
        {"rid": int(admin_role_id), "pid": int(permission_id)},
    ).scalar()
    if exists is None:
        bind.execute(
            sa.text("INSERT INTO role_permissions (role_id, permission_id) VALUES (:rid, :pid)"),
            {"rid": int(admin_role_id), "pid": int(permission_id)},
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if not {"permissions", "role_permissions"}.issubset(tables):
        return

    code = "audit:read"
    permission_id = bind.execute(sa.text("SELECT id FROM permissions WHERE code = :code"), {"code": code}).scalar()
    if permission_id is None:
        return
    bind.execute(sa.text("DELETE FROM role_permissions WHERE permission_id = :pid"), {"pid": int(permission_id)})
    bind.execute(sa.text("DELETE FROM permissions WHERE id = :pid"), {"pid": int(permission_id)})


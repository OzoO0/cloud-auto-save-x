"""extensions runtime

Revision ID: 20260509_extensions_runtime
Revises: 112649d93a0e
Create Date: 2026-05-09 14:30:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = '20260509_extensions_runtime'
down_revision = '112649d93a0e'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('drive_accounts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('drive_type', sa.String(length=64), nullable=False),
        sa.Column('cookie', sa.Text(), nullable=False),
        sa.Column('enabled', sa.Boolean(), server_default='1', nullable=False),
        sa.Column('is_default', sa.Boolean(), server_default='0', nullable=False),
        sa.Column('runtime_status', sa.String(length=32), nullable=True),
        sa.Column('last_checked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_drive_accounts_name'), 'drive_accounts', ['name'], unique=True)
    op.create_index(op.f('ix_drive_accounts_drive_type'), 'drive_accounts', ['drive_type'], unique=False)

    op.create_table('plugin_definitions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('plugin_key', sa.String(length=128), nullable=False),
        sa.Column('module_name', sa.String(length=128), nullable=False),
        sa.Column('source_type', sa.String(length=16), nullable=False),
        sa.Column('version', sa.String(length=32), nullable=True),
        sa.Column('installed', sa.Boolean(), server_default='1', nullable=False),
        sa.Column('discovered_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_plugin_definitions_plugin_key'), 'plugin_definitions', ['plugin_key'], unique=True)
    op.create_index('uq_plugin_definitions_module_name', 'plugin_definitions', ['module_name'], unique=True)

    op.create_table('plugin_configs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('plugin_definition_id', sa.Integer(), nullable=False),
        sa.Column('enabled', sa.Boolean(), server_default='0', nullable=False),
        sa.Column('priority', sa.Integer(), server_default='100', nullable=False),
        sa.Column('config_json', sa.Text(), nullable=True),
        sa.Column('default_task_config_json', sa.Text(), nullable=True),
        sa.Column('runtime_status', sa.String(length=32), nullable=True),
        sa.Column('last_checked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['plugin_definition_id'], ['plugin_definitions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('plugin_definition_id')
    )

    op.create_table('tasks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('task_uid', sa.String(length=64), nullable=False),
        sa.Column('taskname', sa.String(length=255), nullable=False),
        sa.Column('shareurl', sa.Text(), nullable=False),
        sa.Column('savepath', sa.String(length=255), nullable=False),
        sa.Column('pattern', sa.String(length=255), nullable=True),
        sa.Column('replace', sa.String(length=255), nullable=True),
        sa.Column('enddate', sa.String(length=32), nullable=True),
        sa.Column('ignore_extension', sa.Boolean(), server_default='0', nullable=False),
        sa.Column('sort_index', sa.Integer(), nullable=True),
        sa.Column('startfid', sa.String(length=128), nullable=True),
        sa.Column('account_name', sa.String(length=128), nullable=True),
        sa.Column('update_subdir', sa.String(length=255), nullable=True),
        sa.Column('enabled', sa.Boolean(), server_default='1', nullable=False),
        sa.Column('addition_json', sa.Text(), nullable=True),
        sa.Column('extra_json', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_tasks_task_uid'), 'tasks', ['task_uid'], unique=True)

    op.create_table('task_executions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('task_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('tree_summary', sa.Text(), nullable=True),
        sa.Column('message', sa.Text(), nullable=True),
        sa.Column('adapter_snapshot', sa.Text(), nullable=True),
        sa.Column('plugins_snapshot', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_task_executions_task_id'), 'task_executions', ['task_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_task_executions_task_id'), table_name='task_executions')
    op.drop_table('task_executions')
    op.drop_index(op.f('ix_tasks_task_uid'), table_name='tasks')
    op.drop_table('tasks')
    op.drop_table('plugin_configs')
    op.drop_index('uq_plugin_definitions_module_name', table_name='plugin_definitions')
    op.drop_index(op.f('ix_plugin_definitions_plugin_key'), table_name='plugin_definitions')
    op.drop_table('plugin_definitions')
    op.drop_index(op.f('ix_drive_accounts_drive_type'), table_name='drive_accounts')
    op.drop_index(op.f('ix_drive_accounts_name'), table_name='drive_accounts')
    op.drop_table('drive_accounts')

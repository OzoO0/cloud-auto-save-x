from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.extensions.adapters.adapter_factory import AccountManager
from app.extensions.runtime.adapter_registry import AdapterRegistry
from app.models.drive_account import DriveAccount


class DatabaseAccountManager:
    def __init__(self, db: Session, *, no_login: bool = False):
        self.db = db
        self.manager = AccountManager()
        self.accounts = db.execute(select(DriveAccount).order_by(DriveAccount.is_default.desc(), DriveAccount.id.asc())).scalars().all()
        payload = {
            'accounts': [
                {
                    'name': item.name,
                    'drive_type': item.drive_type,
                    'config': AdapterRegistry.parse_config_json(item.drive_type, item.config_json, item.cookie),
                    'cookie': AdapterRegistry.serialize_config(
                        item.drive_type,
                        AdapterRegistry.parse_config_json(item.drive_type, item.config_json, item.cookie),
                    ),
                    'enabled': item.enabled,
                    'default': item.is_default,
                }
                for item in self.accounts
            ]
        }
        self.manager.load_accounts(payload, no_login=no_login)

    def get_adapter_for_task(self, task: dict, *, allow_inactive: bool = False):
        return self.manager.get_adapter_for_task(task, allow_inactive=allow_inactive)

    def get_default_adapter(self):
        return self.manager.get_default_adapter()

    def init_for_tasks(self, tasks: list[dict]) -> None:
        self.manager.init_adapters_for_tasks(tasks)

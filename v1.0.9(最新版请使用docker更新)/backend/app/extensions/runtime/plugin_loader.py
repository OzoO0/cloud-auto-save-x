from __future__ import annotations

import importlib
import json
import platform
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.plugin_config import PluginConfig
from app.models.plugin_definition import PluginDefinition


@dataclass(slots=True)
class PluginDescriptor:
    plugin_key: str
    module_name: str
    source_type: str
    version: str | None
    default_config: dict[str, Any]
    default_task_config: dict[str, Any]
    config_fields: list[dict[str, Any]]
    task_config_fields: list[dict[str, Any]]
    plugin_class: type | None


class PluginLoader:
    def __init__(self) -> None:
        self.plugins_dir = Path(__file__).resolve().parents[1] / 'plugins'

    def _priority_modules(self) -> list[str]:
        priority_path = self.plugins_dir / '_priority.json'
        if not priority_path.exists():
            return []
        try:
            payload = json.loads(priority_path.read_text(encoding='utf-8'))
        except json.JSONDecodeError:
            return []
        return [str(item) for item in payload if isinstance(item, str)]

    def _discover_module_names(self) -> list[tuple[str, str]]:
        sys_ext = 'pyd' if platform.system() == 'Windows' else 'so'
        pairs: list[tuple[str, str]] = []
        for path in self.plugins_dir.iterdir():
            if path.name.startswith('_'):
                continue
            if path.suffix == '.py':
                pairs.append((path.stem, 'py'))
            elif path.suffix == f'.{sys_ext}':
                pairs.append((path.stem, 'so'))
        priority = self._priority_modules()
        ordered = sorted(pairs, key=lambda item: (priority.index(item[0]) if item[0] in priority else len(priority) + 1, item[0]))
        return ordered

    def discover(self) -> list[PluginDescriptor]:
        items: list[PluginDescriptor] = []
        for module_name, source_type in self._discover_module_names():
            try:
                module = importlib.import_module(f'app.extensions.plugins.{module_name}')
            except Exception:
                continue
            class_name = module_name.capitalize()
            plugin_class = getattr(module, class_name, None)
            if plugin_class is None:
                continue
            default_config = getattr(plugin_class, 'default_config', {}) or {}
            default_task_config = getattr(plugin_class, 'default_task_config', {}) or {}
            config_comments = self._extract_dict_comments(getattr(module, '__file__', None), 'default_config')
            task_comments = self._extract_dict_comments(getattr(module, '__file__', None), 'default_task_config')
            plugin_key = getattr(plugin_class, 'plugin_name', None) or module_name
            version = getattr(plugin_class, 'plugin_version', None)
            items.append(
                PluginDescriptor(
                    plugin_key=str(plugin_key),
                    module_name=module_name,
                    source_type=source_type,
                    version=version,
                    default_config=dict(default_config),
                    default_task_config=dict(default_task_config),
                    config_fields=self._build_field_descriptors(default_config, config_comments),
                    task_config_fields=self._build_field_descriptors(default_task_config, task_comments),
                    plugin_class=plugin_class,
                )
            )
        return items

    def _extract_dict_comments(self, module_file: str | None, variable_name: str) -> dict[str, str]:
        if not module_file or not str(module_file).endswith('.py'):
            return {}
        path = Path(module_file)
        if not path.exists():
            return {}
        lines = path.read_text(encoding='utf-8').splitlines()
        start = None
        brace_balance = 0
        result: dict[str, str] = {}
        assign_pattern = re.compile(rf'^\s*{re.escape(variable_name)}\s*=\s*\{{')
        field_pattern = re.compile(r'^\s*[\'"](?P<key>[^\'"]+)[\'"]\s*:\s*.*?(?:#\s*(?P<comment>.+))?$')
        for index, line in enumerate(lines):
            if start is None:
                if assign_pattern.search(line):
                    start = index
                    brace_balance = line.count('{') - line.count('}')
                continue
            brace_balance += line.count('{') - line.count('}')
            match = field_pattern.search(line)
            if match:
                key = match.group('key')
                comment = (match.group('comment') or '').strip()
                if comment:
                    result[key] = comment
            if brace_balance <= 0:
                break
        return result

    def _build_field_descriptors(
        self,
        config: dict[str, Any],
        comments: dict[str, str],
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for key, value in config.items():
            description = comments.get(key, '').strip()
            if not description and str(key).lower().startswith('tips') and isinstance(value, str):
                description = value.strip()
            items.append(
                {
                    'key': str(key),
                    'default': value,
                    'description': description,
                    'input_type': self._infer_input_type(key, value),
                    'secret': self._is_secret_field(key),
                }
            )
        return items

    @staticmethod
    def _infer_input_type(key: str, value: Any) -> str:
        key_lower = str(key).lower()
        if isinstance(value, bool):
            return 'switch'
        if isinstance(value, int) and not isinstance(value, bool):
            return 'number'
        if any(token in key_lower for token in ('cookie', 'json', 'headers', 'token', 'password')):
            return 'textarea'
        return 'text'

    @staticmethod
    def _is_secret_field(key: str) -> bool:
        key_lower = str(key).lower()
        return any(token in key_lower for token in ('cookie', 'token', 'password', 'secret'))


def sync_plugin_definitions(db: Session) -> list[PluginDefinition]:
    loader = PluginLoader()
    descriptors = loader.discover()
    existing = {
        item.plugin_key: item
        for item in db.execute(select(PluginDefinition)).scalars().all()
    }
    seen: set[str] = set()
    for order, descriptor in enumerate(descriptors, start=1):
        seen.add(descriptor.plugin_key)
        definition = existing.get(descriptor.plugin_key)
        if definition is None:
            definition = PluginDefinition(
                plugin_key=descriptor.plugin_key,
                module_name=descriptor.module_name,
                source_type=descriptor.source_type,
                version=descriptor.version,
                installed=True,
            )
            db.add(definition)
            db.flush()
        else:
            definition.module_name = descriptor.module_name
            definition.source_type = descriptor.source_type
            definition.version = descriptor.version
            definition.installed = True

        if definition.config is None:
            db.add(
                PluginConfig(
                    plugin_definition_id=definition.id,
                    enabled=True,
                    priority=order,
                    config_json=json.dumps(descriptor.default_config, ensure_ascii=False),
                    default_task_config_json=json.dumps(descriptor.default_task_config, ensure_ascii=False),
                    runtime_status='discovered',
                )
            )
        else:
            if not definition.config.config_json:
                definition.config.config_json = json.dumps(descriptor.default_config, ensure_ascii=False)
            definition.config.default_task_config_json = json.dumps(descriptor.default_task_config, ensure_ascii=False)
            if not definition.config.priority:
                definition.config.priority = order

    for key, definition in existing.items():
        if key not in seen:
            definition.installed = False
            if definition.config is not None and definition.config.runtime_status != 'error':
                definition.config.runtime_status = 'missing'

    db.flush()
    return db.execute(select(PluginDefinition).order_by(PluginDefinition.plugin_key)).scalars().all()

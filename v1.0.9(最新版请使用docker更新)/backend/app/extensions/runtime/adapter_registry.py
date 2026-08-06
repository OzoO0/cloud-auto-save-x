from __future__ import annotations

import json
from typing import Any

from app.extensions.adapters.adapter_factory import AdapterFactory


class AdapterRegistry:
    @staticmethod
    def _adapter_class(drive_type: str):
        return AdapterFactory.ADAPTER_MAP.get(drive_type)

    @classmethod
    def get_drive_type_meta(cls, drive_type: str) -> dict[str, Any]:
        adapter_class = cls._adapter_class(drive_type)
        if adapter_class is None:
            return {
                "code": drive_type,
                "drive_name": drive_type,
                "class_name": "",
                "config_format": "raw",
                "default_config": {"cookie": ""},
                "config_fields": [],
            }
        return {
            "code": drive_type,
            "class_name": adapter_class.__name__,
            **adapter_class.get_config_meta(),
        }

    @staticmethod
    def supported_drive_types() -> list[dict[str, Any]]:
        return [
            AdapterRegistry.get_drive_type_meta(key)
            for key in AdapterFactory.ADAPTER_MAP.keys()
        ]

    @staticmethod
    def detect_drive_type(url: str) -> str | None:
        return AdapterFactory.get_drive_type_by_url(url)

    @classmethod
    def deserialize_cookie(cls, drive_type: str, cookie: str | None) -> dict[str, Any]:
        meta = cls.get_drive_type_meta(drive_type)
        config = dict(meta.get("default_config", {}) or {})
        raw_cookie = str(cookie or "").strip()
        if not raw_cookie:
            return config
        if meta.get("config_format") == "kv":
            parsed: dict[str, Any] = {}
            for chunk in raw_cookie.split(";"):
                chunk = chunk.strip()
                if not chunk or "=" not in chunk:
                    continue
                key, value = chunk.split("=", 1)
                parsed[key.strip()] = value.strip()
            for key, default_value in config.items():
                if key not in parsed:
                    continue
                if isinstance(default_value, bool):
                    config[key] = str(parsed[key]).strip().lower() in ("1", "true", "yes", "on")
                elif isinstance(default_value, int) and not isinstance(default_value, bool):
                    try:
                        config[key] = int(parsed[key])
                    except ValueError:
                        config[key] = parsed[key]
                else:
                    config[key] = parsed[key]
            for key, value in parsed.items():
                if key not in config:
                    config[key] = value
            return config
        primary_key = cls._primary_config_key(meta)
        config[primary_key] = raw_cookie
        return config

    @classmethod
    def normalize_config(cls, drive_type: str, config: dict[str, Any] | None) -> dict[str, Any]:
        meta = cls.get_drive_type_meta(drive_type)
        result = dict(meta.get("default_config", {}) or {})
        for key, value in (config or {}).items():
            result[key] = value
        return result

    @classmethod
    def parse_config_json(cls, drive_type: str, config_json: str | None, cookie: str | None = None) -> dict[str, Any]:
        if config_json:
            try:
                payload = json.loads(config_json)
                if isinstance(payload, dict):
                    return cls.normalize_config(drive_type, payload)
            except json.JSONDecodeError:
                pass
        return cls.deserialize_cookie(drive_type, cookie)

    @classmethod
    def serialize_config(cls, drive_type: str, config: dict[str, Any] | None) -> str:
        meta = cls.get_drive_type_meta(drive_type)
        payload = cls.normalize_config(drive_type, config)
        if meta.get("config_format") == "kv":
            parts: list[str] = []
            for key, value in payload.items():
                if not cls._keep_value(value):
                    continue
                parts.append(f"{key}={str(value).strip() if not isinstance(value, bool) else str(value)}")
            return ";".join(parts)
        primary_key = cls._primary_config_key(meta)
        return str(payload.get(primary_key, "") or "").strip()

    @staticmethod
    def _primary_config_key(meta: dict[str, Any]) -> str:
        fields = meta.get("config_fields") or []
        if fields and fields[0].get("key"):
            return str(fields[0]["key"])
        defaults = meta.get("default_config") or {}
        if defaults:
            return next(iter(defaults.keys()))
        return "cookie"

    @staticmethod
    def _keep_value(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, int) and not isinstance(value, bool):
            return True
        return str(value or "").strip() != ""

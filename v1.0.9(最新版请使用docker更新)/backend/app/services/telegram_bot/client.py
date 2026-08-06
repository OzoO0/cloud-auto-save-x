from __future__ import annotations

import json
import logging
from typing import Any

import requests

from app.services.telegram_bot.config import TelegramBotConfig


logger = logging.getLogger(__name__)


class TelegramBotClient:
    def __init__(self, config: TelegramBotConfig):
        self.config = config
        self.base_url = f"{self.config.api_host}/bot{self.config.token}"
        self._session = requests.Session()

    def _proxies(self) -> dict[str, str] | None:
        if not (self.config.proxy_host and self.config.proxy_port):
            return None
        proxy_url = f"http://{self.config.proxy_host}:{self.config.proxy_port}"
        if self.config.proxy_auth:
            proxy_url = f"http://{self.config.proxy_auth}@{self.config.proxy_host}:{self.config.proxy_port}"
        return {"http": proxy_url, "https": proxy_url}

    def _request(
        self,
        method: str,
        api: str,
        *,
        json_body: Any | None = None,
        data: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        timeout: int = 30,
    ) -> dict[str, Any]:
        url = f"{self.base_url}/{api.lstrip('/')}"
        response = self._session.request(
            method=method.upper(),
            url=url,
            json=json_body,
            data=data,
            files=files,
            timeout=timeout,
            proxies=self._proxies(),
        )
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError(f"invalid telegram response: {response.text[:500]}")
        if not payload.get("ok"):
            logger.warning("telegram api error api=%s payload=%s", api, json.dumps(payload, ensure_ascii=False)[:1000])
            description = str(payload.get("description") or "telegram api request failed")
            raise RuntimeError(description)
        return payload

    def get_updates(self, *, offset: int = 0, timeout: int = 20) -> list[dict[str, Any]]:
        payload = self._request("POST", "getUpdates", json_body={"offset": offset, "timeout": timeout, "allowed_updates": ["message", "callback_query"]}, timeout=timeout + 10)
        result = payload.get("result")
        return result if isinstance(result, list) else []

    def set_my_commands(self, commands: list[dict[str, str]]) -> None:
        self._request("POST", "setMyCommands", json_body={"commands": commands}, timeout=20)

    def send_message(
        self,
        *,
        chat_id: int,
        text: str,
        reply_markup: dict[str, Any] | None = None,
        parse_mode: str | None = None,
        disable_web_page_preview: bool = True,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text, "disable_web_page_preview": disable_web_page_preview}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        if parse_mode:
            payload["parse_mode"] = parse_mode
        result = self._request("POST", "sendMessage", json_body=payload, timeout=30)
        return result.get("result") or {}

    def edit_message_text(
        self,
        *,
        chat_id: int,
        message_id: int,
        text: str,
        reply_markup: dict[str, Any] | None = None,
        parse_mode: str | None = None,
        disable_web_page_preview: bool = True,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "disable_web_page_preview": disable_web_page_preview,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        if parse_mode:
            payload["parse_mode"] = parse_mode
        result = self._request("POST", "editMessageText", json_body=payload, timeout=30)
        return result.get("result") or {}

    def delete_message(self, *, chat_id: int, message_id: int) -> None:
        self._request("POST", "deleteMessage", json_body={"chat_id": chat_id, "message_id": message_id}, timeout=20)

    def send_photo(
        self,
        *,
        chat_id: int,
        photo_bytes: bytes,
        filename: str = "image.png",
        caption: str | None = None,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {"chat_id": str(chat_id)}
        if caption:
            data["caption"] = caption
        result = self._request(
            "POST",
            "sendPhoto",
            data=data,
            files={"photo": (filename, photo_bytes)},
            timeout=30,
        )
        return result.get("result") or {}

    def answer_callback_query(self, *, callback_query_id: str, text: str | None = None, show_alert: bool = False) -> None:
        payload: dict[str, Any] = {"callback_query_id": callback_query_id, "show_alert": show_alert}
        if text:
            payload["text"] = text
        self._request("POST", "answerCallbackQuery", json_body=payload, timeout=20)

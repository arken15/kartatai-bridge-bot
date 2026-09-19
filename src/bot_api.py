from __future__ import annotations

import asyncio
import json
import logging
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)


class TelegramBotApi:
    def __init__(self, token: str) -> None:
        self.token = token

    async def send_text(self, chat_id: int, text: str, keyboard: list[list[dict]] | None) -> dict:
        payload: dict = {"chat_id": chat_id, "text": text}
        if keyboard:
            payload["reply_markup"] = {"inline_keyboard": keyboard}
        return await self._call("sendMessage", payload)

    async def edit_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        keyboard: list[list[dict]] | None,
    ) -> dict:
        payload: dict = {"chat_id": chat_id, "message_id": message_id, "text": text}
        if keyboard is not None:
            payload["reply_markup"] = {"inline_keyboard": keyboard}
        return await self._call("editMessageText", payload)

    async def edit_markup(
        self,
        chat_id: int,
        message_id: int,
        keyboard: list[list[dict]] | None,
    ) -> dict:
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "reply_markup": {"inline_keyboard": keyboard or []},
        }
        return await self._call("editMessageReplyMarkup", payload)

    async def _call(self, method: str, payload: dict) -> dict:
        return await asyncio.to_thread(self._call_sync, method, payload)

    def _call_sync(self, method: str, payload: dict) -> dict:
        url = f"https://api.telegram.org/bot{self.token}/{method}"
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            logger.warning("Bot API %s failed: %s", method, raw)
            try:
                return json.loads(raw)
            except Exception:
                return {"ok": False, "description": raw}
        return body

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field

from telethon import TelegramClient
from telethon.tl.custom.message import Message

logger = logging.getLogger(__name__)

URL_PATTERN = re.compile(r"https?://[^\s<>\"]+")


@dataclass
class TeamScreen:
    text: str
    button_rows: list[list[str]]
    links: list[str]
    message_id: int
    entities: list = field(default_factory=list)


class TeamBridge:
    def __init__(
        self,
        client: TelegramClient,
        bot_username: str,
        timeout: int = 20,
    ) -> None:
        self.client = client
        self.bot_username = bot_username.lstrip("@")
        self.timeout = timeout
        self.last_message: Message | None = None

    @staticmethod
    def button_rows(message: Message | None) -> list[list[str]]:
        if not message or not message.buttons:
            return []
        return [[button.text or "" for button in row] for row in message.buttons]

    @staticmethod
    def extract_links(text: str | None) -> list[str]:
        if not text:
            return []
        return URL_PATTERN.findall(text)

    def button_label(self, row: int, col: int) -> str:
        rows = self.last_message.buttons if self.last_message else None
        if not rows or row >= len(rows) or col >= len(rows[row]):
            return ""
        return rows[row][col].text or ""

    def _normalize(self, value: str) -> str:
        return (value or "").lower().replace("ё", "е").strip()

    def _find_button(self, candidates: list[str]) -> tuple[int, int] | None:
        rows = self.last_message.buttons if self.last_message else None
        if not rows:
            return None
        normalized = [self._normalize(item) for item in candidates]
        indexed: list[tuple[int, int, str]] = []
        for row_idx, row in enumerate(rows):
            for col_idx, button in enumerate(row):
                indexed.append((row_idx, col_idx, self._normalize(button.text or "")))

        for candidate in normalized:
            for row_idx, col_idx, text in indexed:
                if text == candidate or text.endswith(candidate):
                    return row_idx, col_idx
        for candidate in normalized:
            if len(candidate) < 4:
                continue
            for row_idx, col_idx, text in indexed:
                if candidate in text:
                    return row_idx, col_idx
        return None

    def _find_next_page(self) -> tuple[int, int] | None:
        rows = self.last_message.buttons if self.last_message else None
        if not rows:
            return None
        for row_idx, row in enumerate(rows):
            for col_idx, button in enumerate(row):
                text = (button.text or "").strip()
                compact = text.replace(" ", "")
                if compact in {"➡", "➡️", "→", "▶️", "▶", "➔"} or (
                    "➡" in text and len(text) <= 4
                ):
                    return row_idx, col_idx
        return None

    def to_screen(self, message: Message) -> TeamScreen:
        text = message.message or message.raw_text or ""
        return TeamScreen(
            text=text,
            button_rows=self.button_rows(message),
            links=self.extract_links(text),
            message_id=message.id,
            entities=list(message.entities or []),
        )

    async def _latest_incoming(self, limit: int = 10) -> Message | None:
        messages = await self.client.get_messages(self.bot_username, limit=limit)
        for message in messages:
            if message and not message.out:
                return message
        return None

    def _changed(self, previous: Message, fresh: Message | None) -> bool:
        if not fresh:
            return False
        if fresh.id != previous.id:
            return True
        if (fresh.message or "") != (previous.message or ""):
            return True
        return self.button_rows(fresh) != self.button_rows(previous)

    async def _wait_update(self, previous: Message, after_id: int) -> Message:
        deadline = asyncio.get_running_loop().time() + self.timeout
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.35)
            latest = await self._latest_incoming()
            if latest and latest.id > after_id:
                return latest
            fresh = await self.client.get_messages(self.bot_username, ids=previous.id)
            if self._changed(previous, fresh):
                return fresh
        latest = await self._latest_incoming()
        if latest:
            return latest
        return previous

    @staticmethod
    def _toast(raw: object) -> str | None:
        if raw is None or isinstance(raw, Message):
            return None
        if hasattr(raw, "buttons") and hasattr(raw, "id"):
            return None
        text = getattr(raw, "message", None)
        return str(text) if text else None

    async def open_start(self) -> TeamScreen:
        sent = await self.client.send_message(self.bot_username, "/start")
        updated = await self._wait_update(sent, after_id=sent.id)
        if updated.id == sent.id:
            incoming = await self._latest_incoming()
            if incoming:
                updated = incoming
        self.last_message = updated
        screen = self.to_screen(updated)
        logger.info(
            "Team screen: %r buttons=%s",
            (screen.text or "")[:120],
            screen.button_rows,
        )
        return screen

    async def click(self, row: int, col: int) -> tuple[TeamScreen, str | None]:
        if self.last_message is None:
            return await self.open_start(), None

        rows = self.last_message.buttons or []
        if row < 0 or row >= len(rows) or col < 0 or col >= len(rows[row]):
            raise RuntimeError("Эта кнопка уже неактуальна. Нажми /start")

        previous = self.last_message
        raw = await previous.click(row, col)
        toast = self._toast(raw)

        if isinstance(raw, Message) and getattr(raw, "id", None):
            self.last_message = raw
            return self.to_screen(raw), toast

        updated = await self._wait_update(previous, after_id=previous.id)
        self.last_message = updated
        return self.to_screen(updated), toast

    async def click_named(
        self,
        candidates: list[str],
        *,
        paginate: bool = True,
    ) -> tuple[TeamScreen, str | None]:
        position = self._find_button(candidates)
        if position is None and paginate:
            for _ in range(8):
                nxt = self._find_next_page()
                if nxt is None:
                    break
                await self.click(*nxt)
                await asyncio.sleep(0.7)
                position = self._find_button(candidates)
                if position is not None:
                    break
        if position is None:
            raise RuntimeError(
                f"Кнопка не найдена: {candidates}. "
                f"Доступно: {self.button_rows(self.last_message)}"
            )
        screen, toast = await self.click(*position)
        await asyncio.sleep(0.5)
        return screen, toast

    async def follow_path(self, steps: list[list[str]]) -> TeamScreen:
        if self.last_message is None:
            await self.open_start()
        screen = self.to_screen(self.last_message)
        for step in steps:
            screen, _toast = await self.click_named(step)
            logger.info("Nav step %s -> %r", step, (screen.text or "")[:80])
        return screen

    async def send_text(self, text: str) -> TeamScreen:
        sent = await self.client.send_message(self.bot_username, text)
        return await self._after_outgoing(sent)

    async def send_file(self, path: str, caption: str = "") -> TeamScreen:
        previous_timeout = self.timeout
        self.timeout = max(self.timeout, 40)
        try:
            sent = await self.client.send_file(
                self.bot_username,
                path,
                caption=caption or None,
            )
            return await self._after_outgoing(sent)
        finally:
            self.timeout = previous_timeout

    async def _after_outgoing(self, sent: Message) -> TeamScreen:
        previous = self.last_message or sent
        updated = await self._wait_update(previous, after_id=max(previous.id, sent.id))
        if updated.out:
            incoming = await self._latest_incoming()
            if incoming:
                updated = incoming
        self.last_message = updated
        return self.to_screen(updated)

    def current_screen(self) -> TeamScreen | None:
        if self.last_message is None:
            return None
        return self.to_screen(self.last_message)

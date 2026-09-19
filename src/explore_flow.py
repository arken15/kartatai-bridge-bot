"""Dump the live team bot start screen. Run: python -m src.explore_flow"""

from __future__ import annotations

import asyncio
import logging

from telethon import TelegramClient

from src.config import load_settings
from src.team_bridge import TeamBridge

logging.basicConfig(level=logging.INFO)


async def main() -> None:
    settings = load_settings()
    client = TelegramClient(
        str(settings.session_path),
        settings.api_id,
        settings.api_hash,
    )
    await client.start(phone=settings.phone)
    bridge = TeamBridge(client=client, bot_username=settings.team_bot_username)
    screen = await bridge.open_start()
    print("=== /start ===")
    print(screen.text)
    print("Buttons:", screen.button_rows)
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())

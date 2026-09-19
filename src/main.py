"""Run client bot + Telethon userbot bridge."""

from __future__ import annotations

import asyncio
import logging
import sys

from telethon import TelegramClient

from src.bootstrap import bootstrap_sessions
from src.client_bot import run_client_bot
from src.config import load_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def connect_userbot(settings) -> TelegramClient | None:
    user_client = TelegramClient(
        str(settings.session_path),
        settings.api_id,
        settings.api_hash,
    )
    await user_client.connect()

    if not await user_client.is_user_authorized():
        logger.error(
            "Userbot не авторизован. Сначала выполни:\n"
            "  python -m src.auth_userbot"
        )
        return None

    me = await user_client.get_me()
    logger.info("Userbot authorized as %s (@%s)", me.first_name, me.username or "-")
    return user_client


async def main() -> None:
    settings = load_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    bootstrap_sessions(settings.session_dir, settings.session_name)
    user_client = await connect_userbot(settings)

    try:
        await run_client_bot(settings, user_client)
    finally:
        if user_client is not None:
            await user_client.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)

"""One-time Telethon authorization. Run: python -m src.auth_userbot"""

from __future__ import annotations

import asyncio
import sys

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

from src.config import load_settings


async def main() -> None:
    settings = load_settings()
    client = TelegramClient(
        str(settings.session_path),
        settings.api_id,
        settings.api_hash,
    )

    await client.connect()
    if await client.is_user_authorized():
        me = await client.get_me()
        print(f"Already authorized as {me.first_name} (@{me.username or 'no username'})")
        await client.disconnect()
        return

    print(f"Sending login code to {settings.phone} ...")
    await client.send_code_request(settings.phone)
    code = input("Enter the Telegram code from SMS/Telegram: ").strip()

    try:
        await client.sign_in(settings.phone, code)
    except SessionPasswordNeededError:
        password = input("2FA password: ").strip()
        await client.sign_in(password=password)

    me = await client.get_me()
    print(f"Authorized as {me.first_name} (@{me.username or 'no username'})")
    await client.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)

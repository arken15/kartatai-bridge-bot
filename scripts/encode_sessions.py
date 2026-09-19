"""Encode local Telethon session files to base64 for cloud env vars."""

from __future__ import annotations

import base64
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SESSION_NAME = "kartatai_userbot"


def main() -> None:
    out = ROOT / "deploy.env"
    out.write_text("", encoding="utf-8")
    files = [
        (ROOT / f"{SESSION_NAME}.session", "TELEGRAM_SESSION_B64"),
        (ROOT / f"{SESSION_NAME}_client_bot.session", "TELEGRAM_CLIENT_SESSION_B64"),
    ]
    for path, env_name in files:
        if not path.exists():
            print(f"SKIP {env_name}: {path.name} not found", file=sys.stderr)
            continue
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        print(f"{env_name} ({len(encoded)} chars)")
        with out.open("a", encoding="utf-8") as fh:
            fh.write(f"{env_name}={encoded}\n")
        print(f"  -> appended to {out.name}")


if __name__ == "__main__":
    main()

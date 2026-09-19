from __future__ import annotations

import base64
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def bootstrap_sessions(session_dir: Path, session_name: str) -> None:
    """Write Telethon session files from base64 env vars (for cloud deploy)."""
    session_dir.mkdir(parents=True, exist_ok=True)
    mapping = {
        f"{session_name}.session": "TELEGRAM_SESSION_B64",
        f"{session_name}_client_bot.session": "TELEGRAM_CLIENT_SESSION_B64",
    }
    for filename, env_key in mapping.items():
        raw = os.getenv(env_key, "").strip()
        if not raw:
            continue
        target = session_dir / filename
        if target.exists():
            logger.info("Session already present: %s", filename)
            continue
        try:
            target.write_bytes(base64.b64decode(raw))
            logger.info("Session restored from env: %s", filename)
        except Exception:
            logger.exception("Failed to restore session %s", filename)

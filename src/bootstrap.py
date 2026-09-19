from __future__ import annotations

import base64
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def bootstrap_sessions(session_dir: Path, session_name: str) -> None:
    """Restore Telethon sessions from env before either client opens them."""
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
        try:
            content = base64.b64decode(raw, validate=True)
            if not content.startswith(b"SQLite format 3\x00"):
                raise ValueError(f"{env_key} is not a valid Telethon SQLite session")

            # A first deploy without the B64 variables creates empty session
            # databases on the persistent disk. Always replace those stale
            # files when an explicit session value is configured.
            for suffix in ("-journal", "-wal", "-shm"):
                Path(f"{target}{suffix}").unlink(missing_ok=True)
            temporary = target.with_name(f"{target.name}.tmp")
            temporary.write_bytes(content)
            temporary.replace(target)
            logger.info("Session restored from env: %s", filename)
        except Exception:
            logger.exception("Failed to restore session %s", filename)

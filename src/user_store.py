from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)


class UserStore:
    """Stores each client's own links. Never mix between users."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._data: dict[str, list[dict]] = self._load()

    def _load(self) -> dict[str, list[dict]]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return raw
        except Exception:
            logger.exception("Failed to read user store")
        return {}

    def _save(self) -> None:
        with self._lock:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.path)

    def add_link(self, user_id: int, link: str) -> None:
        with self._lock:
            key = str(user_id)
            items = self._data.setdefault(key, [])
            if any(item.get("link") == link for item in items):
                return
            items.append({"ts": int(time.time()), "link": link})
        self._save()

    def links(self, user_id: int) -> list[str]:
        with self._lock:
            return [str(item["link"]) for item in self._data.get(str(user_id), []) if item.get("link")]

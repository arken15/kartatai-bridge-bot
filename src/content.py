from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)


class ContentStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._data: dict = self._load()

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return raw
        except Exception:
            logger.exception("Failed to read content store")
        return {}

    def _save(self) -> None:
        with self._lock:
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary.replace(self.path)

    def manual_text(self) -> str:
        with self._lock:
            return str(self._data.get("manual_text") or "")

    def set_manual(self, text: str, admin_id: int) -> None:
        cleaned = text.strip()
        if not cleaned:
            raise ValueError("Пустой мануал")
        if len(cleaned) > 4000:
            raise ValueError("Мануал длиннее 4000 символов")
        with self._lock:
            self._data["manual_text"] = cleaned
            self._data["manual_updated_by"] = int(admin_id)
            self._data["manual_updated_at"] = int(time.time())
        self._save()

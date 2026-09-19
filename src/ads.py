from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class StoredAd:
    ad_id: str
    name: str
    ts: int
    user_id: int
    deleted: bool = False


class AdStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._data: list[dict] = self._load()

    def _load(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                return raw
        except Exception:
            logger.exception("Failed to read ads store")
        return []

    def _save(self) -> None:
        with self._lock:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.path)

    def add(self, user_id: int, name: str, ad_id: str) -> None:
        with self._lock:
            for item in self._data:
                if ad_id and item.get("ad_id") == ad_id and not item.get("deleted"):
                    return
            self._data.append(
                {
                    "ad_id": ad_id,
                    "name": name,
                    "ts": int(time.time()),
                    "user_id": int(user_id),
                    "deleted": False,
                }
            )
        self._save()

    def stale(self, max_age_sec: float) -> list[StoredAd]:
        now = time.time()
        result: list[StoredAd] = []
        with self._lock:
            items = list(self._data)
        for item in items:
            if item.get("deleted"):
                continue
            if now - float(item.get("ts", now)) < max_age_sec:
                continue
            result.append(
                StoredAd(
                    ad_id=str(item.get("ad_id") or ""),
                    name=str(item.get("name") or ""),
                    ts=int(item.get("ts") or 0),
                    user_id=int(item.get("user_id") or 0),
                )
            )
        return result

    def mark_deleted(self, ad_id: str = "", name: str = "") -> None:
        changed = False
        with self._lock:
            for item in self._data:
                if item.get("deleted"):
                    continue
                if ad_id and item.get("ad_id") == ad_id:
                    item["deleted"] = True
                    changed = True
                elif name and item.get("name") == name:
                    item["deleted"] = True
                    changed = True
        if changed:
            self._save()

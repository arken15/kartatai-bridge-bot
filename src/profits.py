from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

TZ = timezone(timedelta(hours=3))


@dataclass(frozen=True)
class ProfitSlice:
    count: int
    usd: float


@dataclass(frozen=True)
class ProfitSummary:
    today: ProfitSlice
    week: ProfitSlice
    month: ProfitSlice
    all_time: ProfitSlice


class ProfitStore:
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
            logger.exception("Failed to read profits store")
        return {}

    def _save(self) -> None:
        with self._lock:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.path)

    def add(self, user_id: int, usd: float, count: int, admin_id: int) -> None:
        with self._lock:
            key = str(user_id)
            self._data.setdefault(key, []).append(
                {
                    "ts": int(datetime.now(TZ).timestamp()),
                    "usd": float(usd),
                    "count": int(count),
                    "admin_id": int(admin_id),
                }
            )
        self._save()

    def _slice(self, items: list[dict], start_ts: int | None = None) -> ProfitSlice:
        total_count = 0
        total_usd = 0.0
        for item in items:
            if start_ts is not None and int(item.get("ts", 0)) < start_ts:
                continue
            total_count += int(item.get("count", 0))
            total_usd += float(item.get("usd", 0))
        return ProfitSlice(count=total_count, usd=total_usd)

    def summary(self, user_id: int) -> ProfitSummary:
        with self._lock:
            items = list(self._data.get(str(user_id), []))
        now = datetime.now(TZ)
        today_start = int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        week_start_date = now.date() - timedelta(days=now.weekday())
        week_start = int(datetime.combine(week_start_date, datetime.min.time(), TZ).timestamp())
        month_start = int(now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp())
        return ProfitSummary(
            today=self._slice(items, today_start),
            week=self._slice(items, week_start),
            month=self._slice(items, month_start),
            all_time=self._slice(items),
        )

    def all_users(self) -> list[int]:
        return [int(key) for key in self._data.keys() if key.isdigit()]

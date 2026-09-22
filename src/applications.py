from __future__ import annotations

import json
import logging
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

QUESTIONS = (
    "1/4. Какой ваш опыт работы?",
    "2/4. Сколько часов в день вы готовы уделять работе?",
    "3/4. Имели ли вы опыт раньше по этому направлению? Если да, то какой?",
)
PHOTO_QUESTION = (
    "4/4. Если есть профиты — приложите фото.\n"
    "Если фото нет, нажмите «Пропустить»."
)


@dataclass(frozen=True)
class Application:
    user_id: int
    username: str
    display_name: str
    status: str
    answers: tuple[str, str, str]
    photo_path: str
    created_at: int
    decided_by: int | None
    decided_at: int | None

    def text(self) -> str:
        identity = f"@{self.username}" if self.username else "без username"
        if self.display_name:
            identity += f" ({self.display_name})"
        photo = "приложено" if self.photo_path else "не приложено"
        return (
            "🆕 ЗАЯВКА\n\n"
            f"ID: {self.user_id}\n"
            f"Профиль: {identity}\n\n"
            f"1. Опыт работы:\n{self.answers[0] or '—'}\n\n"
            f"2. Часов в день:\n{self.answers[1] or '—'}\n\n"
            f"3. Опыт по направлению:\n{self.answers[2] or '—'}\n\n"
            f"4. Профиты: {photo}"
        )


def decision_keyboard(user_id: int) -> list[list[dict]]:
    return [[
        {"text": "✅ Принять", "callback_data": f"app:ok:{user_id}", "style": "success"},
        {"text": "❌ Отказать", "callback_data": f"app:no:{user_id}", "style": "danger"},
    ]]


class ApplicationStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.photo_dir = path.parent / "application_photos"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.photo_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._data: dict[str, dict] = self._load()

    def _load(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return raw
        except Exception:
            logger.exception("Failed to read applications")
        return {}

    def _save(self) -> None:
        with self._lock:
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary.replace(self.path)

    def _record(self, user_id: int) -> Application | None:
        item = self._data.get(str(user_id))
        if not item:
            return None
        answers = item.get("answers") or ["", "", ""]
        padded = [str(answers[index]) if index < len(answers) else "" for index in range(3)]
        decided_by = item.get("decided_by")
        return Application(
            user_id=user_id,
            username=str(item.get("username") or ""),
            display_name=str(item.get("display_name") or ""),
            status=str(item.get("status") or "draft"),
            answers=(padded[0], padded[1], padded[2]),
            photo_path=str(item.get("photo_path") or ""),
            created_at=int(item.get("created_at") or 0),
            decided_by=int(decided_by) if decided_by else None,
            decided_at=int(item["decided_at"]) if item.get("decided_at") else None,
        )

    def get(self, user_id: int) -> Application | None:
        with self._lock:
            return self._record(user_id)

    def is_approved(self, user_id: int) -> bool:
        application = self.get(user_id)
        return application is not None and application.status == "approved"

    def count(self, status: str) -> int:
        with self._lock:
            return sum(1 for item in self._data.values() if item.get("status") == status)

    def pending(self) -> list[Application]:
        with self._lock:
            ids = [
                int(key)
                for key, item in self._data.items()
                if key.isdigit() and item.get("status") == "pending"
            ]
        return [application for user_id in sorted(ids) if (application := self.get(user_id))]

    def ensure_approved(self, user_id: int) -> None:
        with self._lock:
            if str(user_id) in self._data:
                return
            now = int(time.time())
            self._data[str(user_id)] = {
                "status": "approved",
                "answers": ["", "", ""],
                "photo_path": "",
                "username": "",
                "display_name": "",
                "created_at": now,
                "decided_at": now,
                "decided_by": 0,
            }
        self._save()

    def start(
        self,
        user_id: int,
        *,
        username: str = "",
        display_name: str = "",
    ) -> Application:
        with self._lock:
            current = self._data.get(str(user_id))
            if current and current.get("status") == "pending":
                record = self._record(user_id)
                assert record is not None
                return record
            self._data[str(user_id)] = {
                "status": "draft",
                "answers": ["", "", ""],
                "photo_path": "",
                "username": username,
                "display_name": display_name,
                "created_at": int(time.time()),
                "decided_by": None,
                "decided_at": None,
            }
        self._save()
        record = self.get(user_id)
        assert record is not None
        return record

    def set_answer(self, user_id: int, index: int, text: str) -> None:
        if index < 0 or index > 2:
            raise IndexError(index)
        with self._lock:
            item = self._data.get(str(user_id))
            if not item or item.get("status") != "draft":
                raise RuntimeError("Анкета не начата")
            answers = list(item.get("answers") or ["", "", ""])
            while len(answers) < 3:
                answers.append("")
            answers[index] = text.strip()
            item["answers"] = answers[:3]
        self._save()

    def attach_photo(self, user_id: int, source: Path) -> str:
        target = self.photo_dir / f"{user_id}{source.suffix.lower() or '.jpg'}"
        shutil.copyfile(source, target)
        with self._lock:
            item = self._data.get(str(user_id))
            if not item or item.get("status") != "draft":
                raise RuntimeError("Анкета не начата")
            item["photo_path"] = str(target)
        self._save()
        return str(target)

    def submit(self, user_id: int) -> Application:
        with self._lock:
            item = self._data.get(str(user_id))
            if not item or item.get("status") != "draft":
                raise RuntimeError("Анкета не начата")
            answers = item.get("answers") or []
            if len(answers) < 3 or not all(str(answer).strip() for answer in answers[:3]):
                raise RuntimeError("Анкета заполнена не до конца")
            item["status"] = "pending"
            item["created_at"] = int(time.time())
        self._save()
        record = self.get(user_id)
        assert record is not None
        return record

    def discard_draft(self, user_id: int) -> None:
        with self._lock:
            item = self._data.get(str(user_id))
            if not item or item.get("status") != "draft":
                return
            self._data.pop(str(user_id), None)
        self._save()

    def decide(self, user_id: int, status: str, admin_id: int) -> bool:
        if status not in {"approved", "rejected"}:
            raise ValueError(status)
        with self._lock:
            item = self._data.get(str(user_id))
            if not item or item.get("status") != "pending":
                return False
            item["status"] = status
            item["decided_by"] = int(admin_id)
            item["decided_at"] = int(time.time())
        self._save()
        return True

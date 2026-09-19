from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

TRC20_RE = re.compile(r"^T[1-9A-HJ-NP-Za-km-z]{33}$")
BEP20_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")


@dataclass(frozen=True)
class UserWallets:
    user_id: int
    username: str
    display_name: str
    trc20: str
    bep20: str
    updated_at: int


def normalize_network(label: str) -> str | None:
    value = (label or "").lower().replace(" ", "")
    if "trc" in value:
        return "trc20"
    if "bep" in value:
        return "bep20"
    return None


def validate_address(network: str, address: str) -> bool:
    value = address.strip()
    if network == "trc20":
        return bool(TRC20_RE.fullmatch(value))
    if network == "bep20":
        return bool(BEP20_RE.fullmatch(value))
    return False


class WalletStore:
    """Persistent wallets isolated by Telegram user ID."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
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
            logger.exception("Failed to read wallet store")
        return {}

    def _save(self) -> None:
        with self._lock:
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary.replace(self.path)

    def register_user(
        self,
        user_id: int,
        *,
        username: str = "",
        display_name: str = "",
    ) -> None:
        with self._lock:
            item = self._data.setdefault(str(user_id), {})
            changed = False
            if username and item.get("username") != username:
                item["username"] = username
                changed = True
            if display_name and item.get("display_name") != display_name:
                item["display_name"] = display_name
                changed = True
        if changed:
            self._save()

    def set_address(
        self,
        user_id: int,
        network: str,
        address: str,
        *,
        username: str = "",
        display_name: str = "",
    ) -> None:
        if network not in {"trc20", "bep20"}:
            raise ValueError("Unsupported wallet network")
        with self._lock:
            item = self._data.setdefault(str(user_id), {})
            item[network] = address.strip()
            item["updated_at"] = int(time.time())
            if username:
                item["username"] = username
            if display_name:
                item["display_name"] = display_name
        self._save()

    def get(self, user_id: int) -> UserWallets:
        with self._lock:
            item = dict(self._data.get(str(user_id), {}))
        return UserWallets(
            user_id=user_id,
            username=str(item.get("username") or ""),
            display_name=str(item.get("display_name") or ""),
            trc20=str(item.get("trc20") or ""),
            bep20=str(item.get("bep20") or ""),
            updated_at=int(item.get("updated_at") or 0),
        )

    def all(self) -> list[UserWallets]:
        with self._lock:
            ids = [int(key) for key in self._data if key.isdigit()]
        return [self.get(user_id) for user_id in sorted(ids)]

    def find(self, raw: str) -> UserWallets | None:
        value = raw.strip().lstrip("@").lower()
        if value.isdigit():
            wallets = self.get(int(value))
            return wallets if wallets.username or wallets.trc20 or wallets.bep20 else None
        for wallets in self.all():
            if wallets.username.lower() == value:
                return wallets
        return None

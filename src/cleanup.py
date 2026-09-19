from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from src.ads import AdStore, StoredAd
from src.team_bridge import TeamBridge, TeamScreen

logger = logging.getLogger(__name__)

TZ = timezone(timedelta(hours=3))
NAV_HINTS = (
    "меню",
    "назад",
    "далее",
    "поиск",
    "конструктор",
    "популярн",
    "списком",
    "создать",
    "профит",
    "настрой",
    "информация",
    "подряд",
    "тпшер",
    "связь",
)
DELETE_HINTS = ("удалить", "снять", "деактив", "delete")
CONFIRM_HINTS = ("да", "подтверд", "удалить", "yes")
DATE_RE = re.compile(r"(\d{1,2})[./](\d{1,2})[./](\d{2,4})")
DAYS_RE = re.compile(r"(\d+)\s*(?:дн|день|дня|дней)", re.IGNORECASE)


def _norm(value: str) -> str:
    return (value or "").lower().replace("ё", "е").strip()


def _is_nav(text: str) -> bool:
    value = _norm(text)
    if not value:
        return True
    if value in {"➡", "➡️", "→", "⬅", "⬅️", "◀️", "▶️"}:
        return True
    if re.fullmatch(r"\[?\d+\s*/\s*\d+\]?", value):
        return True
    return any(hint in value for hint in NAV_HINTS)


def _age_days(text: str) -> float | None:
    days = DAYS_RE.search(text)
    if days:
        return float(days.group(1))
    match = DATE_RE.search(text)
    if not match:
        return None
    day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
    if year < 100:
        year += 2000
    try:
        created = datetime(year, month, day, tzinfo=TZ)
    except ValueError:
        return None
    return (datetime.now(TZ) - created).total_seconds() / 86400


def _matches_stale(blob: str, stale: list[StoredAd]) -> StoredAd | None:
    haystack = _norm(blob)
    for ad in stale:
        if ad.ad_id and _norm(ad.ad_id) in haystack:
            return ad
        if ad.name and len(ad.name) > 2 and _norm(ad.name) in haystack:
            return ad
    return None


class AdCleaner:
    def __init__(self, bridge: TeamBridge, store: AdStore, max_days: int = 3) -> None:
        self.bridge = bridge
        self.store = store
        self.max_days = max_days

    def _should_delete(self, screen: TeamScreen, button_text: str, stale: list[StoredAd]) -> StoredAd | bool:
        blob = f"{screen.text}\n{button_text}"
        age = _age_days(screen.text)
        matched = _matches_stale(blob, stale)
        if age is not None and age >= self.max_days:
            return matched or True
        if matched:
            return matched
        return False

    async def _open_ads(self) -> TeamScreen:
        await self.bridge.open_start()
        screen, _toast = await self.bridge.click_named(["объявления", "объявление"])
        if self.bridge._find_button(["мои объявления", "моих объявлен"]):
            screen, _toast = await self.bridge.click_named(["мои объявления", "моих объявлен"])
        logger.info("Ads screen: %r buttons=%s", (screen.text or "")[:200], screen.button_rows)
        return screen

    async def _try_delete(self) -> bool:
        if self.bridge._find_button(list(DELETE_HINTS)):
            await self.bridge.click_named(list(DELETE_HINTS), paginate=False)
            if self.bridge._find_button(list(CONFIRM_HINTS)):
                await self.bridge.click_named(list(CONFIRM_HINTS), paginate=False)
            return True
        return False

    async def _go_back(self) -> None:
        if self.bridge._find_button(["назад", "меню"]):
            await self.bridge.click_named(["назад", "меню"], paginate=False)

    async def run(self) -> str:
        stale = self.store.stale(self.max_days * 86400)
        deleted = 0
        skipped = 0
        screen = await self._open_ads()

        seen: set[str] = set()
        for _page in range(12):
            rows = screen.button_rows
            targets = [
                (row_idx, col_idx, text)
                for row_idx, row in enumerate(rows)
                for col_idx, text in enumerate(row)
                if not _is_nav(text) and text not in seen
            ]
            if not targets:
                nxt = self.bridge._find_next_page()
                if nxt is None:
                    break
                screen, _toast = await self.bridge.click(*nxt)
                continue

            row_idx, col_idx, text = targets[0]
            seen.add(text)
            screen, _toast = await self.bridge.click(row_idx, col_idx)
            decision = self._should_delete(screen, text, stale)
            if decision:
                logger.info("Deleting ad %r", text)
                if await self._try_delete():
                    deleted += 1
                    if isinstance(decision, StoredAd):
                        self.store.mark_deleted(decision.ad_id, decision.name)
                    else:
                        self.store.mark_deleted(name=text)
                else:
                    skipped += 1
                    await self._go_back()
            else:
                skipped += 1
                await self._go_back()
            screen = self.bridge.current_screen() or screen

        try:
            await self.bridge.open_start()
        except Exception:
            logger.exception("Failed to reset after cleanup")

        report = f"удалено {deleted}, пропущено {skipped}, в сторе старых {len(stale)}"
        logger.info("Ad cleanup: %s", report)
        return report

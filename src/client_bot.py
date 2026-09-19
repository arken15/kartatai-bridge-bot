from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from telethon import TelegramClient, events

from src.access import AccessGuard, Lease
from src.ads import AdStore
from src.bot_api import TelegramBotApi
from src.cleanup import AdCleaner
from src.config import ROOT_DIR, Settings
from src.profits import ProfitStore
from src.sanitize import (
    NAVIGATION,
    button_style,
    extract_result_meta,
    is_create_link,
    is_link_result,
    is_profits_button,
    is_settings_screen,
    sanitize_settings_text,
    sanitize_text,
    visible_buttons,
)
from src.team_bridge import TeamBridge, TeamScreen
from src.user_store import UserStore

logger = logging.getLogger(__name__)

NO_USERBOT_TEXT = "⚠️ Бот ещё не готов. Сначала запусти auth.bat, потом start.bat"
STALE_TEXT = "Сессия истекла. Нажми /start — так данные не смешаются с другим человеком."
QUEUE_TEXT = "⏳ Сейчас ссылку создаёт другой человек.\nТы в очереди, подожди. Как освободится — открою чистое меню."
QUEUE_FULL_TEXT = "🚫 Сейчас слишком много людей. Нажми /start через минуту."
QUEUE_TIMEOUT_TEXT = "⏰ Очередь слишком долгая. Нажми /start ещё раз."


@dataclass
class UserState:
    generation: int = 0
    seen_links: set[str] = field(default_factory=set)


def _is_allowed(user_id: int, settings: Settings) -> bool:
    if not settings.allowed_user_ids:
        return True
    return user_id in settings.allowed_user_ids


def _styled_keyboard(screen: TeamScreen, token: str, generation: int) -> list[list[dict]]:
    grouped: dict[int, list[dict]] = {}
    for row_idx, col_idx, text in visible_buttons(screen):
        item = {
            "text": text,
            "callback_data": f"b:{token}:{generation}:{row_idx}:{col_idx}",
        }
        style = button_style(text)
        if style:
            item["style"] = style
        grouped.setdefault(row_idx, []).append(item)
    return [grouped[key] for key in sorted(grouped)]


class ClientBotApp:
    def __init__(
        self,
        settings: Settings,
        bot_client: TelegramClient,
        user_client: TelegramClient | None,
    ) -> None:
        self.settings = settings
        self.bot_client = bot_client
        self.user_client = user_client
        self.bridge = (
            TeamBridge(client=user_client, bot_username=settings.team_bot_username)
            if user_client is not None
            else None
        )
        self.guard = AccessGuard()
        self.op_lock = asyncio.Lock()
        self.states: dict[int, UserState] = {}
        self.store = UserStore(settings.data_dir / "user_links.json")
        self.profits = ProfitStore(settings.data_dir / "profits.json")
        self.ads = AdStore(settings.data_dir / "ads.json")
        self.cleaner = AdCleaner(self.bridge, self.ads, max_days=3) if self.bridge else None
        self.last_cleanup = 0.0
        self.api = TelegramBotApi(settings.client_bot_token)
        self._watchdog_task: asyncio.Task | None = None

    def _is_admin(self, user_id: int) -> bool:
        return self.settings.owner_user_id is not None and user_id == self.settings.owner_user_id

    def _state(self, user_id: int) -> UserState:
        if user_id not in self.states:
            self.states[user_id] = UserState()
        return self.states[user_id]

    @staticmethod
    async def _safe_answer(
        event: events.CallbackQuery.Event,
        text: str = "",
        *,
        alert: bool = False,
    ) -> None:
        try:
            await event.answer(text, alert=alert)
        except Exception:
            logger.debug("callback answer skipped", exc_info=True)

    async def _reset_team(self) -> TeamScreen | None:
        if self.bridge is None:
            return None
        return await self.bridge.open_start()

    async def _acquire(self, user_id: int, notice) -> Lease | None:
        if self.guard.busy_by_other(user_id):
            position = self.guard.queue_position(user_id)
            await notice(f"{QUEUE_TEXT}\nМесто в очереди: {position}")
        try:
            lease, _switched = await self.guard.acquire(user_id)
            return lease
        except OverflowError:
            await notice(QUEUE_FULL_TEXT)
            return None
        except TimeoutError:
            await self.guard.drop_waiter(user_id)
            await notice(QUEUE_TIMEOUT_TEXT)
            return None

    async def _show_screen(
        self,
        chat_id: int,
        user_id: int,
        lease: Lease,
        screen: TeamScreen,
        *,
        callback_event: events.CallbackQuery.Event | None = None,
    ) -> None:
        if not self.guard.matches(user_id, lease.token):
            logger.warning("Drop screen: lease no longer belongs to user=%s", user_id)
            return

        state = self._state(user_id)
        state.generation += 1
        self.guard.touch(user_id, lease.token)

        text = sanitize_text(screen.text)
        if is_settings_screen(screen):
            text = sanitize_settings_text(screen.text)
        text = text or "\u2060"
        keyboard = _styled_keyboard(screen, lease.token, state.generation)

        media_path = await self._download_team_media()
        if media_path:
            try:
                sent = await self.bot_client.send_file(chat_id, media_path, caption=text)
                if sent is not None:
                    await self.api.edit_markup(chat_id, sent.id, keyboard)
            finally:
                Path(media_path).unlink(missing_ok=True)
        elif callback_event is not None:
            result = await self.api.edit_text(chat_id, callback_event.message_id, text, keyboard)
            if not result.get("ok"):
                await self.api.send_text(chat_id, text, keyboard)
        else:
            await self.api.send_text(chat_id, text, keyboard)

        own_links = [link for link in screen.links if link not in state.seen_links]
        if own_links:
            state.seen_links.update(own_links)
            for link in own_links:
                self.store.add_link(user_id, link)
            if is_link_result(screen.text):
                name, ad_id = extract_result_meta(screen.text)
                self.ads.add(user_id, name, ad_id)
            if not self.guard.matches(user_id, lease.token):
                logger.warning("Skip link delivery, user=%s lost lease", user_id)
                return
            if not is_link_result(screen.text):
                await self.bot_client.send_message(chat_id, "\n".join(own_links))

    async def _download_team_media(self) -> str | None:
        if self.bridge is None or self.bridge.last_message is None:
            return None
        message = self.bridge.last_message
        if not (message.photo or message.document or message.video):
            return None
        tmp_dir = self.settings.data_dir / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        return await message.download_media(file=str(tmp_dir))

    @staticmethod
    def _has_media(message) -> bool:
        return bool(message.photo or message.document or message.video)

    def _profits_text(self, user_id: int) -> str:
        stats = self.profits.summary(user_id)

        def line(icon: str, title: str, count: int, usd: float) -> str:
            return f"{icon} {title}: {count} ({usd:.2f}$)"

        return (
            "💵 ПРОФИТЫ\n\n"
            f"{line('💵', 'Сегодня', stats.today.count, stats.today.usd)}\n"
            f"{line('📆', 'Неделя', stats.week.count, stats.week.usd)}\n"
            f"{line('📅', 'Месяц', stats.month.count, stats.month.usd)}\n"
            f"{line('🏦', 'Все время', stats.all_time.count, stats.all_time.usd)}"
        )

    async def _show_profits(
        self,
        chat_id: int,
        user_id: int,
        lease: Lease,
        *,
        callback_event: events.CallbackQuery.Event | None = None,
    ) -> None:
        if not self.guard.matches(user_id, lease.token):
            return
        state = self._state(user_id)
        state.generation += 1
        self.guard.touch(user_id, lease.token)
        keyboard = [[{"text": "↩️ В МЕНЮ", "callback_data": f"p:{lease.token}:back", "style": "primary"}]]
        text = self._profits_text(user_id)
        if callback_event is not None:
            result = await self.api.edit_text(chat_id, callback_event.message_id, text, keyboard)
            if result.get("ok"):
                return
        await self.api.send_text(chat_id, text, keyboard)

    async def _show_cabinet(
        self,
        chat_id: int,
        user_id: int,
        lease: Lease,
        *,
        callback_event: events.CallbackQuery.Event | None = None,
    ) -> None:
        if self.bridge is None:
            return
        if self.bridge.last_message is not None:
            screen = self.bridge.to_screen(self.bridge.last_message)
            await self._show_screen(chat_id, user_id, lease, screen, callback_event=callback_event)
            return
        async with self.op_lock:
            screen = await self._reset_team()
        if screen is not None:
            await self._show_screen(chat_id, user_id, lease, screen, callback_event=callback_event)

    async def _open_onlyfans(self) -> TeamScreen:
        if self.bridge is None:
            raise RuntimeError("Userbot не подключён")
        return await self.bridge.follow_path(NAVIGATION)

    async def _open_menu(self, event: events.NewMessage.Event) -> None:
        if self.bridge is None:
            await event.respond(NO_USERBOT_TEXT)
            return

        user_id = event.sender_id
        if user_id is None or not _is_allowed(user_id, self.settings):
            await event.respond("У вас нет доступа к этому боту.")
            return

        lease = await self._acquire(user_id, event.respond)
        if lease is None:
            return

        async with self.op_lock:
            if not self.guard.matches(user_id, lease.token):
                await event.respond(STALE_TEXT)
                return
            try:
                screen = await self._reset_team()
            except Exception as exc:
                logger.exception("open_start failed")
                await event.respond(f"Не удалось открыть меню:\n{exc}")
                return
        if screen is None:
            return
        await self._show_screen(event.chat_id, user_id, lease, screen)

    async def _on_callback(self, event: events.CallbackQuery.Event) -> None:
        if self.bridge is None:
            await self._safe_answer(event, "Бот не готов", alert=True)
            return

        user_id = event.sender_id
        if user_id is None or not _is_allowed(user_id, self.settings):
            await self._safe_answer(event, "Нет доступа", alert=True)
            return

        raw = (event.data or b"").decode("utf-8", errors="ignore")
        parts = raw.split(":")
        if parts and parts[0] == "p" and len(parts) == 3:
            token, action = parts[1], parts[2]
            if not self.guard.matches(user_id, token):
                await self._safe_answer(event, STALE_TEXT, alert=True)
                return
            lease = self.guard.lease
            if lease is None:
                await self._safe_answer(event, STALE_TEXT, alert=True)
                return
            await self._safe_answer(event)
            if action == "back":
                await self._show_cabinet(event.chat_id, user_id, lease, callback_event=event)
            return

        if len(parts) != 5 or parts[0] != "b":
            await self._safe_answer(event, STALE_TEXT, alert=True)
            return

        try:
            token, generation_raw, row, col = parts[1], int(parts[2]), int(parts[3]), int(parts[4])
        except ValueError:
            await self._safe_answer(event, STALE_TEXT, alert=True)
            return

        if not self.guard.matches(user_id, token):
            await self._safe_answer(event, STALE_TEXT, alert=True)
            return

        state = self._state(user_id)
        if generation_raw != state.generation:
            await self._safe_answer(event, "Меню обновилось, нажми кнопку ещё раз", alert=True)
            return

        lease = self.guard.lease
        if lease is None:
            await self._safe_answer(event, STALE_TEXT, alert=True)
            return

        self.guard.touch(user_id, token)
        label = self.bridge.button_label(row, col)
        if is_profits_button(label):
            await self._safe_answer(event)
            await self._show_profits(event.chat_id, user_id, lease, callback_event=event)
            return

        opening_onlyfans = is_create_link(label)
        if opening_onlyfans:
            await self._safe_answer(event, "Открываю OnlyFans...")

        async with self.op_lock:
            if not self.guard.matches(user_id, token):
                await self._safe_answer(event, STALE_TEXT, alert=True)
                return
            try:
                screen, toast = await self.bridge.click(row, col)
                if opening_onlyfans:
                    screen = await self._open_onlyfans()
                    toast = None
            except Exception as exc:
                logger.exception("click failed")
                await self._safe_answer(event, str(exc)[:180], alert=True)
                return

        if toast:
            await self._safe_answer(event, toast[:180], alert=len(toast) > 40)
        elif not opening_onlyfans:
            await self._safe_answer(event)

        await self._show_screen(event.chat_id, user_id, lease, screen, callback_event=event)

    async def _on_input(self, event: events.NewMessage.Event) -> None:
        if self.bridge is None:
            return
        user_id = event.sender_id
        if user_id is None or not _is_allowed(user_id, self.settings):
            return

        lease = self.guard.lease
        if lease is None or not self.guard.matches(user_id, lease.token):
            if self.guard.busy_by_other(user_id):
                await event.respond(QUEUE_TEXT)
            return

        text = (event.raw_text or "").strip()
        has_media = self._has_media(event.message)
        if not text and not has_media:
            return

        self.guard.touch(user_id, lease.token)
        async with self.op_lock:
            if not self.guard.matches(user_id, lease.token):
                await event.respond(STALE_TEXT)
                return
            try:
                if has_media:
                    tmp_dir = self.settings.data_dir / "tmp"
                    tmp_dir.mkdir(parents=True, exist_ok=True)
                    path = await event.message.download_media(file=str(tmp_dir))
                    if not path:
                        await event.respond("Не смог скачать файл. Пришли фото ещё раз.")
                        return
                    try:
                        logger.info("Forwarding media to team bot: %s", path)
                        screen = await self.bridge.send_file(path, caption=text)
                    finally:
                        Path(path).unlink(missing_ok=True)
                else:
                    screen = await self.bridge.send_text(text)
            except Exception as exc:
                logger.exception("input forward failed")
                await event.respond(f"Ошибка:\n{exc}")
                return
        await self._show_screen(event.chat_id, user_id, lease, screen)

    async def _cancel(self, event: events.NewMessage.Event) -> None:
        user_id = event.sender_id
        if user_id is None:
            return
        lease = self.guard.lease
        if lease and lease.user_id == user_id:
            async with self.op_lock:
                try:
                    await self._reset_team()
                except Exception:
                    logger.exception("cancel reset failed")
            await self.guard.release(user_id, lease.token)
            await event.respond("Сессию закрыл. Тима сброшена, следующий человек получит чистое меню.")
            return
        await self.guard.drop_waiter(user_id)
        await event.respond("Очередь сброшена. Нажми /start когда будешь готов.")

    async def _my_links(self, event: events.NewMessage.Event) -> None:
        user_id = event.sender_id
        if user_id is None or not _is_allowed(user_id, self.settings):
            return
        links = self.store.links(user_id)
        if not links:
            await event.respond("У тебя пока нет своих ссылок.")
            return
        await event.respond("Твои ссылки:\n" + "\n".join(links[-15:]))

    async def _resolve_target(self, raw: str) -> int:
        value = raw.strip().lstrip("@")
        if value.isdigit():
            return int(value)
        entity = await self.bot_client.get_entity(value)
        return int(entity.id)

    async def _cmd_profit(self, event: events.NewMessage.Event) -> None:
        user_id = event.sender_id
        if user_id is None or not self._is_admin(user_id):
            return

        parts = (event.raw_text or "").split()
        if len(parts) < 3:
            await event.respond(
                "Зачислить профит (это не тима, только наш бот):\n"
                "/profit <id или @user> <сумма> [кол-во]\n\n"
                "Примеры:\n"
                "/profit 123456789 12.50\n"
                "/profit @username 12.50 2"
            )
            return

        try:
            target = await self._resolve_target(parts[1])
            usd = float(parts[2].replace(",", "."))
            count = int(parts[3]) if len(parts) >= 4 else 1
        except Exception as exc:
            await event.respond(f"Не понял данные: {exc}")
            return

        self.profits.add(target, usd, count, user_id)
        stats = self.profits.summary(target)
        await event.respond(
            f"✅ Зачислил {count} ({usd:.2f}$) → {target}\n"
            f"🏦 Все время: {stats.all_time.count} ({stats.all_time.usd:.2f}$)"
        )
        try:
            await self.bot_client.send_message(
                target,
                f"💵 Зачислено: {count} ({usd:.2f}$)\n\n{self._profits_text(target)}",
            )
        except Exception:
            await event.respond("Клиент не получил уведомление — пусть сначала нажмёт /start.")

    async def _run_cleanup(self, force: bool = False) -> str:
        if self.cleaner is None or self.bridge is None:
            return "Userbot не готов"
        if not force and time.time() - self.last_cleanup < 3 * 3600:
            return "ещё рано"
        if not self.guard.is_free():
            return "сейчас занято клиентом"
        async with self.op_lock:
            if not self.guard.is_free():
                return "сейчас занято клиентом"
            report = await self.cleaner.run()
            self.last_cleanup = time.time()
            return report

    async def _cmd_cleanup(self, event: events.NewMessage.Event) -> None:
        user_id = event.sender_id
        if user_id is None or not self._is_admin(user_id):
            return
        await event.respond("Чищу старые объявления в тиме (старше 3 дней)...")
        try:
            report = await self._run_cleanup(force=True)
        except Exception as exc:
            logger.exception("cleanup failed")
            await event.respond(f"Ошибка очистки: {exc}")
            return
        await event.respond(f"Готово: {report}")

    async def watchdog(self) -> None:
        while True:
            await asyncio.sleep(5)
            lease = self.guard.expired_lease()
            if lease is None:
                continue
            logger.info("Idle timeout, reset team for user=%s", lease.user_id)
            async with self.op_lock:
                if not self.guard.is_expired():
                    continue
                try:
                    await self._reset_team()
                except Exception:
                    logger.exception("idle reset failed")
            await self.guard.release(lease.user_id, lease.token)

    def register_handlers(self) -> None:
        @self.bot_client.on(events.NewMessage(pattern=r"^/start"))
        async def cmd_start(event: events.NewMessage.Event) -> None:
            await self._open_menu(event)

        @self.bot_client.on(events.NewMessage(pattern=r"^/create"))
        async def cmd_create(event: events.NewMessage.Event) -> None:
            await self._open_menu(event)

        @self.bot_client.on(events.NewMessage(pattern=r"^/cancel"))
        async def cmd_cancel(event: events.NewMessage.Event) -> None:
            await self._cancel(event)

        @self.bot_client.on(events.NewMessage(pattern=r"^/mylinks"))
        async def cmd_mylinks(event: events.NewMessage.Event) -> None:
            await self._my_links(event)

        @self.bot_client.on(events.NewMessage(pattern=r"^/profit"))
        async def cmd_profit(event: events.NewMessage.Event) -> None:
            await self._cmd_profit(event)

        @self.bot_client.on(events.NewMessage(pattern=r"^/cleanup"))
        async def cmd_cleanup(event: events.NewMessage.Event) -> None:
            await self._cmd_cleanup(event)

        @self.bot_client.on(events.CallbackQuery)
        async def on_callback(event: events.CallbackQuery.Event) -> None:
            await self._on_callback(event)

        @self.bot_client.on(events.NewMessage(incoming=True))
        async def on_text(event: events.NewMessage.Event) -> None:
            text = (event.raw_text or "").strip()
            if text.startswith("/"):
                return
            await self._on_input(event)


async def run_client_bot(
    settings: Settings,
    user_client: TelegramClient | None,
) -> None:
    bot_client = TelegramClient(
        str(settings.session_path) + "_client_bot",
        settings.api_id,
        settings.api_hash,
    )
    await bot_client.start(bot_token=settings.client_bot_token)

    app = ClientBotApp(settings, bot_client, user_client)
    app.register_handlers()
    app._watchdog_task = asyncio.create_task(app.watchdog())

    me = await bot_client.get_me()
    logger.info("Client bot started as @%s (id=%s)", me.username or "-", me.id)
    logger.info("Bot is online. Send /start in Telegram.")

    try:
        await bot_client.run_until_disconnected()
    finally:
        if app._watchdog_task:
            app._watchdog_task.cancel()

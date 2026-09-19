# Kartatai Bridge Bot

Посредник между клиентами и закрытой тимой `@KartataiFuturaBot`.

- **Клиентский бот** (Telethon Bot API) — принимает параметры от людей.
- **Userbot** (Telethon) — заходит через твой Telegram-аккаунт и создаёт ссылку в боте тимы.

## Быстрый старт

```powershell
cd C:\Users\user\Projects\kartatai-bridge-bot
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 1. Авторизация userbot (один раз)

```powershell
python -m src.auth_userbot
```

Telegram пришлёт код на номер `+90 548 262 01 72`. Введи его в консоль.

### 2. Проверка навигации по боту тимы

```powershell
python -m src.explore_flow
```

Скрипт пройдёт путь: **создать ссылку → международные → остальное → onlyfans** и покажет кнопки на каждом шаге. Если тексты кнопок отличаются — поправь `config/flow.yaml`.

### 3. Запуск

```powershell
python -m src.main
```

В Telegram открой своего бота → `/create`.

## Настройка

| Файл | Назначение |
|---|---|
| `.env` | API id/hash, телефон, токен бота, доступы |
| `config/flow.yaml` | Путь навигации и поля критериев |

### Критерии

Список полей в `config/flow.yaml` → `criteria`. Каждое поле спрашивается у клиента и отправляется боту тимы по порядку.

Если бот тимы спрашивает **кнопками**, а не текстом:

```yaml
- key: geo
  prompt: "Выбери гео:"
  type: button
```

### Ограничение доступа

В `.env`:

```env
ALLOWED_USER_IDS=111111111,222222222
OWNER_USER_ID=111111111
```

Если `ALLOWED_USER_IDS` пустой — бот открыт для всех.

## Команды бота

- `/start` — открыть кабинет
- `/create` — создать ссылку
- `/cancel` — закрыть текущую сессию
- `/mylinks` — свои созданные ссылки
- `/profit <id/@user> <сумма> [кол-во]` — начислить профит (только админ)
- `/wallets` — кошельки всех клиентов (только админ)
- `/wallets <id/@user>` — кошельки одного клиента (только админ)
- `/cleanup` — удалить старые объявления (только админ)

Кошельки USDT TRC-20 и BEP-20 хранятся локально отдельно для каждого
Telegram `user_id`. Нажатие кнопок кошелька не изменяет общий кошелёк
аккаунта в боте тимы.

## Безопасность

- **Не коммить** `.env` и `*.session`.
- Токен бота и API hash лучше **перевыпустить**, если они светились в чате.
- Userbot работает от твоего личного аккаунта — не давай `.session` файлы никому.

## Если что-то ломается

1. Запусти `python -m src.explore_flow` и сверь тексты кнопок.
2. Обнови `config/flow.yaml`.
3. Добавь недостающие поля в `criteria`.
4. Перезапусти бота и проверь логи.

## Деплой в облако (не Vercel)

**Vercel не подходит** для этого бота: нужен процесс 24/7 с постоянным Telethon-соединением и SQLite-сессиями. Vercel — serverless (функции до ~60 сек), бот там не будет работать.

Используй **Render Background Worker** (или Railway / Fly.io / VPS):

1. Залей репозиторий на GitHub.
2. [render.com](https://render.com) → **New** → **Background Worker** → подключи репо.
3. Render подхватит `render.yaml` и `Dockerfile`.
4. В **Environment** добавь переменные из `.env.example`.
5. Закодируй сессии для первого запуска:
   ```powershell
   python scripts/encode_sessions.py
   ```
   Скопируй `TELEGRAM_SESSION_B64` и `TELEGRAM_CLIENT_SESSION_B64` в env Render.
6. Включи **Persistent Disk** на `/data` (уже в `render.yaml`).
7. Запусти **один** инстанс — несколько копий сломают SQLite-сессии.

### Мульти-клиент

- Один активный клиент на тим-аккаунте, остальные в очереди (до 8).
- Токены в callback-кнопках — старые кнопки не срабатывают.
- Авто-сброс тимы через 90 сек бездействия.
- Данные ссылок и профитов — отдельно по `user_id`.

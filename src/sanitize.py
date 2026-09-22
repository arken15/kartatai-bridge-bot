from __future__ import annotations

import re

from src.team_bridge import TeamScreen

HIDDEN_BUTTONS = (
    "подрядчик",
    "тпшер",
    "обратная связь",
    "конкурс",
    "информация",
    "предыдущий",
    "объявл",
)

SETTINGS_KEEP = (
    "кошел",
    "wallet",
    "usdt",
    "trc",
    "bep",
    "адрес",
    "указ",
    "меню",
    "назад",
    "↩️",
    "в меню",
)

CREATE_LINK_HINTS = ("создать ссылку",)
PROFITS_HINTS = ("профит",)
SETTINGS_HINTS = ("настрой",)
COUNTRY_HINTS = ("выберите страну", "выбери страну")

NAVIGATION = [
    ["международные"],
    ["остальные", "остальное", "прочее", "other"],
    ["onlyfans 1.0", "onlyfans 1", "onlyfans"],
]

URL_RE = re.compile(r"https?://[^\s<>\")\]]+")
NAME_RE = re.compile(r"назван\w*\s*:\s*(.+)", re.IGNORECASE)
PRICE_RE = re.compile(r"цена\s*:\s*(.+)", re.IGNORECASE)
CHECKER_RE = re.compile(r"чекер\s*:\s*(.+)", re.IGNORECASE)
ID_RE = re.compile(r"(?:id|#search)\s*:?\s*(#\S+|\d+)", re.IGNORECASE)
RESULT_HINTS = ("фишинг", "сокращатель", "возврат")
LEVEL_NAME_RE = re.compile(r"уровень\s*:\s*\[([^\]]+)\]", re.IGNORECASE)
PERCENT_RE = re.compile(r"65(?:[.,]\d+)?\s*[%％﹪]")
CONTEST_RE = re.compile(
    r"(конкурс|тикетов|тикет|место\s*:|🍁|🎟|🪇|40,?000)",
    re.IGNORECASE,
)
BOX_RE = re.compile(r"[╭┌├└╰╮┐┘]")
LEVEL_JUNK_RE = re.compile(r"(следующий|сброс)", re.IGNORECASE)
TIER_LINE_RE = re.compile(
    r"^\s*\[[A-Z+]+\].*(USD|%|％|\u2014|-)",
    re.IGNORECASE,
)
INVISIBLE_CHARS = dict.fromkeys(
    map(ord, "\u200b\u200c\u200d\u200e\u200f\u2060\ufeff\u00a0")
)


def _norm(value: str) -> str:
    return (value or "").lower().replace("ё", "е").strip()


def extract_result_meta(text: str) -> tuple[str, str]:
    raw = _strip_invisible(text)
    name = _first_group(NAME_RE, raw)
    ident = _first_group(ID_RE, raw)
    if ident and not ident.startswith("#"):
        ident = f"#{ident}"
    return name, ident


def is_link_result(text: str) -> bool:
    value = _norm(_strip_invisible(text))
    return any(hint in value for hint in RESULT_HINTS)


def _first_group(pattern: re.Pattern, text: str) -> str:
    match = pattern.search(text)
    if not match:
        return ""
    return match.group(1).strip().strip("»").strip()


def format_created_link(text: str) -> str:
    raw = _strip_invisible(text)
    name = _first_group(NAME_RE, raw) or "—"
    price = _first_group(PRICE_RE, raw) or "—"
    checker = _first_group(CHECKER_RE, raw) or "—"
    ident = _first_group(ID_RE, raw)
    if ident and not ident.startswith("#"):
        ident = f"#{ident}"

    phishing = ""
    refund = ""
    short = ""
    section = ""
    for line in raw.splitlines():
        lowered = line.lower()
        if "фишинг" in lowered:
            section = "phish"
        elif "возврат" in lowered:
            section = "refund"
        elif "сокращ" in lowered:
            section = "short"
        urls = URL_RE.findall(line)
        if not urls:
            continue
        url = urls[0]
        if "/refund/" in url:
            refund = url
            continue
        if section == "phish" and not phishing:
            phishing = url
        elif section == "refund" and not refund:
            refund = url
        elif section == "short" and not short:
            short = url

    if not phishing or not refund or not short:
        urls = URL_RE.findall(raw)
        for url in urls:
            if "/refund/" in url and not refund:
                refund = url
            elif (("s55." in url) or ("/short" in url)) and not short:
                short = url
            elif not phishing:
                phishing = url
            elif not short:
                short = url

    lines = [
        f"🗂 Название: {name}",
        f"├ 💵 Цена: {price}",
        f"╰ 🎯 Чекер: {checker}",
        "",
        "╭ 🔗 ФИШИНГ:",
        f"╰ (MAIN) » {phishing or '—'}",
        "",
        "╭ ♻️ ВОЗВРАТ:",
        f"╰ (MAIN) » {refund or '—'}",
        "",
        "╭ ✂️ СОКРАЩАТЕЛЬ:",
        f"╰ (MAIN) » {short or '—'}",
    ]
    if ident:
        lines.append(f"╰ 🉐 ID: {ident}")
    return "\n".join(lines)


def _strip_invisible(value: str) -> str:
    return (value or "").translate(INVISIBLE_CHARS)


def _is_contest_line(line: str) -> bool:
    cleaned = _strip_invisible(line)
    return bool(CONTEST_RE.search(cleaned) or BOX_RE.search(cleaned))


def _cabinet_text(text: str) -> str:
    rank = "NEW"
    match = LEVEL_NAME_RE.search(_strip_invisible(text))
    if match:
        rank = match.group(1).strip() or "NEW"
    return f"🛄 ЛИЧНЫЙ КАБИНЕТ\n\n🚀 УРОВЕНЬ: [{rank}] (45.00%)"


def sanitize_text(text: str) -> str:
    if not text:
        return text

    raw = _strip_invisible(text)
    if is_link_result(raw):
        return format_created_link(raw)
    if "личный кабинет" in raw.lower() or "уровень:" in raw.lower():
        return _cabinet_text(raw)

    kept: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if _is_contest_line(line):
            continue
        if TIER_LINE_RE.search(stripped):
            continue
        if LEVEL_JUNK_RE.search(stripped):
            continue
        kept.append(stripped)

    cleaned = "\n".join(kept)
    cleaned = PERCENT_RE.sub("45.00%", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def button_style(text: str) -> str | None:
    value = _norm(text)
    if any(hint in value for hint in ("создать ссылку", "подтверд", "профит", "onlyfans")):
        return "success"
    if any(hint in value for hint in ("отмен", "удал")):
        return "danger"
    if any(hint in value for hint in ("настрой", "кошел", "usdt", "меню", "назад")):
        return "primary"
    if any(hint in value for hint in ("пропуст", "поиск", "предыдущ")):
        return "primary"
    return None


def _is_hidden_main(text: str) -> bool:
    value = _norm(text)
    return any(hint in value for hint in HIDDEN_BUTTONS)


def _is_settings_keep(text: str) -> bool:
    value = _norm(text)
    return any(hint in value for hint in SETTINGS_KEEP)


def sanitize_settings_text(text: str) -> str:
    cleaned = sanitize_text(text)
    kept = [
        line
        for line in cleaned.splitlines()
        if any(hint in line.lower() for hint in ("кошел", "usdt", "trc", "bep", "адрес", "wallet"))
    ]
    if kept:
        return "\n".join(kept).strip()
    return "💳 Укажи кошелёк USDT TRC20 / BEP20"


def is_create_link(text: str) -> bool:
    value = _norm(text)
    return any(hint in value for hint in CREATE_LINK_HINTS)


def is_profits_button(text: str) -> bool:
    value = _norm(text)
    return any(hint in value for hint in PROFITS_HINTS)


def is_settings_button(text: str) -> bool:
    value = _norm(text)
    return any(hint in value for hint in SETTINGS_HINTS)


def is_country_select(screen: TeamScreen) -> bool:
    blob = _norm(screen.text)
    return any(hint in blob for hint in COUNTRY_HINTS)


def is_main_menu(screen: TeamScreen) -> bool:
    return any(is_create_link(text) for _, _, text in visible_buttons(screen))


def is_settings_screen(screen: TeamScreen) -> bool:
    buttons = " ".join(button for row in screen.button_rows for button in row)
    blob = _norm(f"{screen.text}\n{buttons}")
    if is_create_link(buttons) or is_country_select(screen):
        return False
    return "настрой" in blob or "кошел" in blob or "usdt" in blob


def visible_buttons(screen: TeamScreen) -> list[tuple[int, int, str]]:
    settings = is_settings_screen(screen)
    visible: list[tuple[int, int, str]] = []
    for row_idx, row in enumerate(screen.button_rows):
        for col_idx, text in enumerate(row):
            if _is_hidden_main(text):
                continue
            if settings and not _is_settings_keep(text):
                continue
            visible.append((row_idx, col_idx, text))
    return visible

"""Оформление сообщений бота.

Единый визуальный язык: заголовок с эмодзи, разделитель, моноширинные
блоки со статистикой (в Telegram они выравниваются по колонкам) и
аккуратные подписи.

Разметка Telegram позволяет <b>, <i>, <code>, <pre> — этого достаточно,
чтобы сообщения выглядели как карточки, а не как простыня текста.
"""

from __future__ import annotations

from typing import Iterable, Sequence

DIVIDER = "━━━━━━━━━━━━━━━━━━━━"
THIN = "────────────────────────"

# ширина колонки с подписями в моноширинных блоках
LABEL_WIDTH = 18


def number(value: int | float) -> str:
    """1240 -> '1 240' (с неразрывными пробелами для глаз)."""
    if isinstance(value, float) and not value.is_integer():
        return f"{value:.1f}".replace(".", ",")
    return f"{int(value):,}".replace(",", " ")


def header(emoji: str, title: str, subtitle: str = "") -> str:
    """Заголовок карточки: эмодзи, название, подпись, разделитель."""
    lines = [f"{emoji} <b>{title}</b>"]
    if subtitle:
        lines.append(f"<i>{subtitle}</i>")
    lines.append(DIVIDER)
    return "\n".join(lines)


def section(title: str) -> str:
    """Подзаголовок внутри карточки."""
    return f"\n<b>{title}</b>"


def stats(
    rows: Sequence[tuple[str, str, str]],
    indent: int = 2,
    total: tuple[str, str] | None = None,
) -> str:
    """Моноширинный блок со строками (иконка, подпись, значение).

    Колонки выравниваются по ширине подписи, поэтому значения
    выглядят как в таблице. ``total`` добавляет разделитель и строку
    с итогом.
    """
    if not rows and total is None:
        return ""
    pad = " " * indent
    lines = []
    for icon, label, value in rows:
        icon_part = f"{icon} " if icon else ""
        lines.append(f"{pad}{icon_part}{label:<{LABEL_WIDTH}}{value}")
    if total is not None:
        lines.append(pad + THIN[:LABEL_WIDTH])
        lines.append(f"{pad}{total[0]:<{LABEL_WIDTH}}{total[1]:>0}")
    return "<pre>" + "\n".join(lines) + "</pre>"


def bar(current: int, total: int, width: int = 18) -> str:
    """Прогресс-бар из блоков: '▓▓▓▓░░░░░  42%'."""
    if total <= 0:
        return "░" * width + "   0%"
    filled = max(0, min(width, round(width * current / total)))
    percent = round(100 * current / total)
    return f"{'▓' * filled}{'░' * (width - filled)}  {percent}%"


def progress_block(current: int, total: int, caption: str = "") -> str:
    """Блок прогресса с подписью под ним."""
    block = f"<pre>{bar(current, total)}</pre>"
    if caption:
        block += f"\n<i>{caption}</i>"
    return block


def medal(position: int) -> str:
    """Маркер места в таблице: медали для тройки, дальше - две цифры."""
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    if position in medals:
        return medals[position]
    return f" {position}" if position < 10 else str(position)


def leaderboard(
    rows: Iterable[tuple[str, str]],
    name_width: int = 20,
    start: int = 1,
    highlight: int | None = None,
) -> str:
    """Таблица рейтинга. Строки: (имя, значение).

    ``start`` - место первой строки (для окна вокруг игрока).
    ``highlight`` - индекс строки внутри таблицы, которую надо выделить.
    """
    lines = []
    for offset, (name, value) in enumerate(rows, start=start):
        marker = medal(offset)
        clean = name.replace("\n", " ").strip()
        if highlight is not None and offset - start == highlight:
            # помечаем игрока, но ширину не трогаем - колонки остаются ровными
            clean = ("◀ " + clean)[:name_width]
        else:
            clean = clean[:name_width]
        lines.append(f"{marker} {clean:<{name_width}}{value:>8}")
    if not lines:
        return "<i>пока пусто</i>"
    return "<pre>" + "\n".join(lines) + "</pre>"


def points_line(points: int) -> str:
    """Строка с количеством очков."""
    sign = "+" if points > 0 else ""
    return f"{sign}{number(points)}"


def bullets(items: Iterable[str]) -> str:
    """Список с буллетами."""
    return "\n".join(f"• {item}" for item in items)


def note(text: str) -> str:
    """Приглушённая сноска."""
    return f"<i>{text}</i>"


def question(text: str) -> str:
    """Текст вопроса - крупно и по центру строки."""
    return f"<b>{text}</b>"


def answer(text: str) -> str:
    """Правильный ответ в виде строки."""
    return f"Ответ: <b>{text}</b>"


def hint(text: str) -> str:
    """Блок-подсказка с отступом."""
    return f"<blockquote>{text}</blockquote>"


def footer(text: str = "") -> str:
    """Нижний разделитель карточки."""
    if not text:
        return DIVIDER
    return f"{DIVIDER}\n{note(text)}"

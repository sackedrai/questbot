"""Админ-раздел: статистика, игроки, починка, объявления.

Доступен только владельцу бота - его tg_id лежит в секрете
``ADMIN_CHAT_ID``. Если секрет не задан, админка закрыта для всех.

Команды (в личном чате с ботом):

* ``/admin``    - меню админки
* ``/stats``    - короткая сводка
* ``/players``  - список игроков
"""

from __future__ import annotations

import csv
import io

from aiogram import Bot

from . import style
from .config import ADMIN_IDS
from .db import db


def admin_ids() -> tuple[int, ...]:
    """Все аккаунты с правами админа."""
    return ADMIN_IDS


def is_admin(tg_id: int) -> bool:
    """Этот игрок - администратор?"""
    return tg_id in ADMIN_IDS


async def build_admins_text(viewer_id: int | None = None) -> str:
    """Кто имеет права админа: список аккаунтов."""
    ids = admin_ids()
    if not ids:
        return "\n".join(
            [
                style.section("👑 АДМИНЫ"),
                style.note("Список пуст - не задана переменная ADMIN_CHAT_ID."),
            ]
        )

    width = max(len(str(value)) for value in ids)
    lines = []
    for admin_id in ids:
        user = await db.get_user(admin_id)
        name = (user["nickname"] if user else "") or "без профиля"
        mark = "  ← это вы" if admin_id == viewer_id else ""
        lines.append(f"{admin_id:>{width}}  {name}{mark}")

    return "\n".join(
        [
            style.section("👑 АДМИНЫ"),
            "<pre>" + "\n".join(lines) + "</pre>",
        ]
    )


# ----------------------------------------------------------------------
# тексты экранов
# ----------------------------------------------------------------------
async def build_stats_text() -> str:
    """Сводка: игроки, активные сегодня, средняя точность."""
    stats = await db.stats_overview()
    parts = [
        style.header("📊", "СТАТИСТИКА", "сводка по игрокам"),
        style.stats(
            [
                ("", "Игроков", str(stats["total"])),
                ("", "Активны сегодня", str(stats["active_today"])),
                ("", "Средняя точность", f"{stats['accuracy']}%"),
                ("", "Квестов пройдено", str(stats["quests_done"])),
            ]
        ),
    ]
    parts.append(style.footer())
    return "\n".join(parts)


async def build_players_text(limit: int = 20) -> str:
    """Список игроков с их показателями."""
    users = await db.all_users()
    if not users:
        return "\n".join(
            [
                style.header("👥", "ИГРОКИ", "никого ещё нет"),
                style.note("Список пуст - никто не зарегистрировался."),
                style.footer(),
            ]
        )

    rows = []
    for user in users[:limit]:
        rows.append(
            (
                str(user["tg_id"]),
                user["nickname"] or "Без имени",
                f"{user['points']} очк · серия {user['streak']} дн.",
            )
        )

    parts = [
        style.header("👥", "ИГРОКИ", f"всего {len(users)}"),
        "<pre>"
        + "\n".join(
            f"{tg_id:>12}  {name[:16]:<16}  {note}"
            for tg_id, name, note in rows
        )
        + "</pre>",
        style.note("Починить игрока можно из меню «Починить»."),
    ]
    if len(users) > limit:
        parts.append(style.note(f"Показаны первые {limit} из {len(users)}."))
    parts.append(style.footer())
    return "\n".join(parts)


async def build_player_card(tg_id: int) -> str:
    """Карточка игрока для админа."""
    user = await db.get_user(tg_id)
    if user is None:
        return style.note(f"Игрока {tg_id} нет в базе.")

    done = user["quests_done"] or 0
    accuracy = round(100 * user["correct"] / done) if done else 0
    parts = [
        style.header(
            "👤", "ИГРОК", f"{user['nickname'] or 'Без имени'} · {tg_id}"
        ),
        style.stats(
            [
                ("", "Очки", style.number(user["points"])),
                ("", "Квестов", str(done)),
                ("", "Точность", f"{accuracy}%"),
                ("", "Серия", f"{user['streak']} дн."),
                ("", "Рекорд", f"{user['best_streak']} дн."),
                ("", "Последний день", user["last_quest_day"] or "никогда"),
            ]
        ),
    ]
    parts.append(style.footer())
    return "\n".join(parts)


# ----------------------------------------------------------------------
# действия
# ----------------------------------------------------------------------
async def reset_player(tg_id: int) -> str:
    """Сбросить серию игрока."""
    if not await db.reset_streak(tg_id):
        return style.note(f"Игрока {tg_id} нет в базе.")
    return style.note(f"Серия игрока {tg_id} обнулена.")


async def change_points(tg_id: int, delta: int) -> str:
    """Начислить или списать очки."""
    if not await db.add_points_admin(tg_id, delta):
        return style.note(f"Игрока {tg_id} нет в базе.")
    sign = "+" if delta > 0 else ""
    return style.note(f"Игроку {tg_id} начислено {sign}{delta} очков.")


async def grant_achievement(tg_id: int, code: str) -> str:
    """Выдать достижение игроку."""
    from .achievements import ACHIEVEMENTS

    spec = ACHIEVEMENTS.get(code)
    if spec is None:
        return style.note(f"Нет достижения с кодом {code}.")
    if not await db.get_user(tg_id):
        return style.note(f"Игрока {tg_id} нет в базе.")
    await db.grant_achievement(tg_id, code)
    return style.note(f"Игроку {tg_id} выдано: {spec['title']}.")


async def broadcast(bot: Bot, text: str) -> tuple[int, int]:
    """Разослать объявление всем игрокам. Возвращает (доставлено, всего)."""
    users = await db.all_users()
    sent = 0
    for user in users:
        try:
            await bot.send_message(user["tg_id"], text)
            sent += 1
        except Exception:  # noqa: BLE001 - чат мог быть заблокирован
            continue
    return sent, len(users)


async def players_csv_bytes() -> bytes:
    """Выгрузка игроков в CSV."""
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(
        [
            "tg_id",
            "ник",
            "очки",
            "квестов",
            "верных",
            "ошибок",
            "точность_%",
            "серия",
            "рекорд",
            "последний_день",
        ]
    )
    for user in await db.all_users():
        done = user["quests_done"] or 0
        accuracy = round(100 * user["correct"] / done) if done else 0
        writer.writerow(
            [
                user["tg_id"],
                user["nickname"] or "",
                user["points"],
                done,
                user["correct"],
                user["wrong"],
                accuracy,
                user["streak"],
                user["best_streak"],
                user["last_quest_day"] or "",
            ]
        )
    return buf.getvalue().encode("utf-8-sig")


async def vacuum(days: int = 90) -> str:
    """Вычистить старые записи из базы."""
    result = await db.vacuum_old(days)
    return style.note(
        "Убрано: квестов {quests}, матчей {pvp}, сообщений {messages}".format(**result)
    )

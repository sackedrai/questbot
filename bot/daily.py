"""Логика ежедневного квеста.

Правило: следующий квест доступен ровно через 24 часа после того, как
предыдущий был пройден. Не в полночь по календарю, а в то же самое
время суток, что и предыдущий. Время считается в часовом поясе игрока
(по умолчанию Москва, UTC+3), смена - командой /tz.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from aiogram import Bot

from .db import db

QUEST_COOLDOWN = timedelta(hours=24)
DEFAULT_TZ = 3

STATE_ACTIVE = "active"
STATE_DUE = "due"
STATE_COOLDOWN = "cooldown"


@dataclass
class Availability:
    """Когда игроку доступен квест."""

    state: str
    due_at: datetime  # в UTC
    tz_offset: int

    @property
    def seconds_left(self) -> int:
        return max(0, int(self.due_at.timestamp() - time.time()))

    def local_due(self) -> datetime:
        return self.due_at.astimezone(timezone.utc) + timedelta(hours=self.tz_offset)

    def local_now(self) -> datetime:
        return datetime.now(timezone.utc) + timedelta(hours=self.tz_offset)

    def human_left(self) -> str:
        """Сколько осталось ждать - человеческим языком."""
        seconds = self.seconds_left
        if seconds <= 0:
            return "уже сейчас"
        hours, rest = divmod(seconds, 3600)
        minutes = rest // 60
        if hours and minutes:
            return f"через {hours} ч {minutes} мин"
        if hours:
            return f"через {hours} ч"
        return f"через {minutes} мин"

    def human_due(self) -> str:
        return self.local_due().strftime("%H:%M")


async def availability(tg_id: int, risky: bool = False) -> Availability:
    """Посчитать, когда игроку доступен очередной квест."""
    user = await db.get_user(tg_id)
    tz_raw = user["tz_offset"] if user else None
    tz = DEFAULT_TZ if tz_raw is None else int(tz_raw)

    active = await db.get_active_quest(tg_id)
    if active is not None:
        base = datetime.now(timezone.utc)
        return Availability(STATE_ACTIVE, base, tz)

    last = await db.last_done_at(tg_id, risky)
    if last is None:
        # первый квест доступен сразу после регистрации
        created = user["created_at"] if user else time.time()
        due = datetime.fromtimestamp(created, tz=timezone.utc)
    else:
        due = datetime.fromtimestamp(last, tz=timezone.utc) + QUEST_COOLDOWN

    if time.time() >= due.timestamp():
        return Availability(STATE_DUE, due, tz)
    return Availability(STATE_COOLDOWN, due, tz)


async def auto_moment(tg_id: int) -> Optional[datetime]:
    """Когда бот должен выдать квест автоматически.

    Это момент, когда прошло 24 часа с последнего пройденного квеста.
    Если квест уже выдавали недавно (например, игрок его пропустил), то
    автоматическая выдача ждёт, чтобы не спамить.
    """
    avail = await availability(tg_id)
    if avail.state == STATE_ACTIVE:
        return None

    moment = avail.due_at
    last_issued = await db.last_issued_at(tg_id)
    if last_issued:
        limit = datetime.fromtimestamp(last_issued, tz=timezone.utc) + QUEST_COOLDOWN
        if limit > moment:
            moment = limit
    return moment


async def send_daily_quest(bot: Bot, tg_id: int) -> bool:
    """Выдать и отправить квест дня игроку."""
    from .services import start_quest  # локальный импорт: избегаем цикла

    result = await start_quest(tg_id, risky=False)
    if result.blocked:
        return False

    greeting = (
        "🌅 <b>Доброе утро!</b>\n"
        "<i>Твой квест дня ждал тебя.</i>\n\n"
    )
    try:
        await bot.send_message(tg_id, greeting + result.text, reply_markup=result.markup)
    except Exception:  # noqa: BLE001 - чат мог быть заблокирован
        return False
    return True


async def run_daily_pass(bot: Bot, max_wait: float = 0.0) -> int:
    """Раздать квесты тем, кому положено.

    Если квест положен скоро (в пределах max_wait секунд), бот дождётся
    нужного момента и отправит его ровно в срок. Остальных обработает
    следующий запуск.
    """
    now = time.time()
    plan: list[tuple[float, int]] = []

    for user in await db.all_users():
        if not await db.notify_enabled(user["tg_id"]):
            continue  # игрок выключил уведомления
        moment = await auto_moment(user["tg_id"])
        if moment is None:
            continue
        wait = moment.timestamp() - now
        if wait <= 0:
            plan.append((0.0, user["tg_id"]))
        elif wait <= max_wait:
            plan.append((wait, user["tg_id"]))

    plan.sort(key=lambda item: item[0])
    issued = 0
    for wait, tg_id in plan:
        if wait > 0:
            await asyncio.sleep(wait)
        if await send_daily_quest(bot, tg_id):
            issued += 1
    return issued

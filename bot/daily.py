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


def _availability_state(
    *,
    active_started_at: Optional[float],
    last_done: Optional[float],
    created_at: float,
    now: float,
) -> tuple[str, datetime]:
    """Чистый расчёт доступности квеста.

    Возвращает (состояние, момент доступности). Вынесено отдельно, чтобы
    одиночный запрос и массовый обход считали по одним и тем же правилам.
    """
    if active_started_at is not None:
        return STATE_ACTIVE, datetime.fromtimestamp(now, tz=timezone.utc)

    if last_done is None:
        due = datetime.fromtimestamp(created_at, tz=timezone.utc)
    else:
        due = datetime.fromtimestamp(last_done, tz=timezone.utc) + QUEST_COOLDOWN

    state = STATE_DUE if now >= due.timestamp() else STATE_COOLDOWN
    return state, due


def _apply_issued_limit(moment: datetime, last_issued: Optional[float]) -> datetime:
    """Не выдавать квест раньше, чем сутки после прошлой выдачи."""
    if not last_issued:
        return moment
    limit = datetime.fromtimestamp(last_issued, tz=timezone.utc) + QUEST_COOLDOWN
    return limit if limit > moment else moment


async def availability(tg_id: int, risky: bool = False) -> Availability:
    """Посчитать, когда игроку доступен очередной квест."""
    user = await db.get_user(tg_id)
    tz_raw = user["tz_offset"] if user else None
    tz = DEFAULT_TZ if tz_raw is None else int(tz_raw)

    active_started: Optional[float] = None
    active = await db.get_active_quest(tg_id)
    if active is not None:
        # квест, который висит дольше суток, протухает - иначе игрок
        # застревает на нём навсегда
        if time.time() - (active["started_at"] or 0) > QUEST_COOLDOWN.total_seconds():
            await db.finish_quest(active["id"], 0, "expired")
        else:
            active_started = active["started_at"] or 0

    last = await db.last_done_at(tg_id, risky)
    created = user["created_at"] if user else time.time()
    state, due = _availability_state(
        active_started_at=active_started,
        last_done=last,
        created_at=created,
        now=time.time(),
    )
    return Availability(state, due, tz)


async def auto_moment(tg_id: int) -> Optional[datetime]:
    """Когда бот должен выдать квест автоматически.

    Это момент, когда прошло 24 часа с последнего пройденного квеста.
    Если квест уже выдавали недавно (например, игрок его пропустил), то
    автоматическая выдача ждёт, чтобы не спамить.
    """
    avail = await availability(tg_id)
    if avail.state == STATE_ACTIVE:
        return None

    last_issued = await db.last_issued_at(tg_id)
    return _apply_issued_limit(avail.due_at, last_issued)


async def send_daily_quest(bot: Bot, tg_id: int) -> bool:
    """Выдать и отправить квест дня игроку."""
    from .services import start_quest  # локальный импорт: избегаем цикла
    from .utils import auto_clean  # локальный импорт: избегаем цикла

    result = await start_quest(tg_id, risky=False)
    if result.blocked:
        return False

    greeting = (
        "🌅 <b>Доброе утро!</b>\n"
        "<i>Твой квест дня ждал тебя.</i>\n\n"
    )
    try:
        # в чате остаётся только новый квест - старое убираем
        await auto_clean(bot, tg_id, db)
        await bot.send_message(tg_id, greeting + result.text, reply_markup=result.markup)
    except Exception:  # noqa: BLE001 - чат мог быть заблокирован
        return False
    return True


async def run_daily_pass(bot: Bot, max_wait: float = 0.0) -> int:
    """Раздать квесты тем, кому положено.

    Если квест положен скоро (в пределах max_wait секунд), бот дождётся
    нужного момента и отправит его ровно в срок. Остальных обработает
    следующий запуск.

    Считаем массово: несколько запросов на всех игроков вместо десятка
    запросов на каждого.
    """
    now = time.time()
    users = await db.all_users()
    if not users:
        return 0

    # протухшие квесты закрываем разом - иначе игрок застревает на старом
    await db.finish_expired_quests(QUEST_COOLDOWN.total_seconds())

    active_map = await db.active_quests_map()
    done_map = await db.last_done_map()
    issued_map = await db.last_issued_map()

    plan: list[tuple[float, int]] = []

    for user in users:
        notify = user["notify"]
        if notify is not None and not notify:
            continue  # игрок выключил уведомления
        tg_id = user["tg_id"]

        active_started: Optional[float] = None
        active = active_map.get(tg_id)
        if active is not None:
            started = active["started_at"] or 0
            if started and now - started <= QUEST_COOLDOWN.total_seconds():
                active_started = started

        state, due = _availability_state(
            active_started_at=active_started,
            last_done=done_map.get(tg_id),
            created_at=user["created_at"] or now,
            now=now,
        )
        if state == STATE_ACTIVE:
            continue

        moment = _apply_issued_limit(due, issued_map.get(tg_id))
        wait = moment.timestamp() - now
        if wait <= 0:
            plan.append((0.0, tg_id))
        elif wait <= max_wait:
            plan.append((wait, tg_id))

    plan.sort(key=lambda item: item[0])
    issued = 0
    for wait, tg_id in plan:
        if wait > 0:
            await asyncio.sleep(wait)
        if await send_daily_quest(bot, tg_id):
            issued += 1
    return issued

"""Самопроверка бота.

Проблема, которую ловит самопроверка: бот формально жив (процесс работает,
polling идёт, прогоны зелёные), но обработчики сломались - на сообщения
не отвечает. Именно так мы однажды потеряли несколько часов.

Решение простое: бот подсовывает диспетчеру настоящий объект Update с
командой самопроверки. Обработчик не отвечает в Telegram (иначе это спам),
но отмечает в базе, что всё работает. Если команда падает - растёт
счётчик ошибок, и сторож сообщает владельцу.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher
from aiogram.types import Chat, Message, Update, User

from .db import db

log = logging.getLogger(__name__)

SELFCHECK_COMMAND = "/__selfcheck"

# Как часто бот проверяет себя
SELFCHECK_INTERVAL = 1800  # 30 минут


async def mark_selfcheck_ok() -> None:
    """Отметить, что обработчики живы."""
    await db.set_meta("selfcheck_ok_at", str(time.time()))
    count = int(await db.get_meta("selfcheck_count", "0") or 0)
    await db.set_meta("selfcheck_count", str(count + 1))


async def run_self_check(dp: Dispatcher, bot: Bot, chat_id: int = 0) -> bool:
    """Прогнать фейковое сообщение через диспетчер.

    Возвращает True, если обработчик отработал без ошибок.
    """
    fake_user = User(id=chat_id or 1, is_bot=False, first_name="Selfcheck")
    fake_chat = Chat(id=chat_id or 1, type="private")
    message = Message(
        message_id=999_999_999,
        date=datetime.now(timezone.utc),
        chat=fake_chat,
        from_user=fake_user,
        text=SELFCHECK_COMMAND,
    )
    update = Update(update_id=0, message=message)

    before = await db.get_meta("selfcheck_count", "0")
    try:
        await dp.feed_update(bot, update)
    except Exception as exc:  # noqa: BLE001
        log.warning("Самопроверка не прошла: %r", exc)
        return False

    after = await db.get_meta("selfcheck_count", "0")
    if after == before:
        log.warning("Самопроверка: обработчик не отработал")
        return False
    return True


async def self_check_loop(dp: Dispatcher, bot: Bot, chat_id: int = 0) -> None:
    """Проверять себя каждые SELFCHECK_INTERVAL секунд."""
    while True:
        await asyncio.sleep(SELFCHECK_INTERVAL)
        try:
            ok = await run_self_check(dp, bot, chat_id)
            log.info("Самопроверка: %s", "ок" if ok else "провалена")
        except Exception as exc:  # noqa: BLE001
            log.warning("Самопроверка упала: %r", exc)

"""Тест РОУТИНГА aiogram: настоящий CallbackQuery через Dispatcher.

flowtest.py вызывал обработчики напрямую и не проверял, что aiogram вообще
до них дойдёт. Этот тест кормит диспетчер настоящими объектами Telegram.

Запуск: python tools/routing_test.py
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # pragma: no cover
        pass

from aiogram import Dispatcher  # noqa: E402
from aiogram.client.session.aiohttp import AiohttpSession  # noqa: E402
from aiogram.fsm.storage.memory import MemoryStorage  # noqa: E402
from aiogram.types import (  # noqa: E402
    CallbackQuery,
    Chat,
    Message,
    Update,
    User,
)

from bot.db import Database  # noqa: E402
from bot.handlers import common, games, profile, quests, ranking  # noqa: E402

PASSED = 0
FAILED = 0


def check(condition: bool, label: str) -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  ok   {label}")
    else:
        FAILED += 1
        print(f"  FAIL {label}")


class MockSession(AiohttpSession):
    """Сессия без сети: записывает вызовы и возвращает сам метод."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[object] = []

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        return method

    def method_names(self) -> list[str]:
        return [type(call).__name__ for call in self.calls]


def build_router():
    """Берём тот же роутер, что использует бот (handlers/__init__.py)."""
    from bot.handlers import router as main_router

    return main_router


async def main() -> None:
    print("=" * 60)
    print("  Тест роутинга aiogram")
    print("=" * 60)

    import faulthandler

    faulthandler.dump_traceback_later(25, exit=True)

    # тестовая БД
    db = Database(":memory:")
    await db.connect()
    import bot.handlers.common as common_module
    import bot.handlers.games as games_module
    import bot.handlers.profile as profile_module
    import bot.handlers.quests as quests_module
    import bot.handlers.ranking as ranking_module
    import bot.services as services_module

    for module in (services_module, common_module, games_module,
                   profile_module, quests_module, ranking_module):
        module.db = db

    session = MockSession()
    bot = None
    from aiogram import Bot

    bot = Bot(token="123456:AAFakeTokenForRoutingTest", session=session)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(build_router())

    user = User(id=555, is_bot=False, first_name="Тест")
    chat = Chat(id=555, type="private")

    # --- 1. callback выбора сложности ---
    message = Message(message_id=1, date=datetime.now(timezone.utc),
                      chat=chat, from_user=user)
    cq = CallbackQuery(id="cq1", from_user=user, chat_instance="ci",
                       data="diff:easy", message=message)
    await dp.feed_update(bot, Update(update_id=1, callback_query=cq))

    row = await db.get_user(555)
    check(row is not None and row["difficulty"] == "easy",
          f"callback diff:easy обработан (difficulty={row['difficulty'] if row else None})")
    check("EditMessageText" in session.method_names(),
          f"сообщение с кнопками обновлено: {session.method_names()}")

    # --- 2. callback главного меню ---
    session.calls.clear()
    message2 = Message(message_id=2, date=datetime.now(timezone.utc),
                       chat=chat, from_user=user)
    cq2 = CallbackQuery(id="cq2", from_user=user, chat_instance="ci",
                        data="menu:profile", message=message2)
    await dp.feed_update(bot, Update(update_id=2, callback_query=cq2))
    check("EditMessageText" in session.method_names(),
          f"callback menu:profile обработан: {session.method_names()}")

    # --- 3. callback рейтинга ---
    session.calls.clear()
    message3 = Message(message_id=3, date=datetime.now(timezone.utc),
                       chat=chat, from_user=user)
    cq3 = CallbackQuery(id="cq3", from_user=user, chat_instance="ci",
                        data="top:today", message=message3)
    await dp.feed_update(bot, Update(update_id=3, callback_query=cq3))
    check("EditMessageText" in session.method_names(),
          f"callback top:today обработан: {session.method_names()}")

    # --- 4. игровой callback ---
    await db.create_user(555, "u", "U")
    quest_id = await db.create_quest(555, "2026-01-01", "quiz", "easy",
                                     {"q": "?", "options": ["a", "b", "c", "d"],
                                      "correct": 0, "cat": "t"})
    session.calls.clear()
    message4 = Message(message_id=4, date=datetime.now(timezone.utc),
                       chat=chat, from_user=user)
    cq4 = CallbackQuery(id="cq4", from_user=user, chat_instance="ci",
                        data=f"g:{quest_id}:0", message=message4)
    await dp.feed_update(bot, Update(update_id=4, callback_query=cq4))
    check("EditMessageText" in session.method_names(),
          f"игровой callback обработан: {session.method_names()}")
    qrow = await db.get_quest(quest_id)
    check(qrow["status"] == "done", f"квест закрыт со статусом done: {qrow['status']}")

    # --- 5. полный цикл текстовой игры через диспетчер ---
    # /quest -> бот выдаёт загадку и ставит состояние -> игрок пишет ответ
    import bot.services as services_module

    services_module.GAME_TYPES = ("riddle",)
    session.calls.clear()

    msg_q = Message(message_id=10, date=datetime.now(timezone.utc),
                    chat=chat, from_user=user, text="/quest")
    await dp.feed_update(bot, Update(update_id=10, message=msg_q))
    check("SendMessage" in session.method_names(),
          f"/quest отработал через диспетчер: {session.method_names()}")

    active = await db.get_active_quest(555)
    check(active is not None, "загадка выдана и сохранена в базе")
    if active is not None:
        import json

        payload = json.loads(active["payload"])
        session.calls.clear()
        msg_a = Message(message_id=11, date=datetime.now(timezone.utc),
                        chat=chat, from_user=user, text=payload["answers"][0])
        await dp.feed_update(bot, Update(update_id=11, message=msg_a))
        qrow = await db.get_quest(active["id"])
        check(qrow["status"] == "done",
              f"текстовый ответ засчитан: {qrow['status']}")
        check("SendMessage" in session.method_names(),
              f"бот ответил на ответ: {session.method_names()}")

    await db.close()

    print("\n" + "=" * 60)
    print(f"  Пройдено: {PASSED}   Провалено: {FAILED}")
    print("=" * 60)
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    asyncio.run(main())

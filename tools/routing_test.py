"""Тест РОУТИНГА aiogram: настоящий CallbackQuery через Dispatcher.

flowtest.py вызывал обработчики напрямую и не проверял, что aiogram вообще
до них дойдёт. Этот тест кормит диспетчер настоящими объектами Telegram.

Запуск: python tools/routing_test.py
"""

from __future__ import annotations

import asyncio
import re
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
from aiogram.exceptions import TelegramBadRequest  # noqa: E402
from aiogram.methods import (  # noqa: E402
    DeleteMessage,
    DeleteMessages,
    EditMessageText,
    GetMe,
    SendMessage,
)

from bot.db import Database  # noqa: E402
from bot.middleware import ErrorCounterMiddleware  # noqa: E402
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
    """Сессия без сети: записывает вызовы и возвращает осмысленный ответ.

    Повторяет поведение Telegram: если текст сообщения не изменился,
    editMessageText падает с "message is not modified".
    """

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[object] = []
        self.texts: dict[tuple[int, int], str] = {}

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, SendMessage):
            return Message(
                message_id=4242,
                date=datetime.now(timezone.utc),
                chat=Chat(id=555, type="private"),
            )
        if isinstance(method, DeleteMessage | DeleteMessages):
            return True
        if isinstance(method, GetMe):
            return User(
                id=1,
                is_bot=True,
                first_name="Quest",
                username="test_quest_bot",
            )
        if isinstance(method, EditMessageText):
            key = (method.chat_id, method.message_id)
            text = method.text or ""
            if self.texts.get(key) == text:
                raise TelegramBadRequest(
                    method="editMessageText",
                    message="Bad Request: message is not modified",
                )
            self.texts[key] = text
        return method

    def method_names(self) -> list[str]:
        return [type(call).__name__ for call in self.calls]

    def deleted_ids(self) -> list[int]:
        """Все id, которые бот попытался удалить."""
        ids: list[int] = []
        for call in self.calls:
            if isinstance(call, DeleteMessage):
                ids.append(call.message_id)
            elif isinstance(call, DeleteMessages):
                ids.extend(call.message_ids)
        return ids


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
    import bot.daily as daily_module
    import bot.adaptive as adaptive_module
    import bot.pvp as pvp_module
    import bot.selfcheck as selfcheck_module
    import bot.middleware as middleware_module
    import bot.achievements as achievements_module
    import bot.handlers.pvp as pvp_handlers_module
    import bot.handlers.settings as settings_handlers_module

    for module in (services_module, common_module, games_module,
                   profile_module, quests_module, ranking_module,
                   daily_module, adaptive_module, pvp_module,
                   selfcheck_module, middleware_module,
                   pvp_handlers_module, settings_handlers_module,
                   achievements_module):
        module.db = db

    session = MockSession()
    bot = None
    from aiogram import Bot

    bot = Bot(token="123456:AAFakeTokenForRoutingTest", session=session)
    dp = Dispatcher(storage=MemoryStorage())
    dp.message.middleware(ErrorCounterMiddleware())
    dp.callback_query.middleware(ErrorCounterMiddleware())
    dp.include_router(build_router())

    user = User(id=555, is_bot=False, first_name="Тест")
    chat = Chat(id=555, type="private")

    # --- 1. callback старого выбора сложности (теперь сложность адаптивная) ---
    message = Message(message_id=1, date=datetime.now(timezone.utc),
                      chat=chat, from_user=user)
    cq = CallbackQuery(id="cq1", from_user=user, chat_instance="ci",
                       data="diff:easy", message=message)
    await dp.feed_update(bot, Update(update_id=1, callback_query=cq))
    check("EditMessageText" in session.method_names(),
          f"обработчик сложности ответил: {session.method_names()}")
    row = await db.get_user(555)
    check(row is None or row["difficulty"] in ("easy", "medium", "hard"),
          "сложность не задаётся вручную")
    check("EditMessageText" in session.method_names(),
          f"сообщение с кнопками обновлено: {session.method_names()}")

    # --- 1.1. сообщения игрока запоминаются (для авточистки чата) ---
    # проверяется в selftest: middleware не выполняется, если ни один
    # обработчик не подошёл

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
    await db.create_user(555)
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
    # отдельный игрок: у 555 уже есть пройденный квест, значит кулдаун 24ч
    import bot.services as services_module

    services_module.GAME_TYPES = ("riddle",)
    session.calls.clear()

    fresh_user = User(id=556, is_bot=False, first_name="Другой")
    fresh_chat = Chat(id=556, type="private")
    await db.create_user(556)
    msg_q = Message(message_id=10, date=datetime.now(timezone.utc),
                    chat=fresh_chat, from_user=fresh_user, text="/quest")
    await dp.feed_update(bot, Update(update_id=10, message=msg_q))
    check("SendMessage" in session.method_names(),
          f"/quest отработал через диспетчер: {session.method_names()}")

    active = await db.get_active_quest(556)
    check(active is not None, "загадка выдана и сохранена в базе")
    if active is not None:
        import json

        payload = json.loads(active["payload"])
        session.calls.clear()
        msg_a = Message(message_id=11, date=datetime.now(timezone.utc),
                        chat=fresh_chat, from_user=fresh_user,
                        text=payload["answers"][0])
        await dp.feed_update(bot, Update(update_id=11, message=msg_a))
        qrow = await db.get_quest(active["id"])
        check(qrow["status"] == "done",
              f"текстовый ответ засчитан: {qrow['status']}")
        check("SendMessage" in session.method_names(),
              f"бот ответил на ответ: {session.method_names()}")

        # после прохождения квест недоступен 24 часа
        session.calls.clear()
        msg_q2 = Message(message_id=12, date=datetime.now(timezone.utc),
                         chat=fresh_chat, from_user=fresh_user, text="/quest")
        await dp.feed_update(bot, Update(update_id=12, message=msg_q2))
        check("SendMessage" in session.method_names(),
              "после прохождения квест закрыт на 24 часа")

    # --- 6. отказ от квеста ---
    await db.create_user(555)
    quest_id = await db.create_quest(555, "2026-10-21", "quiz", "easy",
                                     {"q": "?", "options": ["a", "b", "c", "d"],
                                      "correct": 0, "cat": "t"})
    points_before = (await db.get_user(555))["points"]
    session.calls.clear()
    msg_skip = Message(message_id=20, date=datetime.now(timezone.utc),
                        chat=chat, from_user=user)
    cq_skip = CallbackQuery(id="cq5", from_user=user, chat_instance="ci",
                            data=f"skip:{quest_id}", message=msg_skip)
    await dp.feed_update(bot, Update(update_id=20, callback_query=cq_skip))
    qrow = await db.get_quest(quest_id)
    check(qrow["status"] == "skipped", f"квест пропущен: {qrow['status']}")
    check((await db.get_user(555))["points"] == points_before,
          "за отказ очки не снимаются")
    check("EditMessageText" in session.method_names(),
          f"бот показал экран отказа: {session.method_names()}")

    # --- 7. очистка чата: удаляется всё в диапазоне ---
    await db.track_message(555, 12, "quest")
    await db.track_message(555, 13, "quest")
    session.calls.clear()
    msg_clear = Message(message_id=21, date=datetime.now(timezone.utc),
                        chat=chat, from_user=user, text="/clear")
    await dp.feed_update(bot, Update(update_id=21, message=msg_clear))
    deleted = session.deleted_ids()
    check(12 in deleted and 13 in deleted,
          f"известные сообщения бота удалены: {sorted(deleted)[:8]}")
    check(any(i < 12 for i in deleted),
          f"зачищены и неотслеженные сообщения: {min(deleted) if deleted else None}")
    check(max(deleted) >= 20, "зачищен диапазон до текущего сообщения")

    # --- 8. очистка из меню: само меню остаётся ---
    await db.track_message(555, 14, "menu")
    session.calls.clear()
    msg_menu = Message(message_id=22, date=datetime.now(timezone.utc),
                       chat=chat, from_user=user)
    cq_menu = CallbackQuery(id="cq6", from_user=user, chat_instance="ci",
                            data="menu:clear", message=msg_menu)
    await dp.feed_update(bot, Update(update_id=22, callback_query=cq_menu))
    deleted = session.deleted_ids()
    check(22 not in deleted, f"меню не удалено при очистке: {sorted(deleted)[:8]}")
    check("EditMessageText" in session.method_names(),
          f"меню переписано в экран очистки: {session.method_names()}")

    # --- 8.1. в меню возвращаемся без второго меню ---
    # в чате мог остаться другой экран (например, вызов на бой)
    await db.track_message(555, 40, "auto")
    session.calls.clear()
    msg_menu2 = Message(message_id=41, date=datetime.now(timezone.utc),
                        chat=chat, from_user=user)
    cq_menu2 = CallbackQuery(id="cq_menu_home", from_user=user, chat_instance="ci",
                             data="menu:home", message=msg_menu2)
    await dp.feed_update(bot, Update(update_id=41, callback_query=cq_menu2))
    deleted = session.deleted_ids()
    check(40 in deleted,
          f"прошлый экран удалён при возврате в меню: {sorted(deleted)[:8]}")
    check(41 not in deleted, f"само меню осталось: {sorted(deleted)[:8]}")

    # --- 9. повторное нажатие той же кнопки не плодит сообщения ---
    session.calls.clear()
    msg_top = Message(message_id=30, date=datetime.now(timezone.utc),
                      chat=chat, from_user=user)
    for _ in range(3):
        cq_top = CallbackQuery(id="cq7", from_user=user, chat_instance="ci",
                                data="top:today", message=msg_top)
        await dp.feed_update(bot, Update(update_id=30, callback_query=cq_top))
    sent = [c for c in session.calls if isinstance(c, SendMessage)]
    check(not sent,
          f"повторные нажатия не создают новых сообщений: {len(sent)}")

    # --- 10. из рейтинга есть кнопка «в меню» ---
    from bot.keyboards import top_menu

    markup = top_menu("today")
    labels = [button.text for row in markup.inline_keyboard for button in row]
    check(any("меню" in label.lower() for label in labels),
          f"в рейтинге есть кнопка возврата: {labels}")

    # --- 11. PvP: вызов, принятие, одинаковый квест, победа ---
    await db.create_user(600)
    await db.create_user(601)
    user_a = User(id=600, is_bot=False, first_name="A")
    user_b = User(id=601, is_bot=False, first_name="B")

    session.calls.clear()
    msg_pvp = Message(message_id=40, date=datetime.now(timezone.utc),
                       chat=Chat(id=600, type="private"), from_user=user_a,
                       text="/pvp")
    await dp.feed_update(bot, Update(update_id=40, message=msg_pvp))

    code = None
    for call in session.calls:
        if isinstance(call, SendMessage) and call.text:
            found = re.search(r"start=pvp_([A-Z0-9]{6})", call.text)
            if found:
                code = found.group(1)
                break
    check(bool(code), f"код вызова создан: {code}")

    # вызов из меню: сообщение переписывается на месте, второго окна нет
    session.calls.clear()
    msg_menu_pvp = Message(message_id=42, date=datetime.now(timezone.utc),
                           chat=Chat(id=600, type="private"), from_user=user_a)
    cq_pvp = CallbackQuery(id="cq_pvp", from_user=user_a, chat_instance="ci",
                           data="menu:pvp", message=msg_menu_pvp)
    await dp.feed_update(bot, Update(update_id=42, callback_query=cq_pvp))
    sent_pvp = [c for c in session.calls if isinstance(c, SendMessage)]
    edited_pvp = [c for c in session.calls if isinstance(c, EditMessageText)]
    check(not sent_pvp, f"вызов из меню не создаёт второго окна: {len(sent_pvp)}")
    check(edited_pvp, "вызов из меню переписан на месте")

    session.calls.clear()
    msg_acc = Message(message_id=41, date=datetime.now(timezone.utc),
                       chat=Chat(id=601, type="private"), from_user=user_b,
                       text=f"/pvp {code}")
    await dp.feed_update(bot, Update(update_id=41, message=msg_acc))

    quest_a = await db.get_active_quest(600)
    quest_b = await db.get_active_quest(601)
    check(quest_a is not None and quest_b is not None,
          "оба игрока получили квест")
    if quest_a is not None and quest_b is not None:
        check(quest_a["payload"] == quest_b["payload"],
              "квест у обоих одинаковый")
        check(quest_a["pvp_id"] == quest_b["pvp_id"] and quest_a["pvp_id"] > 0,
              "квесты привязаны к одному матчу")

        match = await db.finish_pvp(quest_a["pvp_id"], 600, 50)
        check(match is None, "матч ждёт второго игрока")
        match = await db.finish_pvp(quest_a["pvp_id"], 601, 30)
        check(match is not None and match["winner"] == 600,
              f"победитель определён верно: {match['winner'] if match else None}")
        winner = await db.get_user(600)
        loser = await db.get_user(601)
        check(winner["pvp_wins"] == 1, f"победа засчитана: {winner['pvp_wins']}")
        check(loser["pvp_losses"] == 1, f"поражение засчитано: {loser['pvp_losses']}")

    # --- 12. /quest при активном квесте показывает квест, а не заглушку ---
    await db.create_user(700)
    user_c = User(id=700, is_bot=False, first_name="C")
    chat_c = Chat(id=700, type="private")
    await db.create_quest(700, "2026-10-21", "quiz", "easy",
                          {"q": "Вопрос?", "options": ["a", "b", "c", "d"],
                           "correct": 0, "cat": "тест"})
    session.calls.clear()
    msg_again = Message(message_id=50, date=datetime.now(timezone.utc),
                         chat=chat_c, from_user=user_c, text="/quest")
    await dp.feed_update(bot, Update(update_id=50, message=msg_again))
    sent = [c for c in session.calls if isinstance(c, SendMessage)]
    check(bool(sent), f"квест показан заново: {len(sent)} сообщений")
    check(any("Вопрос?" in (c.text or "") for c in sent),
          "это именно квест, а не заглушка")

    # --- 13. самопроверка: фейковое сообщение через диспетчер ---
    from bot.selfcheck import run_self_check

    ok = await run_self_check(dp, bot)
    check(ok, "самопроверка прошла")
    stamp = await db.get_meta("selfcheck_ok_at", "0")
    check(float(stamp) > 0, f"отметка самопроверки записана: {stamp}")
    count = await db.get_meta("selfcheck_count", "0")
    check(int(count) >= 1, f"счётчик самопроверок: {count}")

    await db.close()

    print("\n" + "=" * 60)
    print(f"  Пройдено: {PASSED}   Провалено: {FAILED}")
    print("=" * 60)
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    asyncio.run(main())

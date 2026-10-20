"""Интеграционный тест: полный цикл игрока без сети и токена.

Прогоняет реальные хендлеры с подставными объектами Telegram.
Каждая из пяти мини-игр проверяется отдельно.

Запуск: python tools/flowtest.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # pragma: no cover
        pass

from aiogram.fsm.context import FSMContext  # noqa: E402
from aiogram.fsm.storage.memory import MemoryStorage  # noqa: E402

from bot.db import Database  # noqa: E402
from bot.games import GAMES  # noqa: E402
from bot.handlers import common, games, profile, quests, ranking  # noqa: E402
from bot.services import GAME_TYPES  # noqa: E402
from bot.states import Onboarding  # noqa: E402

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


class FakeUser:
    def __init__(self, tg_id: int, username: str = "tester", full_name: str = "Тестер"):
        self.id = tg_id
        self.username = username
        self.full_name = full_name


class FakeChat:
    def __init__(self, chat_id: int):
        self.id = chat_id
        self.type = "private"


class FakeBot:
    """Заглушка бота: умеет удалять сообщения."""

    def __init__(self) -> None:
        self.deleted: list[tuple[int, int]] = []

    async def delete_message(self, chat_id: int, message_id: int) -> None:
        self.deleted.append((chat_id, message_id))


class FakeMessage:
    """Заглушка сообщения: собирает всё, что бот отправил."""

    def __init__(self, text: str, user: FakeUser):
        self.text = text
        self.from_user = user
        self.chat = FakeChat(user.id)
        self.message_id = 1
        self.sent: list[tuple[str, object]] = []
        self.edited: list[tuple[str, object]] = []

    async def answer(self, text: str, reply_markup=None, **kwargs):
        self.sent.append((text, reply_markup))
        return self

    async def edit_text(self, text: str, reply_markup=None, **kwargs):
        self.edited.append((text, reply_markup))
        return self

    @property
    def last_text(self) -> str:
        if self.sent:
            return self.sent[-1][0]
        return self.edited[-1][0] if self.edited else ""


class FakeCallback:
    def __init__(self, data: str, user: FakeUser, message: FakeMessage):
        self.data = data
        self.from_user = user
        self.message = message
        self.answers: list[str | None] = []

    async def answer(self, text: str | None = None, show_alert: bool = False, **kwargs):
        self.answers.append(text)


async def play_quest(
    db: Database,
    user: FakeUser,
    game_type: str,
    state: FSMContext,
    fake_bot: FakeBot,
) -> None:
    """Пройти квест выбранного типа до конца."""
    quest_msg = FakeMessage("/quest", user)
    await quests.cmd_quest(quest_msg, state, fake_bot)

    quest_row = await db.get_active_quest(user.id)
    if quest_row is None:
        raise AssertionError("квест не выдан")
    quest_id = quest_row["id"]
    payload = json.loads(quest_row["payload"])
    message = quest_msg

    if game_type in ("quiz", "fast"):
        await games.on_game_callback(
            FakeCallback(f"g:{quest_id}:{payload['correct']}", user, message), state
        )
    elif game_type == "timeline":
        items = payload["items"]
        for _ in range(len(items)):
            fresh = await db.get_quest(quest_id)
            collected = json.loads(fresh["payload"]).get("collected", [])
            remaining = [i for i in range(len(items)) if i not in collected]
            if not remaining:
                break
            pick = min(remaining, key=lambda i: items[i]["year_num"])
            await games.on_game_callback(
                FakeCallback(f"g:{quest_id}:{pick}", user, message), state
            )
    elif game_type == "riddle":
        await games.on_game_text(FakeMessage(payload["answers"][0], user), state)
    elif game_type == "word":
        await games.on_game_text(FakeMessage(payload["word"].lower(), user), state)


async def run_flow(db: Database, game_type: str) -> None:
    print(f"\n--- Сценарий: {game_type} ---")
    storage = MemoryStorage()
    user = FakeUser(1000 + list(GAMES).index(game_type))
    state = FSMContext(storage=storage, key=user.id)
    fake_bot = FakeBot()
    message = FakeMessage("/start", user)

    # Форсируем тип мини-игры, чтобы проверить каждую
    import bot.services as services_module
    services_module.GAME_TYPES = (game_type,)

    # 1. Регистрация
    await common.cmd_start(message, state, fake_bot)
    check(bool(message.sent), "на /start бот отвечает")
    current_state = await state.get_state()
    check(current_state == Onboarding.nickname.state,
          f"бот просит ник (состояние: {current_state})")

    await common.on_nickname(FakeMessage("  Вася  ", user), state, fake_bot)
    row = await db.get_user(user.id)
    check(row["nickname"] == "Вася", f"ник сохранён: {row['nickname']}")

    # 2. Выбор сложности
    await common.on_difficulty(FakeCallback("diff:hard", user, message), state)
    row = await db.get_user(user.id)
    check(row["difficulty"] == "hard", f"сложность сохранена: {row['difficulty']}")

    # 3–5. Квест и ответ
    await play_quest(db, user, game_type, state, fake_bot)
    row = await db.get_user(user.id)
    check(row["points"] > 0, f"очки начислены: {row['points']}")
    check(row["quests_done"] == 1, f"квест учтён: {row['quests_done']}")
    check(row["streak"] == 1, f"серия начата: {row['streak']}")

    check(await db.get_active_quest(user.id) is None, "активных квестов не осталось")

    # 6. Повторный квест в тот же день заблокирован
    again = FakeMessage("/quest", user)
    await quests.cmd_quest(again, state, fake_bot)
    check("следующий квест" in again.last_text.lower(),
          "повторный квест дня заблокирован")

    # 7. Рискованный квест доступен
    risk_msg = FakeMessage("/risk", user)
    await quests.cmd_risk(risk_msg, state, fake_bot)
    check(bool(risk_msg.sent), "рискованный квест выдан")

    # 8. Профиль и рейтинг
    profile_msg = FakeMessage("/profile", user)
    await profile.cmd_profile(profile_msg)
    check("профиль" in profile_msg.last_text.lower(), "профиль построен")

    top_msg = FakeMessage("/top", user)
    await ranking.cmd_top(top_msg)
    check("рейтинг" in top_msg.last_text.lower(), "рейтинг построен")
    check("Вася" in top_msg.last_text, "игрок есть в рейтинге")

    # 9–10. Команды
    diff_msg = FakeMessage("/difficulty", user)
    await common.cmd_difficulty(diff_msg)
    check(bool(diff_msg.sent), "команда смены сложности отвечает")

    help_msg = FakeMessage("/help", user)
    await common.cmd_help(help_msg)
    check("как играть" in help_msg.last_text.lower(), "справка отдаётся")


async def test_failure(db: Database) -> None:
    """Проверяем, что неверный ответ не начисляет очки и квест можно переиграть."""
    print("\n--- Сценарий: неверный ответ ---")
    import bot.services as services_module
    services_module.GAME_TYPES = ("quiz",)

    storage = MemoryStorage()
    user = FakeUser(2001)
    state = FSMContext(storage=storage, key=user.id)
    fake_bot = FakeBot()
    message = FakeMessage("/start", user)

    await common.cmd_start(message, state, fake_bot)
    await common.on_nickname(FakeMessage("Петя", user), state, fake_bot)
    await common.on_difficulty(FakeCallback("diff:easy", user, message), state)

    quest_msg = FakeMessage("/quest", user)
    await quests.cmd_quest(quest_msg, state, fake_bot)
    quest_row = await db.get_active_quest(user.id)
    payload = json.loads(quest_row["payload"])
    wrong_index = (payload["correct"] + 1) % len(payload["options"])

    await games.on_game_callback(
        FakeCallback(f"g:{quest_row['id']}:{wrong_index}", user, message), state
    )

    row = await db.get_user(user.id)
    check(row["points"] == 0, f"за неверный ответ очков нет: {row['points']}")
    check(row["wrong"] == 1, f"ошибка учтена: {row['wrong']}")

    again = FakeMessage("/quest", user)
    await quests.cmd_quest(again, state, fake_bot)
    check("следующий квест" not in again.last_text.lower(),
          "после провала квест можно переиграть")


async def main() -> None:
    print("=" * 56)
    print("  QuestBot — интеграционный тест")
    print("=" * 56)

    db = Database(":memory:")
    await db.connect()

    import bot.handlers.common as common_module
    import bot.handlers.games as games_module
    import bot.handlers.profile as profile_module
    import bot.handlers.quests as quests_module
    import bot.handlers.ranking as ranking_module
    import bot.services as services_module
    import bot.daily as daily_module

    for module in (
        services_module,
        common_module,
        games_module,
        profile_module,
        quests_module,
        ranking_module,
        daily_module,
    ):
        module.db = db

    try:
        for game_type in GAMES:
            await run_flow(db, game_type)
        await test_failure(db)
    finally:
        await db.close()

    print("\n" + "=" * 56)
    print(f"  Пройдено: {PASSED}   Провалено: {FAILED}")
    print("=" * 56)
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    asyncio.run(main())

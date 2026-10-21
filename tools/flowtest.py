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
from bot.states import Onboarding  # noqa: E402
from tools._testing import (  # noqa: E402
    FakeBot,
    FakeCallback,
    FakeMessage,
    FakeUser,
    Tally,
    patch_db,
)


TALLY = Tally()
check = TALLY.check





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
            FakeCallback(f"g:{quest_id}:{payload['correct']}", user, message),
            state,
            fake_bot,
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
                FakeCallback(f"g:{quest_id}:{pick}", user, message),
                state,
                fake_bot,
            )
    elif game_type == "riddle":
        await games.on_game_text(FakeMessage(payload["answers"][0], user), state)
    elif game_type == "word":
        await games.on_game_text(FakeMessage(payload["word"].lower(), user), state)
    elif game_type == "truth":
        choice = "t" if payload["a"] else "f"
        await games.on_game_callback(
            FakeCallback(f"g:{quest_id}:{choice}", user, message),
            state,
            fake_bot,
        )
    elif game_type == "math":
        await games.on_game_callback(
            FakeCallback(f"g:{quest_id}:{payload['correct']}", user, message),
            state,
            fake_bot,
        )


async def test_pvp(db: Database) -> None:
    """Матч PvP: квест выдаётся обоим, результат объявляется обоим.

    Регрессия: в обработчике игровых кнопок не было параметра bot, и
    ветка PvP падала с NameError в момент объявления результата.
    """
    print("\n--- Сценарий: PvP ---")
    import json

    import bot.pvp as pvp_module
    from bot.handlers import pvp as pvp_handlers

    storage = MemoryStorage()
    user_a = FakeUser(3001)
    user_b = FakeUser(3002)
    state = FSMContext(storage=storage, key=user_a.id)
    fake_bot = FakeBot()

    await db.create_user(3001)
    await db.set_nickname(3001, "Первый")
    await db.create_user(3002)
    await db.set_nickname(3002, "Второй")

    # берём викторину: у неё есть готовый "correct", загадка отвечается текстом
    old_types = pvp_module.GAME_TYPES
    pvp_module.GAME_TYPES = ("quiz",)

    # вызов от первого, принятие вторым
    code = await pvp_module.create_challenge(3001)
    check(bool(code), f"код вызова создан: {code}")

    accept_msg = FakeMessage(f"/start pvp_{code}", user_b)
    await pvp_handlers.accept_flow(accept_msg, fake_bot, code)

    for player in (3001, 3002):
        row = await db.get_active_quest(player)
        check(row is not None, f"у игрока {player} есть квест матча")
    check(len(fake_bot.sent) >= 2, f"квест отправлен обоим: {len(fake_bot.sent)}")

    # первый игрок отвечает - должен сработать путь PvP
    row = await db.get_active_quest(3001)
    payload = json.loads(row["payload"])
    message = FakeMessage("/quest", user_a)
    await games.on_game_callback(
        FakeCallback(f"g:{row['id']}:{payload['correct']}", user_a, message),
        state,
        fake_bot,
    )

    announced = [chat for chat, _ in fake_bot.sent]
    check(3002 in announced, f"сопернику объявили результат: {announced}")
    pvp_module.GAME_TYPES = old_types


async def test_pvp_from_menu(db: Database) -> None:
    """Вызов на бой из меню создаёт нажавший, а не бот.

    Регрессия: в сообщении с меню автор - бот, и код брал
    message.from_user.id. Из-за этого все вызовы создавались от имени
    бота, и принять их было невозможно.
    """
    print("\n--- Сценарий: вызов на бой из меню ---")
    import bot.pvp as pvp_module
    from bot.handlers import pvp as pvp_handlers

    player = FakeUser(3101)
    fake_bot = FakeBot()

    await db.create_user(3101)
    await db.set_nickname(3101, "Вызывающий")

    old_types = pvp_module.GAME_TYPES
    pvp_module.GAME_TYPES = ("quiz",)

    # сообщение с меню написал бот - как и бывает на самом деле
    menu_message = FakeMessage("/start", player)
    menu_message.from_user = FakeUser(999, username="questbot_bot", full_name="QuestBot")

    await pvp_handlers.create_flow(
        menu_message, fake_bot, edit=True, player_id=player.id
    )

    rows = []
    async with db.db.execute(
        "SELECT player1, player2 FROM pvp_matches ORDER BY id DESC LIMIT 1"
    ) as cur:
        rows = list(await cur.fetchall())
    check(bool(rows), "вызов создан")
    if rows:
        check(
            rows[0]["player1"] == 3101,
            f"вызов от нажавшего, а не от бота: {rows[0]['player1']}",
        )

    pvp_module.GAME_TYPES = old_types


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

    # 2. Сложность теперь адаптивная - выбор убран
    import bot.adaptive as adaptive_module

    level = await adaptive_module.current_level(user.id)
    check(level in ("easy", "medium", "hard"),
          f"адаптивный уровень определён: {level}")

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
    await profile.cmd_profile(profile_msg, fake_bot)
    check("профиль" in profile_msg.last_text.lower(), "профиль построен")

    top_msg = FakeMessage("/top", user)
    await ranking.cmd_top(top_msg, fake_bot)
    check("рейтинг" in top_msg.last_text.lower(), "рейтинг построен")
    check("Вася" in top_msg.last_text, "игрок есть в рейтинге")

    # 9–10. Команды
    diff_msg = FakeMessage("/difficulty", user)
    await common.cmd_difficulty(diff_msg, fake_bot)
    check(bool(diff_msg.sent), "команда смены сложности отвечает")

    help_msg = FakeMessage("/help", user)
    await common.cmd_help(help_msg, fake_bot)
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
        FakeCallback(f"g:{quest_row['id']}:{wrong_index}", user, message),
        state,
        fake_bot,
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


    patch_db(db)

    try:
        for game_type in GAMES:
            await run_flow(db, game_type)
        await test_failure(db)
        await test_pvp(db)
        await test_pvp_from_menu(db)
    finally:
        await db.close()

    print("\n" + "=" * 56)
    print(TALLY.summary())
    print("=" * 56)
    sys.exit(1 if TALLY.failed else 0)


if __name__ == "__main__":
    asyncio.run(main())

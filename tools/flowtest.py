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
from bot.games import GAME_TYPES  # noqa: E402
from bot.handlers import common, games, profile, quests, ranking  # noqa: E402
from bot.states import AskQuestion, Onboarding  # noqa: E402
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

    if game_type in ("quiz", "fast", "userquiz"):
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
    user = FakeUser(1000 + list(GAME_TYPES).index(game_type))
    state = FSMContext(storage=storage, key=user.id)
    fake_bot = FakeBot()
    message = FakeMessage("/start", user)

    # Форсируем тип мини-игры, чтобы проверить каждую
    import bot.services as services_module
    services_module.GAME_TYPES = (game_type,)
    services_module.USER_QUESTION_CHANCE = 0.0

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
    services_module.USER_QUESTION_CHANCE = 0.0

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


async def test_user_question(db: Database) -> None:
    """Полный цикл: игрок предложил вопрос, админ одобрил, вопрос выпал."""
    print("\n--- Сценарий: свой вопрос ---")
    import bot.admin as admin_module
    import bot.services as services_module
    from bot.handlers import admin as admin_handlers
    from bot.handlers import ask as ask_handlers

    storage = MemoryStorage()
    author = FakeUser(4001)
    player = FakeUser(4002)
    admin_user = FakeUser(9001)
    state = FSMContext(storage=storage, key=author.id)
    player_state = FSMContext(storage=storage, key=player.id)
    fake_bot = FakeBot()

    await db.create_user(author.id)
    await db.set_nickname(author.id, "Автор")
    await db.create_user(player.id)
    await db.set_nickname(player.id, "Игрок")

    old_admins = admin_module.ADMIN_IDS
    old_chance = services_module.USER_QUESTION_CHANCE
    old_types = services_module.GAME_TYPES
    admin_module.ADMIN_IDS = (admin_user.id,)
    services_module.USER_QUESTION_CHANCE = 0.0
    services_module.GAME_TYPES = ("quiz",)

    try:
        home = FakeMessage("/ask", author)
        await ask_handlers.cmd_ask(home, fake_bot)
        check("свой вопрос" in home.last_text.lower(), "открыт раздел вопросов")

        screen = FakeMessage("/ask", author)
        await ask_handlers.on_ask_new(
            FakeCallback("ask:new", author, screen), state
        )
        check(
            await state.get_state() == AskQuestion.waiting_question.state,
            "начат ввод вопроса",
        )

        await ask_handlers.on_question_text(
            FakeMessage("Столица Австралии?", author), state, fake_bot
        )
        await ask_handlers.on_answer_text(
            FakeMessage("Канберра", author), state, fake_bot
        )
        await ask_handlers.on_options_text(
            FakeMessage("Сидней, Мельбурн, Перт", author), state, fake_bot
        )
        await ask_handlers.on_category_text(
            FakeMessage("География", author), state, fake_bot
        )
        screen = FakeMessage("", author)
        await ask_handlers.on_difficulty_callback(
            FakeCallback("ask:diff:medium", author, screen), state, fake_bot
        )

        rows = await db.get_user_questions(author.id)
        check(len(rows) == 1, f"вопрос сохранён: {len(rows)}")
        question_id = rows[0]["id"] if rows else 0
        check(rows and rows[0]["status"] == "pending", "вопрос ждёт проверки")
        check(
            rows and json.loads(rows[0]["options"]) == ["Сидней", "Мельбурн", "Перт"],
            "варианты ответа сохранены",
        )

        admin_msg = FakeMessage("/moderate", admin_user)
        await admin_handlers.cmd_moderate(admin_msg)
        check(str(question_id) in admin_msg.last_text, "вопрос виден в очереди")

        card = FakeMessage("/admin", admin_user)
        await admin_handlers.on_question_moderation(
            FakeCallback(f"qmod:view:{question_id}", admin_user, card), fake_bot
        )
        check(
            "Столица Австралии" in card.edited[-1][0],
            "карточка показывает вопрос",
        )
        check(
            "Канберра" in card.edited[-1][0],
            "карточка показывает верный ответ",
        )

        await admin_handlers.on_question_moderation(
            FakeCallback(f"qmod:approve:{question_id}", admin_user, card), fake_bot
        )
        row = await db.get_user_question(question_id)
        check(row["status"] == "approved", "вопрос одобрен")
        check(
            any(chat_id == author.id for chat_id, _ in fake_bot.sent),
            "автору сообщили об одобрении",
        )

        # Вопрос автора не должен выпасть ему же.
        services_module.USER_QUESTION_CHANCE = 1.0
        await services_module.start_quest(author.id)
        own_quest = await db.get_active_quest(author.id)
        check(
            own_quest is not None and own_quest["game_type"] != "userquiz",
            "автор не получает свой вопрос",
        )

        # Другому игроку вопрос выпадает как отдельная игра.
        services_module.USER_QUESTION_CHANCE = 1.0
        result = await services_module.start_quest(player.id)
        check(not result.blocked, "вопрос выдан игроку")
        quest_row = await db.get_active_quest(player.id)
        check(
            quest_row is not None and quest_row["game_type"] == "userquiz",
            "тип игры - вопрос игрока",
        )
        payload = json.loads(quest_row["payload"])
        check(payload["q"] == "Столица Австралии?", "текст вопроса совпадает")
        check(
            payload["options"][payload["correct"]] == "Канберра",
            "верный вариант на месте",
        )

        await games.on_game_callback(
            FakeCallback(
                f"g:{quest_row['id']}:{payload['correct']}",
                player,
                FakeMessage("/quest", player),
            ),
            player_state,
            fake_bot,
        )
        player_row = await db.get_user(player.id)
        check(player_row["quests_done"] == 1, "вопрос засчитан как квест")
        check(player_row["points"] > 0, "за ответ начислены очки")

        # Отклонение тоже уведомляет автора.
        rejected_id = await db.add_user_question(
            player.id,
            "Вопрос, который не подойдёт",
            "Да",
            ["Нет", "Может", "Не знаю"],
            "Тест",
            "easy",
        )
        await admin_handlers.on_question_moderation(
            FakeCallback(f"qmod:reject:{rejected_id}", admin_user, card), fake_bot
        )
        rejected = await db.get_user_question(rejected_id)
        check(rejected["status"] == "rejected", "вопрос отклонён")
        check(
            any(chat_id == player.id for chat_id, _ in fake_bot.sent),
            "автору сообщили об отказе",
        )

        for index in range(3):
            await db.add_user_question(
                author.id,
                f"Лимит {index}",
                "Да",
                ["Нет", "Может", "Не знаю"],
                "Тест",
                "easy",
            )
        check(not await ask_handlers._can_ask(author.id), "лимит 3 вопроса работает")
    finally:
        admin_module.ADMIN_IDS = old_admins
        services_module.USER_QUESTION_CHANCE = old_chance
        services_module.GAME_TYPES = old_types


async def main() -> None:
    print("=" * 56)
    print("  QuestBot — интеграционный тест")
    print("=" * 56)

    db = Database(":memory:")
    await db.connect()


    patch_db(db)

    try:
        for game_type in GAME_TYPES:
            await run_flow(db, game_type)
        await test_failure(db)
        await test_pvp(db)
        await test_pvp_from_menu(db)
        await test_user_question(db)
    finally:
        await db.close()

    print("\n" + "=" * 56)
    print(TALLY.summary())
    print("=" * 56)
    sys.exit(1 if TALLY.failed else 0)


if __name__ == "__main__":
    asyncio.run(main())

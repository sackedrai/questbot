"""Локальная проверка игровой логики и базы данных.

Запуск: python tools/selftest.py
Сеть и токен не нужны.
"""

from __future__ import annotations

import asyncio
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Консоль Windows по умолчанию живёт в cp1251/cp1252 — переключаем на UTF-8
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # pragma: no cover
        pass

from bot import content  # noqa: E402
from bot.config import BASE_POINTS  # noqa: E402
from bot.db import Database  # noqa: E402
from bot.games import GAMES, Quest, get_game  # noqa: E402
from bot.scoring import calculate_points, level_for_points, progress_bar  # noqa: E402

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


def section(title: str) -> None:
    print(f"\n{title}")
    print("-" * len(title))


def test_content() -> None:
    section("Контент")
    check(len(content.QUIZ) >= 50, f"викторин: {len(content.QUIZ)}")
    check(len(content.FAST_QUIZ) >= 20, f"быстрых вопросов: {len(content.FAST_QUIZ)}")
    check(len(content.RIDDLES) >= 20, f"загадок: {len(content.RIDDLES)}")
    check(len(content.WORDS) >= 30, f"слов: {len(content.WORDS)}")
    check(len(content.TIMELINE_SETS) >= 8, f"наборов хронологии: {len(content.TIMELINE_SETS)}")

    valid = all(
        len(item["options"]) == 4
        and 0 <= item["correct"] < 4
        and item["diff"] in ("easy", "medium", "hard")
        for item in content.QUIZ
    )
    check(valid, "все викторины корректны (4 варианта, верный индекс, сложность)")

    valid_fast = all(len(i["options"]) == 4 and 0 <= i["correct"] < 4 for i in content.FAST_QUIZ)
    check(valid_fast, "все быстрые вопросы корректны")

    valid_riddles = all(i["answers"] and i["hint"] for i in content.RIDDLES)
    check(valid_riddles, "у всех загадок есть ответы и подсказка")

    valid_sets = all(len(s) == 4 for s in content.TIMELINE_SETS)
    check(valid_sets, "все наборы хронологии содержат 4 события")

    sorted_sets = all(
        all(a["year_num"] < b["year_num"] for a, b in zip(s, s[1:]))
        for s in content.TIMELINE_SETS
    )
    check(sorted_sets, "все наборы хронологии идут строго по возрастанию дат")

    dupes = len(content.QUIZ) - len({i["q"] for i in content.QUIZ})
    check(dupes == 0, f"нет повторяющихся вопросов (дублей: {dupes})")


def test_scoring() -> None:
    section("Очки")
    points, reasons = calculate_points(difficulty="easy", streak=0)
    check(points == BASE_POINTS["easy"], f"базовые очки за лёгкий: {points}")

    points, _ = calculate_points(difficulty="hard", streak=0)
    check(points == BASE_POINTS["hard"], f"базовые очки за сложный: {points}")

    fast, _ = calculate_points(difficulty="medium", streak=0, elapsed=2, timed=True)
    slow, _ = calculate_points(difficulty="medium", streak=0, elapsed=60, timed=True)
    check(fast > slow, f"скорость даёт больше очков ({fast} > {slow})")

    streak_points, reasons = calculate_points(difficulty="medium", streak=6)
    check(any("Серия" in label for label, _value in reasons), "бонус за серию начисляется")

    hinted, _ = calculate_points(difficulty="medium", streak=0, hint_used=True)
    check(hinted < BASE_POINTS["medium"], f"подсказка уменьшает очки ({hinted})")

    risky, _ = calculate_points(difficulty="medium", streak=0, risky=True)
    check(risky == BASE_POINTS["medium"] * 2, f"рискованный квест удваивает ({risky})")

    level, in_level, need = level_for_points(0)
    check(level == 1, f"нулевой уровень: {level}")
    level2, _, _ = level_for_points(1500)
    check(level2 > 1, f"уровень растёт: {level2}")
    check(progress_bar(5, 10) == "█████░░░░░", "полоска прогресса считается")


async def test_games() -> None:
    section("Мини-игры")
    rng = random.Random(42)

    # --- викторина ---
    game = get_game("quiz")
    payload = await game.build("medium", rng)
    quest = Quest(id=1, tg_id=1, day="2026-01-01", game_type="quiz",
                  difficulty="medium", payload=payload)
    render = game.render(quest)
    rows = render.markup.inline_keyboard if render.markup else []
    check(len(rows) == 5 and rows[-1][0].text == "⏭ Сдаться",
          "викторина: 4 варианта + кнопка сдаться")

    result = await game.on_choice(quest, str(payload["correct"]))
    check(result.outcome == "solved", "викторина: верный ответ засчитан")

    wrong_index = (payload["correct"] + 1) % 4
    result = await game.on_choice(quest, str(wrong_index))
    check(result.outcome == "failed", "викторина: неверный ответ проваливает квест")

    # --- быстрый квест ---
    fast = get_game("fast")
    check(fast.timed is True, "быстрый квест помечен как timed")
    payload = await fast.build("medium", rng)
    quest = Quest(id=2, tg_id=1, day="2026-01-01", game_type="fast",
                  difficulty="medium", payload=payload)
    result = await fast.on_choice(quest, str(payload["correct"]))
    check(result.outcome == "solved", "быстрый квест: верный ответ засчитан")

    # --- хронология ---
    timeline = get_game("timeline")
    payload = await timeline.build("medium", rng)
    quest = Quest(id=3, tg_id=1, day="2026-01-01", game_type="timeline",
                  difficulty="medium", payload=payload)
    render = timeline.render(quest)
    rows = render.markup.inline_keyboard if render.markup else []
    check(len(rows) == 5 and rows[-1][0].text == "⏭ Сдаться",
          "хронология: 4 события + кнопка сдаться")

    # неверный выбор — не самое раннее событие
    items = payload["items"]
    wrong_pick = max(range(len(items)), key=lambda i: items[i]["year"])
    result = await timeline.on_choice(quest, str(wrong_pick))
    check(result.outcome is None, "хронология: неверный порядок не завершает квест сразу")
    check(payload["mistakes"] == 1, "хронология: ошибка засчитана")

    # проходим целиком
    outcome = None
    for _ in range(10):
        collected = payload["collected"]
        remaining = [i for i in range(len(items)) if i not in collected]
        if not remaining:
            break
        pick = min(remaining, key=lambda i: items[i]["year_num"])
        result = await timeline.on_choice(quest, str(pick))
        outcome = result.outcome
    check(outcome == "solved", "хронология: полная сортировка засчитывается")

    # --- загадка ---
    riddle = get_game("riddle")
    payload = await riddle.build("medium", rng)
    quest = Quest(id=4, tg_id=1, day="2026-01-01", game_type="riddle",
                  difficulty="medium", payload=payload)
    result = await riddle.on_text(quest, payload["answers"][0].upper())
    check(result.outcome == "solved", "загадка: ответ без учёта регистра засчитан")

    payload = await riddle.build("medium", rng)
    quest = Quest(id=5, tg_id=1, day="2026-01-01", game_type="riddle",
                  difficulty="medium", payload=payload)
    result = await riddle.on_text(quest, "точно неправильный ответ")
    check(result.outcome is None, "загадка: неверный ответ продолжает игру")
    check(payload["tries"] == 1, "загадка: попытка засчитана")

    # подсказка
    payload["tries"] = 2
    result = await riddle.on_choice(quest, "hint")
    check(result.hint_used is True, "загадка: подсказка помечается как использованная")

    # --- угадай слово ---
    word_game = get_game("word")
    payload = await word_game.build("medium", rng)
    quest = Quest(id=6, tg_id=1, day="2026-01-01", game_type="word",
                  difficulty="medium", payload=payload)
    target = payload["word"]
    result = await word_game.on_text(quest, target.lower())
    check(result.outcome == "solved", "угадай слово: слово целиком засчитано")

    payload = await word_game.build("medium", rng)
    quest = Quest(id=7, tg_id=1, day="2026-01-01", game_type="word",
                  difficulty="medium", payload=payload)
    alphabet = "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"
    wrong_letters = [c for c in alphabet if c.upper() not in payload["word"]]
    result = await word_game.on_text(quest, wrong_letters[0])
    check(result.outcome is None and payload["lives"] < 7,
          "угадай слово: неверная буква отнимает жизнь")

    # повтор той же буквы жизнь не отнимает
    lives_before = payload["lives"]
    await word_game.on_text(quest, wrong_letters[0])
    check(payload["lives"] == lives_before, "угадай слово: повтор буквы не отнимает жизнь")

    outcome = None
    for letter in wrong_letters[1:]:
        payload["lives"] = 1
        result = await word_game.on_text(quest, letter)
        if result.outcome:
            outcome = result.outcome
            break
    check(outcome == "failed", "угадай слово: конец жизней проваливает квест")

    check(set(GAMES) == {"quiz", "fast", "timeline", "riddle", "word"},
          f"зарегистрировано 5 игр: {sorted(GAMES)}")


async def test_database() -> None:
    section("База данных")
    db = Database(":memory:")
    await db.connect()

    await db.create_user(1, "ivan", "Иван")
    await db.create_user(2, "petr", "Пётр")
    check(await db.get_user(1) is not None, "пользователь создан")

    await db.set_nickname(1, "Иван")
    await db.set_nickname(2, "Пётр")
    await db.set_difficulty(1, "medium")

    streak = await db.touch_day(1, "2026-01-01")
    check(streak == 1, f"первый день серии: {streak}")
    streak = await db.touch_day(1, "2026-01-02")
    check(streak == 2, f"второй день подряд: {streak}")
    streak = await db.touch_day(1, "2026-01-02")
    check(streak == 2, f"повтор в тот же день не увеличивает серию: {streak}")
    streak = await db.touch_day(1, "2026-01-05")
    check(streak == 1, f"пропуск сбрасывает серию: {streak}")

    await db.add_result(1, 50, True)
    await db.add_result(2, 30, True)
    user = await db.get_user(1)
    check(user["points"] == 50, f"очки начислены: {user['points']}")
    check(user["quests_done"] == 1, f"счётчик квестов: {user['quests_done']}")

    await db.add_result(1, -100, False)
    user = await db.get_user(1)
    check(user["points"] == 0, f"очки не уходят в минус: {user['points']}")

    quest_id = await db.create_quest(1, "2026-01-01", "quiz", "medium", {"q": "?"}, risky=False)
    check(quest_id > 0, f"квест создан: id={quest_id}")
    await db.finish_quest(quest_id, 40, "done")

    # игрок с нулём очков в рейтинг не попадает
    rows = await db.leaderboard(scope="all")
    check(all(row["tg_id"] != 1 for row in rows),
          "игрок без очков не попадает в рейтинг")

    await db.add_result(1, 120, True)
    rows = await db.leaderboard(scope="all")
    check(len(rows) >= 1, f"рейтинг построен: {len(rows)} строк")
    check(rows[0]["tg_id"] == 1, "лидер рейтинга — игрок с очками")

    place = await db.user_position(1, "all")
    check(place == 1, f"место игрока: {place}")

    summary = await db.daily_summary(1, "2026-01-01")
    check(summary["done"] == 1, f"итоги дня: {dict(summary)}")

    check(await db.count_quests_today(1, "2026-01-01", risky=False) == 1,
          "квест дня засчитан")
    check(await db.count_quests_today(1, "2026-01-01", risky=True) == 0,
          "рискованный квест не засчитан")

    await db.close()


async def test_tracking_session() -> None:
    """Сессия должна запоминать каждое отправленное сообщение."""
    section("Трекинг сообщений")

    from datetime import datetime, timezone

    import aiogram.client.session.aiohttp as aiohttp_session
    from aiogram.methods import SendMessage
    from aiogram.types import Chat, Message as TelegramMessage

    from bot.net import TrackingSession
    from bot import net as net_module

    # изолируемся от боевой базы
    original_db = net_module.db
    db = Database(":memory:")
    await db.connect()
    net_module.db = db

    original = aiohttp_session.AiohttpSession.make_request

    async def fake_request(self, bot, method, timeout=None):
        return TelegramMessage(
            message_id=777,
            date=datetime.now(timezone.utc),
            chat=Chat(id=555, type="private"),
        )

    aiohttp_session.AiohttpSession.make_request = fake_request
    try:
        session = TrackingSession()
        await session.make_request(None, SendMessage(chat_id=555, text="привет"))
        tracked = await db.chat_messages(555)
    finally:
        aiohttp_session.AiohttpSession.make_request = original
        net_module.db = original_db
        await db.close()

    check(tracked == [777], f"сообщение отслежено: {tracked}")


async def test_daily_logic() -> None:
    """Правило: следующий квест - ровно через 24 часа после прошлого."""
    section("Ежедневная логика")

    import bot.daily as daily

    db = Database(":memory:")
    await db.connect()
    daily.db = db
    await db.create_user(1, "u", "U")

    avail = await daily.availability(1)
    check(avail.state == "due", f"первый квест доступен сразу: {avail.state}")

    quest_id = await db.create_quest(1, "2026-10-21", "quiz", "easy", {"q": "?"})
    await db.finish_quest(quest_id, 20, "done")

    avail = await daily.availability(1)
    check(avail.state == "cooldown",
          f"после прохождения - кулдаун: {avail.state}")
    check(abs(avail.seconds_left - 86400) < 120,
          f"осталось примерно 24 часа: {avail.seconds_left} сек")
    check("24 ч" in avail.human_left() or "23 ч" in avail.human_left(),
          f"человекообразно: {avail.human_left()}")

    await db.set_tz(1, 5)
    avail = await daily.availability(1)
    check(avail.tz_offset == 5, f"часовой пояс сохранён: {avail.tz_offset}")

    # незаконченный квест блокирует выдачу
    await db.create_quest(1, "2026-10-21", "quiz", "easy", {"q": "?"})
    avail = await daily.availability(1)
    check(avail.state == "active",
          f"незаконченный квест блокирует: {avail.state}")

    await db.close()


async def main() -> None:
    print("=" * 56)
    print("  QuestBot — самопроверка")
    print("=" * 56)
    test_content()
    test_scoring()
    await test_games()
    await test_database()
    await test_tracking_session()
    await test_daily_logic()

    print("\n" + "=" * 56)
    print(f"  Пройдено: {PASSED}   Провалено: {FAILED}")
    print("=" * 56)
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    asyncio.run(main())

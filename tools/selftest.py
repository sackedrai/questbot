"""Локальная проверка игровой логики и базы данных.

Запуск: python tools/selftest.py
Сеть и токен не нужны.
"""

from __future__ import annotations

import asyncio
import random
import sys
import time
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
from tools._testing import Tally, patch_db  # noqa: E402

PASSED = 0
FAILED = 0


TALLY = Tally()
check = TALLY.check
section = TALLY.section


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

    valid_sets = all(4 <= len(s) <= 5 for s in content.TIMELINE_SETS)
    check(valid_sets, "все наборы хронологии содержат 4-5 событий")

    valid_truth = all(
        i.get("t")
        and isinstance(i.get("a"), bool)
        and i.get("why")
        and i.get("diff") in ("easy", "medium", "hard")
        for i in content.TRUE_FALSE
    )
    check(valid_truth, "все утверждения корректны (текст, да/нет, объяснение)")

    # в каждом пуле должны быть все три сложности
    for label, items in (
        ("викторина", content.QUIZ),
        ("правда/ложь", content.TRUE_FALSE),
    ):
        levels = {i.get("diff") for i in items}
        check(
            {"easy", "medium", "hard"} <= levels,
            f"в пуле «{label}» есть все сложности: {sorted(levels)}",
        )

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
    check(need == 200, f"до второго уровня 200 очков: {need}")
    check(level_for_points(199)[0] == 1, "199 очков - ещё первый уровень")
    check(level_for_points(200)[0] == 2, "200 очков - второй уровень")
    check(level_for_points(500)[0] == 3, "500 очков - третий уровень")
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
    labels = [b.text for b in rows[-1]] if rows else []
    check(
        len(rows) == 5 and "Сдаться" in labels[0] and "меню" in labels[1],
        f"викторина: 4 варианта + сдаться + в меню: {labels}",
    )

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
    labels = [b.text for b in rows[-1]] if rows else []
    check(
        len(rows) == 5 and "Сдаться" in labels[0] and "меню" in labels[1],
        f"хронология: 4 события + сдаться + в меню: {labels}",
    )

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

    check(
        set(GAMES) == {"quiz", "fast", "timeline", "riddle", "word", "truth", "math"},
        f"зарегистрировано 7 игр: {sorted(GAMES)}",
    )


async def test_database() -> None:
    section("База данных")
    db = Database(":memory:")
    await db.connect()

    await db.create_user(1)
    await db.create_user(2)
    check(await db.get_user(1) is not None, "пользователь создан")
    # @username и имя не храним - бэкап базы публичный
    raw = await db.get_user(1)
    check((raw["username"] or "") == "" and (raw["display_name"] or "") == "",
          "личные поля не сохраняются при создании")

    # данные, оставшиеся от старых версий, вычищаются
    await db.set_nickname(1, "Иван")
    await db.db.execute(
        "UPDATE users SET username = 'ivan', display_name = 'Иван' WHERE tg_id = 1"
    )
    await db.db.commit()
    purged = await db.purge_personal_fields()
    check(purged == 1, f"старые личные поля вычищены: {purged}")
    row = await db.get_user(1)
    check((row["username"] or "") == "" and (row["display_name"] or "") == "",
          "после очистки личных полей не осталось")
    check(row["nickname"] == "Иван", "ник при этом сохранился")

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
    patch_db(db)

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
    patch_db(db)
    await db.create_user(1)

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

    # квест старше суток протухает
    import time as _time

    await db.db.execute(
        "UPDATE quests SET started_at = ? WHERE tg_id = ?",
        (_time.time() - 90000, 1),
    )
    await db.db.commit()
    avail = await daily.availability(1)
    check(avail.state != "active",
          f"залежавшийся квест протухает: {avail.state}")
    rows = await db.db.execute(
        "SELECT status FROM quests WHERE tg_id = ?", (1,)
    )
    statuses = [row["status"] for row in await rows.fetchall()]
    check("expired" in statuses, f"протухший помечен: {statuses}")

    await db.close()


async def test_adaptive_and_notify() -> None:
    """Адаптивная сложность и переключатель уведомлений."""
    section("Адаптив и уведомления")

    import random

    import bot.adaptive as adaptive

    db = Database(":memory:")
    await db.connect()
    patch_db(db)
    await db.create_user(1)

    level = await adaptive.pick_difficulty(1, random.Random(1))
    check(level == "easy", f"новичку начинаем легко: {level}")

    for _ in range(6):
        quest_id = await db.create_quest(1, "2026-10-21", "quiz", "easy", {"q": "?"})
        await db.finish_quest(quest_id, 30, "done")
    level = await adaptive.current_level(1)
    check(level == "hard", f"после серии успехов - сложнее: {level}")

    for _ in range(6):
        quest_id = await db.create_quest(1, "2026-10-21", "quiz", "easy", {"q": "?"})
        await db.finish_quest(quest_id, 0, "failed")
    level = await adaptive.current_level(1)
    check(level == "easy", f"после серии провалов - легче: {level}")

    check(await db.notify_enabled(1) is True, "уведомления включены по умолчанию")
    await db.set_notify(1, False)
    check(await db.notify_enabled(1) is False, "уведомления выключаются")
    await db.set_notify(1, True)
    check(await db.notify_enabled(1) is True, "уведомления включаются обратно")

    await db.close()


async def test_backup() -> None:
    """Бэкап базы в git: шифрование, коммит и восстановление."""
    section("Бэкап в репозитории")

    import os
    import subprocess
    import tempfile

    from cryptography.fernet import Fernet

    from bot.backup import backup_database, restore_from_repo

    old_key = os.environ.get("BACKUP_KEY")
    os.environ["BACKUP_KEY"] = Fernet.generate_key().decode("ascii")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "work"
            repo.mkdir()
            bare = Path(tmp) / "origin.git"
            subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
            subprocess.run(
                ["git", "remote", "add", "origin", str(bare)], cwd=repo, check=True
            )

            db = repo / "data" / "questbot.db"
            db.parent.mkdir(exist_ok=True)
            db.write_bytes(b"first version")

            status = await backup_database(repo, db, min_hours=0)
            check("запушен" in status or "закоммичено" in status,
                  f"база закоммичена: {status}")

            enc = repo / "backup" / "questbot.db.enc"
            check(enc.exists(), "зашифрованная копия появилась в backup/")
            check(not (repo / "backup" / "questbot.db").exists(),
                  "открытая копия базы не создаётся")
            check(b"first version" not in enc.read_bytes(),
                  "в файле бэкапа нет открытых данных")

            # декодируем сами: text=True использует локаль системы,
            # а git отдаёт UTF-8 с кириллицей (в cp1252 это падает)
            committed = subprocess.run(
                ["git", "log", "--oneline"], cwd=repo, capture_output=True
            ).stdout.decode("utf-8", "replace")
            check("backup:" in committed, f"коммит с бэкапом создан: {committed.strip()[:60]}")

            shown = subprocess.run(
                ["git", "show", "HEAD:backup/questbot.db.enc"],
                cwd=repo, capture_output=True,
            ).stdout
            check(b"first version" not in shown,
                  "в истории git нет открытой базы")

            # восстановление в чистую рабочую папку
            db.unlink()
            status = await restore_from_repo(repo, db)
            check(db.exists(), f"база восстановлена из репозитория: {status}")
            check(db.read_bytes() == b"first version", "содержимое совпадает")

            # троттлинг: сразу после коммита повторный бэкап не делается
            db.write_bytes(b"second version")
            status = await backup_database(repo, db, min_hours=4)
            check("пока не коммичу" in status, f"троттлинг работает: {status}")

            # неверный ключ - восстановление не должно ломать бота
            os.environ["BACKUP_KEY"] = Fernet.generate_key().decode("ascii")
            db.unlink()
            status = await restore_from_repo(repo, db)
            check("не удалось расшифровать" in status,
                  f"чужим ключом база не открывается: {status}")
            check(not db.exists(), "при неверном ключе база не создаётся")

            # без ключа бэкап делаться не должен - данные не утекают
            os.environ.pop("BACKUP_KEY", None)
            db.write_bytes(b"third version")
            status = await backup_database(repo, db, min_hours=0)
            check("BACKUP_KEY" in status, f"без ключа бэкап пропущен: {status}")
    finally:
        if old_key is None:
            os.environ.pop("BACKUP_KEY", None)
        else:
            os.environ["BACKUP_KEY"] = old_key


def test_watchdog_logic() -> None:
    """Сторож: когда перезапускать, когда тревожить."""
    section("Сторож")

    from tools.watchdog import (
        MAX_RESTARTS,
        STALE_HOURS,
        Run,
        State,
        evaluate,
    )

    now = 1_700_000_000.0
    fresh = Run(
        id=1, status="completed", conclusion="success",
        created_at=now - 3600, event="workflow_dispatch"
    )
    old = Run(
        id=2, status="completed", conclusion="success",
        created_at=now - 5 * 3600, event="workflow_dispatch"
    )
    failed = Run(
        id=3, status="completed", conclusion="failure",
        created_at=now - 600, event="workflow_dispatch"
    )

    decision = evaluate([fresh], State(), now=now)
    check(decision.action == "none",
          f"свежий успешный прогон - всё спокойно: {decision.action}")

    decision = evaluate([old], State(), now=now)
    check(decision.action == "restart",
          f"старый прогон - перезапускаем: {decision.action}")

    decision = evaluate([failed], State(), now=now)
    check(decision.action == "restart",
          f"упавший прогон - перезапускаем: {decision.action}")

    state = State(fails=MAX_RESTARTS, last_alert=0)
    decision = evaluate([failed], state, now=now)
    check(decision.action == "alert" and decision.should_alert,
          f"после нескольких попыток - тревога: {decision.action}")

    state = State(fails=MAX_RESTARTS, last_alert=now - 60)
    decision = evaluate([failed], state, now=now)
    check(decision.action == "alert" and not decision.should_alert,
          "недавно тревожили - молчим")

    # идущий прогон - бот жив, даже если последний успешный был давно
    running = Run(
        id=4, status="in_progress", conclusion="",
        created_at=now - 300, event="workflow_dispatch"
    )
    decision = evaluate([running], State(), now=now)
    check(decision.action == "none",
          f"идущий прогон считаем живым: {decision.action}")

    check(STALE_HOURS > 2.0,
          f"порог 'бот мёртв' больше длительности круга: {STALE_HOURS} ч")

    # разбор дат из API GitHub
    from tools.watchdog import _parse_time

    stamp = _parse_time("2026-10-20T20:05:07Z")
    check(stamp > 1_700_000_000,
          f"дата прогона разобрана: {stamp}")
    check(_parse_time(None) == 0.0, "пустая дата не ломает разбор")

    # проверка здоровья по метрикам
    from tools.watchdog import ERROR_THRESHOLD, SELFCHECK_MAX_AGE, check_health

    now = 1_700_000_000.0
    check(check_health({}, now) == [], "без метрик - проблем нет")

    problems = check_health({"errors_count": str(ERROR_THRESHOLD)}, now)
    check(bool(problems), f"много ошибок - замечаем: {problems}")

    problems = check_health(
        {"selfcheck_ok_at": str(now - SELFCHECK_MAX_AGE - 60)}, now
    )
    check(bool(problems), f"самопроверка давно не шла - замечаем: {problems}")

    problems = check_health(
        {"errors_count": "0", "selfcheck_ok_at": str(now - 60)}, now
    )
    check(not problems, f"всё хорошо - не замечаем: {problems}")


async def test_error_counter() -> None:
    """Счётчик ошибок в обработчиках."""
    section("Счётчик ошибок")

    db = Database(":memory:")
    await db.connect()

    count = await db.count_error(window_seconds=3600)
    check(count == 1, f"первая ошибка: {count}")
    count = await db.count_error(window_seconds=3600)
    check(count == 2, f"вторая ошибка: {count}")
    check(await db.get_meta("errors_count") == "2", "счётчик сохранён в базе")

    # окно сбрасывается, когда проходит больше часа
    await db.set_meta("errors_window_start", "0")
    count = await db.count_error(window_seconds=3600)
    check(count == 1, f"окно сбросилось: {count}")

    await db.close()


async def test_rotator() -> None:
    """Ротатор контента: не выдаём пройденное повторно."""
    section("Ротатор контента")

    import random

    import bot.services as services
    from bot.games import get_game
    from bot.games.base import pick_unseen

    db = Database(":memory:")
    await db.connect()
    patch_db(db)
    patch_db(db)
    patch_db(db)

    try:
        # чистый помощник: пока пул не исчерпан - берём непроходимое
        pool = [{"q": "а"}, {"q": "б"}, {"q": "в"}]
        rng = random.Random(0)
        item, exhausted = pick_unseen(pool, lambda x: x["q"], rng, set())
        check(not exhausted and item["q"] in {"а", "б", "в"}, f"первый выбор: {item['q']}")
        item, exhausted = pick_unseen(pool, lambda x: x["q"], rng, {"а", "б"})
        check(item["q"] == "в" and not exhausted, f"выбрано непроходимое: {item['q']}")
        item, exhausted = pick_unseen(pool, lambda x: x["q"], rng, {"а", "б", "в"})
        check(exhausted, "банк исчерпан - сигнал игроку")

        # реальная выдача: 12 квестов одного типа - все разные
        await db.create_user(1)
        await db.set_nickname(1, "Тест")
        game = get_game("quiz")
        keys: list[str] = []
        for i in range(12):
            used = await db.used_item_keys(1)
            payload = await game.build("easy", random.Random(i), exclude=used)
            key = payload["_key"]
            keys.append(key)
            await db.create_quest(
                1, "2026-10-21", "quiz", "easy", payload, item_key=key
            )
        check(len(set(keys)) == 12, f"12 квестов - 12 разных заданий: {len(set(keys))}")
        check(await db.used_item_keys(1) == set(keys), "база помнит пройденные ключи")
        check(await db.count_used_items(1) == 12, "счётчик уникальных заданий: 12")

        # служебные квесты закрываем, чтобы они не перехватывали выдачу
        await db.db.execute(
            "UPDATE quests SET status = 'skipped' WHERE tg_id = 1 AND status = 'active'"
        )
        await db.db.commit()

        # сервисный путь: второй квест не повторяет первый
        q1 = await services.start_quest(1, game_type="quiz")
        check(q1.quest_id is not None, "первый квест выдан")
        row1 = await db.get_quest(q1.quest_id)
        # отматываем "прошёл 25 часов назад", чтобы обойти правило 24 часов
        await db.db.execute(
            "UPDATE quests SET finished_at = ? WHERE id = ?",
            (time.time() - 90000, q1.quest_id),
        )
        await db.db.execute(
            "UPDATE quests SET status = 'done' WHERE id = ?", (q1.quest_id,)
        )
        await db.db.commit()

        q2 = await services.start_quest(1, game_type="quiz")
        row2 = await db.get_quest(q2.quest_id)
        check(
            row1["item_key"] != row2["item_key"],
            f"второй квест другой: {row2['item_key']}",
        )
        check(bool(row2["item_key"]), "ключ задания сохранён в базе")
        check("_key" not in row2["payload"], "служебный ключ убран из payload")

        # когда все задания пройдены - честно говорим об этом
        used = await db.used_item_keys(1)
        payload = await game.build("easy", random.Random(7), exclude=used)
        check("_exhausted" in payload, "в payload есть признак исчерпания банка")

        # квесты, выданные до появления ротатора, получают ключ при старте
        old_id = await db.create_quest(
            1, "2026-10-20", "quiz", "easy", {"q": "Старый вопрос?"}
        )
        check((await db.get_quest(old_id))["item_key"] == "", "у старого квеста ключа нет")
        fixed = await services.backfill_item_keys()
        check(fixed == 1, f"ключ восстановлен: {fixed}")
        restored = (await db.get_quest(old_id))["item_key"]
        check(restored == "quiz:Старый вопрос?", f"ключ восстановлен верно: {restored}")
    finally:
        await db.close()


async def test_novice_level() -> None:
    """Новичку сложный уровень не достаётся."""
    section("Ограничение для новичка")

    import random

    import bot.adaptive as adaptive

    db = Database(":memory:")
    await db.connect()
    patch_db(db)
    await db.create_user(1)

    try:
        # одна удачная попытка - ещё новичок
        quest_id = await db.create_quest(1, "2026-10-21", "quiz", "easy", {"q": "?"})
        await db.finish_quest(quest_id, 30, "done")

        level = await adaptive.current_level(1)
        check(level != "hard", f"новичку не дают сложный уровень: {level}")
        check(level in ("easy", "medium"), f"уровень новичка: {level}")

        picked = await adaptive.pick_difficulty(1, random.Random(5))
        check(picked != "hard", f"и случайность не выдаст сложный: {picked}")

        # с шестью успехами - уже не новичок, сложный доступен
        for _ in range(6):
            quest_id = await db.create_quest(
                1, "2026-10-22", "quiz", "easy", {"q": "?"}
            )
            await db.finish_quest(quest_id, 30, "done")
        level = await adaptive.current_level(1)
        check(level == "hard", f"после серии успехов сложный уровень есть: {level}")
    finally:
        await db.close()


async def test_daily_pass_batch() -> None:
    """Массовый обход: квесты выдаются тем, кому положено."""
    section("Массовая раздача квестов")

    import bot.daily as daily

    class FakeBot:
        def __init__(self) -> None:
            self.sent: list[int] = []

        async def send_message(self, chat_id: int, text: str, **kwargs) -> None:
            self.sent.append(chat_id)

    db = Database(":memory:")
    await db.connect()
    patch_db(db)
    patch_db(db)
    patch_db(db)

    try:
        # игрок, которому квест положен давно
        await db.create_user(1)
        await db.set_nickname(1, "Первый")
        quest_id = await db.create_quest(1, "2026-10-18", "quiz", "easy", {"q": "?"})
        await db.finish_quest(quest_id, 10, "done")
        await db.db.execute(
            "UPDATE quests SET finished_at = ?, started_at = ? WHERE id = ?",
            (time.time() - 90000, time.time() - 90000, quest_id),
        )
        await db.db.commit()

        # игрок, у которого квест ещё не положен
        await db.create_user(2)
        await db.set_nickname(2, "Второй")
        quest_id = await db.create_quest(2, "2026-10-21", "quiz", "easy", {"q": "?"})
        await db.finish_quest(quest_id, 10, "done")

        # игрок с активным квестом
        await db.create_user(3)
        await db.set_nickname(3, "Третий")
        await db.create_quest(3, "2026-10-21", "quiz", "easy", {"q": "?"})

        # игрок с выключенными уведомлениями
        await db.create_user(4)
        await db.set_nickname(4, "Четвёртый")
        await db.set_notify(4, False)
        quest_id = await db.create_quest(4, "2026-10-18", "quiz", "easy", {"q": "?"})
        await db.finish_quest(quest_id, 10, "done")
        await db.db.execute(
            "UPDATE quests SET finished_at = ?, started_at = ? WHERE id = ?",
            (time.time() - 90000, time.time() - 90000, quest_id),
        )
        await db.db.commit()

        # одиночный расчёт: у кого-то квест положен, у кого-то нет
        moment = await daily.auto_moment(1)
        check(moment is not None, "момент автовыдачи посчитан")
        check(
            moment is not None and moment.timestamp() <= time.time() + 1,
            "игроку квест положен - момент в прошлом",
        )
        later = await daily.auto_moment(2)
        check(
            later is not None and later.timestamp() > time.time(),
            "у второго игрока квест ещё не положен",
        )
        check(await daily.auto_moment(3) is None, "у активного квеста момента нет")

        bot = FakeBot()
        issued = await daily.run_daily_pass(bot, max_wait=0)
        check(issued == 1, f"выдан один квест (тому, кому положен): {issued}")
        check(bot.sent == [1], f"квест получил нужный игрок: {bot.sent}")
    finally:
        await db.close()


async def test_migration_old_db() -> None:
    """Старая база без новых колонок должна открываться.

    Регрессия: индекс по новой колонке в SCHEMA ломал старые базы - бот
    падал при старте и при этом не завершался (висел поток aiosqlite).
    """
    section("Миграция старой базы")

    import sqlite3
    import tempfile

    import bot.db as db_module

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "old.db"
        con = sqlite3.connect(str(path))
        con.executescript(
            """
            CREATE TABLE users (
                tg_id INTEGER PRIMARY KEY, nickname TEXT, points INTEGER DEFAULT 0
            );
            CREATE TABLE quests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id INTEGER NOT NULL,
                day TEXT NOT NULL,
                game_type TEXT NOT NULL,
                difficulty TEXT NOT NULL,
                payload TEXT NOT NULL,
                points INTEGER DEFAULT 0,
                status TEXT DEFAULT 'active',
                risky INTEGER DEFAULT 0,
                started_at REAL DEFAULT 0,
                finished_at REAL DEFAULT 0
            );
            INSERT INTO users (tg_id, nickname) VALUES (5, 'Старый игрок');
            """
        )
        con.commit()
        con.close()

        db = Database(str(path))
        await db.connect()
        try:
            cur = await db.db.execute("PRAGMA table_info(quests)")
            cols = {row["name"] for row in await cur.fetchall()}
            check("item_key" in cols, "колонка item_key добавлена миграцией")
            cur = await db.db.execute("PRAGMA index_list(quests)")
            indexes = {row["name"] for row in await cur.fetchall()}
            check("idx_quests_user_key" in indexes, "индекс по item_key создан")
            user = await db.get_user(5)
            check(
                user is not None and user["nickname"] == "Старый игрок",
                "старые данные на месте",
            )
        finally:
            await db.close()

    # при ошибке схемы соединение должно закрываться, иначе процесс зависнет
    original = db_module.SCHEMA
    db_module.SCHEMA = original + "CREATE INDEX broken ON quests (нет_такой_колонки);"
    bad = Database(":memory:")
    try:
        await bad.connect()
        check(False, "ожидалась ошибка схемы")
    except Exception:
        check(bad._db is None, "после ошибки соединение закрыто")
    finally:
        db_module.SCHEMA = original


async def test_profile_and_top() -> None:
    """Профиль: время следующего квеста. Рейтинг: место игрока и соседи."""
    section("Профиль и рейтинг")

    import bot.services as services

    db = Database(":memory:")
    await db.connect()
    patch_db(db)
    patch_db(db)
    patch_db(db)
    patch_db(db)

    try:
        # 12 игроков, у каждого свои очки
        for i in range(1, 13):
            await db.create_user(100 + i)
            await db.set_nickname(100 + i, f"Игрок{i}")
            await db.db.execute(
                "UPDATE users SET points = ?, quests_done = ? WHERE tg_id = ?",
                (1000 - i * 50, i, 100 + i),
            )
        await db.db.commit()

        text, _ = await services.build_top_text("all", 112)
        check("Ты на <b>12</b>-м месте из 12" in text, "указано место игрока")
        check("Твои соседи" in text, "показаны соседи по рейтингу")
        check("◀" in text, "строка игрока выделена")

        text, _ = await services.build_top_text("all", 101)
        check("Ты на <b>1</b>-м месте из 12" in text, "место лидера")
        check("Твои соседи" not in text, "лидеру соседи не нужны")

        # профиль: квест только что пройден - видно время ожидания
        await db.create_user(200)
        await db.set_nickname(200, "Тестер")
        quest_id = await db.create_quest(
            200, "2026-10-21", "quiz", "easy", {"q": "?"}
        )
        await db.finish_quest(quest_id, 20, "done")
        await db.db.commit()
        profile = await services.build_profile_text(200)
        check("СЛЕДУЮЩИЙ КВЕСТ" in profile, "в профиле есть блок следующего квеста")
        check("через" in profile, "видно, сколько ждать")

        # квест положен давно - доступен прямо сейчас
        await db.db.execute(
            "UPDATE quests SET finished_at = ? WHERE id = ?",
            (time.time() - 90000, quest_id),
        )
        await db.db.commit()
        profile = await services.build_profile_text(200)
        check("Доступен прямо сейчас" in profile, "квест доступен")

        # есть незаконченный квест
        await db.create_user(201)
        await db.set_nickname(201, "Другой")
        await db.create_quest(201, "2026-10-21", "quiz", "easy", {"q": "?"})
        profile = await services.build_profile_text(201)
        check("незаконченный квест" in profile, "сказано про незаконченный квест")
    finally:
        await db.close()


async def test_auto_clean() -> None:
    """Авточистка: в чате остаётся только текущий экран."""
    section("Авточистка чата")

    from bot.utils import auto_clean, open_screen

    class FakeBot:
        def __init__(self) -> None:
            self.deleted: list[int] = []

        async def delete_messages(self, chat_id: int, ids: list[int]) -> None:
            self.deleted.extend(ids)

        async def delete_message(self, chat_id: int, message_id: int) -> None:
            self.deleted.append(message_id)

    class FakeMessage:
        def __init__(self, chat_id: int, message_id: int) -> None:
            self.chat = type("Chat", (), {"id": chat_id})()
            self.message_id = message_id
            self.sent: list[str] = []

        async def answer(self, text: str, reply_markup=None):
            self.sent.append(text)
            return self

    db = Database(":memory:")
    await db.connect()
    try:
        # раньше бот писал в этом чате
        await db.track_message(5, 10, "auto")
        await db.track_message(5, 11, "auto")
        await db.track_message(5, 12, "auto")

        bot = FakeBot()
        message = FakeMessage(5, 13)
        await open_screen(bot, message, db, "НОВЫЙ ЭКРАН")
        check(message.sent == ["НОВЫЙ ЭКРАН"], "экран отправлен")
        check(10 in bot.deleted and 12 in bot.deleted, "прошлые сообщения бота удалены")
        check(13 in bot.deleted, "сообщение игрока, которым вызван экран, тоже удалено")
        left = await db.chat_messages(5)
        check(not left, "база забыла удалённые сообщения")

        # пустой чат - удалять нечего, экран всё равно отправляется
        bot2 = FakeBot()
        message2 = FakeMessage(7, 1)
        await open_screen(bot2, message2, db, "ПЕРВЫЙ ЭКРАН")
        check(message2.sent == ["ПЕРВЫЙ ЭКРАН"], "первый экран отправлен")

        # авточистка без нового сообщения (например, перед автоквестом)
        bot3 = FakeBot()
        deleted = await auto_clean(bot3, 7, db)
        check(deleted >= 0, f"авточистка отработала: {deleted}")

        # middleware запоминает сообщения игрока - чтобы чистить их потом
        from datetime import datetime, timezone

        from aiogram.types import Chat, Message, User

        from bot.middleware import ErrorCounterMiddleware

        patch_db(db)
        middleware = ErrorCounterMiddleware()

        async def _handler(event, data):
            return "ok"

        msg = Message(
            message_id=77,
            date=datetime.now(timezone.utc),
            chat=Chat(id=5, type="private"),
            from_user=User(id=5, is_bot=False, first_name="И"),
            text="привет",
        )
        await middleware(_handler, msg, {})
        tracked = await db.chat_messages(5)
        check(77 in tracked, f"middleware запомнил сообщение игрока: {tracked}")

        # а callback - это сообщение бота, его запоминать не надо
        before = len(tracked)
        await middleware(_handler, object(), {})
        check(len(await db.chat_messages(5)) == before,
              "не-сообщения не запоминаются")
    finally:
        await db.close()


async def test_cleanup_is_bounded() -> None:
    """Чистка не должна перебирать тысячи номеров сообщений."""
    section("Чистка ограничена по объёму")

    from bot.utils import auto_clean

    class FakeBot:
        def __init__(self) -> None:
            self.deleted: list[int] = []

        async def delete_message(self, chat_id: int, message_id: int) -> None:
            self.deleted.append(message_id)

    db = Database(":memory:")
    await db.connect()
    try:
        # чат живёт давно: номера сообщений разошлись на тысячи
        await db.track_message(5, 30, "auto")
        await db.track_message(5, 9000, "auto")

        bot = FakeBot()
        await auto_clean(bot, 5, db, up_to_id=9000)
        check(
            len(bot.deleted) <= 250,
            f"удалено не больше пары сотен сообщений: {len(bot.deleted)}",
        )
        check(30 in bot.deleted, "старый известный номер тоже удалён")
        check(9000 in bot.deleted, "последнее сообщение удалено")
        left = await db.chat_messages(5)
        check(not left, "база забыла удалённые сообщения")
    finally:
        await db.close()


async def test_streak_free() -> None:
    """Защита серии: один пропущенный день не обнуляет серию."""
    section("Защита серии")

    db = Database(":memory:")
    await db.connect()
    try:
        await db.create_user(1)
        for day in ("2026-10-01", "2026-10-02", "2026-10-03"):
            await db.touch_day(1, day)
        user = await db.get_user(1)
        check(user["streak"] == 3, f"серия растёт: {user['streak']}")

        # пропустили 4 октября, пришли 5-го - защита сработала
        streak = await db.touch_day(1, "2026-10-05")
        check(streak == 4, f"защита сохранила серию: {streak}")
        check(await db.streak_free_used_today(1, "2026-10-05"), "защита отмечена")
        check(
            not await db.streak_free_available(1, "2026-10-06"),
            "защита на перезарядке",
        )
        check(
            await db.streak_free_available(1, "2026-10-12"),
            "через неделю защита снова доступна",
        )

        # без защиты серия обнуляется
        await db.create_user(2)
        for day in ("2026-10-01", "2026-10-02", "2026-10-03"):
            await db.touch_day(2, day)
        await db.db.execute(
            "UPDATE users SET streak_free_day = '2026-10-09' WHERE tg_id = 2"
        )
        await db.db.commit()
        streak = await db.touch_day(2, "2026-10-05")
        check(streak == 1, f"без защиты серия обнулилась: {streak}")

        # два пропущенных дня - защита одна, серия обнуляется
        await db.create_user(3)
        for day in ("2026-10-01", "2026-10-02"):
            await db.touch_day(3, day)
        streak = await db.touch_day(3, "2026-10-06")
        check(streak == 1, f"два пропущенных дня обнуляют серию: {streak}")
    finally:
        await db.close()


async def test_pvp_rotator() -> None:
    """Вызов на бой не выдаёт то, что игрок уже проходил."""
    section("Ротатор в PvP")

    import json

    import bot.pvp as pvp_module
    from bot.content import RIDDLES
    from bot.pvp import create_challenge

    db = Database(":memory:")
    await db.connect()
    patch_db(db)
    patch_db(db)
    pvp_module.GAME_TYPES = ("riddle",)
    try:
        await db.create_user(1)
        # половина загадок "уже пройдена"
        for item in RIDDLES[:15]:
            await db.create_quest(
                1,
                "2026-10-01",
                "riddle",
                "easy",
                {"q": item["q"]},
                item_key=f"riddle:{item['q']}",
            )

        code = await create_challenge(1)
        match = await db.get_pvp_by_code(code)
        payload = json.loads(match["payload"])
        used = {f"riddle:{item['q']}" for item in RIDDLES[:15]}
        check(payload["_key"] not in used, f"вызов не выдал пройденное: {payload['_key']}")
        check(
            payload["_key"].startswith("riddle:"),
            f"у вызова есть ключ задания: {payload['_key']}",
        )
    finally:
        await db.close()


async def test_error_handler() -> None:
    """Ошибка в обработчике: игроку отвечают, а не молчат."""
    section("Ошибки видны игроку")

    from datetime import datetime, timezone
    from unittest.mock import AsyncMock, patch

    from aiogram.types import Chat, ErrorEvent, Message as AiogramMessage
    from aiogram.types import Update, User

    from bot.__main__ import handle_error

    msg = AiogramMessage(
        message_id=1,
        date=datetime.now(timezone.utc),
        chat=Chat(id=5, type="private"),
        from_user=User(id=5, is_bot=False, first_name="И"),
        text="привет",
    )
    event = ErrorEvent(
        update=Update(update_id=1, message=msg),
        exception=RuntimeError("сломалось"),
    )

    with patch.object(AiogramMessage, "answer", new=AsyncMock()) as answer:
        result = await handle_error(event)
    check(result is True, "обработчик ошибок отработал")
    check(answer.await_count == 1, f"игроку ответили: {answer.await_count}")
    text = answer.await_args.args[0] if answer.await_args else ""
    check("СЛОМАЛОСЬ" in text, f"в ответе есть понятное объяснение: {text[:60]}")


async def test_achievements() -> None:
    """Достижения выдаются по статистике и не дублируются."""
    section("Достижения")

    import bot.achievements as achievements_module
    from bot.achievements import ACHIEVEMENTS, check_achievements

    db = Database(":memory:")
    await db.connect()
    patch_db(db)
    try:
        await db.create_user(1)

        fresh = await check_achievements(1)
        check(not fresh, f"до первого квеста достижений нет: {fresh}")

        await db.db.execute(
            "UPDATE users SET quests_done = 1, correct = 1 WHERE tg_id = 1"
        )
        await db.db.commit()
        fresh = await check_achievements(1)
        check(len(fresh) == 1, f"первое достижение выдано: {fresh}")
        check("Первый" in fresh[0], f"у достижения понятное название: {fresh[0]}")

        again = await check_achievements(1)
        check(not again, f"повторно не выдаётся: {again}")

        await db.db.execute(
            "UPDATE users SET best_streak = 7, pvp_wins = 1 WHERE tg_id = 1"
        )
        await db.db.commit()
        fresh = await check_achievements(1)
        check(len(fresh) == 3, f"серия (3 дня и неделя) и победа засчитаны: {fresh}")

        earned, total = await achievements_module.achievements_summary(1)
        check(earned == 4, f"всего получено: {earned}")
        check(total == len(ACHIEVEMENTS), f"всего доступно: {total}")
        titles = await achievements_module.achievements_list(1)
        check(len(titles) == 4, f"список полученных: {titles}")
    finally:
        await db.close()


async def test_achievements_screen() -> None:
    """Экран достижений: полученные, закрытые и подсказка."""
    section("Экран достижений")

    from bot.achievements import build_achievements_text
    from bot.keyboards import main_menu

    db = Database(":memory:")
    await db.connect()
    patch_db(db)
    try:
        await db.create_user(1)
        await db.grant_achievement(1, "first_quest")

        text = await build_achievements_text(1)
        check("ДОСТИЖЕНИЯ" in text, "есть заголовок")
        check("1 из 9" in text, f"счётчик полученных: {text[:60]}")
        check("✅" in text, "полученные отмечены галочкой")
        check("🔒" in text, "неполученные закрыты замком")
        check("Пройди 50 квестов" in text, "у закрытого есть подсказка")
        check("Ближайшее" in text, "есть подсказка, что делать дальше")

        labels = [b.text for row in main_menu().inline_keyboard for b in row]
        check(
            any("Достижения" in label for label in labels),
            f"кнопка достижений есть в меню: {labels}",
        )
    finally:
        await db.close()


def test_greeting() -> None:
    """Приветствие зависит от времени суток."""
    section("Приветствие по времени")

    from bot.daily import greeting_for

    check("утро" in greeting_for(8), f"утром - утро: {greeting_for(8)}")
    check("день" in greeting_for(14), f"днём - день: {greeting_for(14)}")
    check("вечер" in greeting_for(20), f"вечером - вечер: {greeting_for(20)}")
    check("ночи" in greeting_for(2), f"ночью - ночь: {greeting_for(2)}")


async def test_admin_panel() -> None:
    """Админ-раздел: доступ, статистика, починка, объявление."""
    section("Админка")

    import bot.admin as admin_module
    from bot.admin import (
        build_player_card,
        build_players_text,
        build_stats_text,
        change_points,
        grant_achievement,
        is_admin,
        players_csv_bytes,
        reset_player,
        vacuum,
    )

    db = Database(":memory:")
    await db.connect()
    patch_db(db)

    class FakeBot:
        def __init__(self) -> None:
            self.sent: list[int] = []

        async def send_message(self, chat_id: int, text: str, **kwargs) -> None:
            self.sent.append(chat_id)

    old_admin = admin_module.ADMIN_IDS
    admin_module.ADMIN_IDS = (555,)
    try:
        check(is_admin(555), "владелец - админ")
        check(not is_admin(556), "остальные - не админы")
        admin_module.ADMIN_IDS = ()
        check(not is_admin(555), "без секрета админка закрыта")

        admin_module.ADMIN_IDS = (555,)
        await db.create_user(555)
        await db.set_nickname(555, "Тест")
        await db.db.execute(
            "UPDATE users SET points = 300, quests_done = 10, correct = 8,"
            " wrong = 2, streak = 5, best_streak = 6,"
            " last_quest_day = '2026-10-21' WHERE tg_id = 555"
        )
        await db.db.commit()

        stats = await build_stats_text()
        check("СТАТИСТИКА" in stats, "есть заголовок статистики")
        check("Активны сегодня" in stats, "есть активные за сегодня")
        check("80%" in stats, f"средняя точность посчитана: {stats[:200]}")

        players = await build_players_text()
        check("ИГРОКИ" in players, "есть список игроков")
        check("Тест" in players, "игрок в списке")

        card = await build_player_card(555)
        check("Очки" in card and "300" in card, f"карточка игрока: {card[:120]}")

        await reset_player(555)
        user = await db.get_user(555)
        check(user["streak"] == 0, f"серия сброшена: {user['streak']}")

        await change_points(555, 50)
        user = await db.get_user(555)
        check(user["points"] == 350, f"очки начислены: {user['points']}")

        await grant_achievement(555, "first_quest")
        earned = await db.earned_achievements(555)
        check("first_quest" in earned, f"достижение выдано: {earned}")

        bot = FakeBot()
        sent, total = await admin_module.broadcast(bot, "Тестовое объявление")
        check(sent == 1 and total == 1, f"объявление разослано: {sent} из {total}")
        check(bot.sent == [555], f"получил админ: {bot.sent}")

        data = await players_csv_bytes()
        check(b"tg_id" in data, "CSV с заголовком")
        check(b"555" in data, "CSV со списком игроков")

        note = await vacuum(0)
        check("Убрано" in note, f"уборка отработала: {note}")
    finally:
        admin_module.ADMIN_IDS = old_admin
        await db.close()


async def test_new_games() -> None:
    """Новые игры: «Правда или ложь» и «Счёт»."""
    section("Новые мини-игры")

    from bot.games import get_game
    from bot.games.math import _make_options, _make_problem

    rng = random.Random(11)

    # «Правда или ложь»
    truth = get_game("truth")
    payload = await truth.build("easy", rng)
    check("t" in payload and "a" in payload, f"есть утверждение и ответ: {payload}")
    check(isinstance(payload["a"], bool), "ответ - да/нет")
    check(bool(payload.get("why")), "есть объяснение")

    quest = Quest(id=1, tg_id=1, day="2026-10-21", game_type="truth",
                  difficulty="easy", payload=payload)
    render = truth.render(quest)
    check(render.markup is not None, "есть кнопки")
    labels = [b.text for row in render.markup.inline_keyboard for b in row]
    check(any("Правда" in label for label in labels), f"кнопка «Правда»: {labels}")
    check(any("Ложь" in label for label in labels), f"кнопка «Ложь»: {labels}")

    # верный ответ засчитывается, неверный - нет
    right_choice = "t" if payload["a"] else "f"
    wrong_choice = "f" if payload["a"] else "t"
    ok = await truth.on_choice(quest, right_choice)
    check(ok.outcome == "solved", f"верный ответ засчитан: {ok.outcome}")
    bad = await truth.on_choice(quest, wrong_choice)
    check(bad.outcome == "failed", f"неверный ответ не засчитан: {bad.outcome}")

    # «Счёт»: примеры всегда с верным ответом
    math_game = get_game("math")
    for difficulty in ("easy", "medium", "hard"):
        for _ in range(20):
            question, answer, cat = _make_problem(difficulty, random.Random(_))
            options = _make_options(answer, random.Random(_))
            check_true = answer in options and len(options) == 4
            if not check_true:
                check(False, f"сломан пример: {question} -> {answer} {options}")
                break
    else:
        check(True, "все примеры с верным ответом и четырьмя вариантами")

    payload = await math_game.build("medium", rng)
    check(payload["q"].endswith("= ?"), f"вопрос-пример: {payload['q']}")
    check(len(payload["options"]) == 4, "четыре варианта")
    check(
        str(payload["options"][payload["correct"]]).isdigit(),
        "верный вариант - число",
    )
    check(payload["_key"].startswith("math:"), f"есть ключ: {payload['_key']}")


async def test_admin_list() -> None:
    """Несколько админов: список и права."""
    section("Список админов")

    import bot.admin as admin_module
    from bot.admin import admin_ids, build_admins_text, is_admin

    db = Database(":memory:")
    await db.connect()
    patch_db(db)

    old_ids = admin_module.ADMIN_IDS
    try:
        admin_module.ADMIN_IDS = (111, 222)
        check(admin_ids() == (111, 222), f"админов двое: {admin_ids()}")
        check(is_admin(111) and is_admin(222), "оба - админы")
        check(not is_admin(333), "остальные - нет")

        await db.create_user(222)
        await db.set_nickname(222, "Второй")
        await db.create_user(111)
        await db.set_nickname(111, "Первый")

        text = await build_admins_text(111)
        check("АДМИНЫ" in text, "есть раздел с админами")
        check("111" in text and "222" in text, f"оба видны: {text[:200]}")
        check("Первый" in text, "ники показаны")
        check("это вы" in text, f"текущий отмечен: {text[:200]}")

        empty = await build_admins_text()
        check("АДМИНЫ" in empty, "раздел есть даже без админов")
    finally:
        admin_module.ADMIN_IDS = old_ids
        await db.close()


async def main() -> None:
    print("=" * 56)
    print("  QuestBot — самопроверка")
    print("=" * 56)
    test_content()
    test_scoring()
    test_greeting()
    await test_games()
    await test_new_games()
    await test_database()
    await test_tracking_session()
    await test_daily_logic()
    await test_adaptive_and_notify()
    await test_rotator()
    await test_novice_level()
    await test_daily_pass_batch()
    await test_profile_and_top()
    await test_auto_clean()
    await test_cleanup_is_bounded()
    await test_streak_free()
    await test_pvp_rotator()
    await test_achievements()
    await test_achievements_screen()
    await test_admin_panel()
    await test_admin_list()
    await test_error_handler()
    await test_migration_old_db()
    await test_backup()
    test_watchdog_logic()
    await test_error_counter()

    print("\n" + "=" * 56)
    print(TALLY.summary())
    print("=" * 56)
    sys.exit(1 if TALLY.failed else 0)


if __name__ == "__main__":
    asyncio.run(main())

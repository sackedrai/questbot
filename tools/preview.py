"""Превью всех сообщений бота - посмотреть дизайн без запуска.

Запуск: python tools/preview.py
"""

from __future__ import annotations

import asyncio
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # pragma: no cover
        pass

from bot import style  # noqa: E402
from bot.config import DIFFICULTY_TITLES  # noqa: E402
from bot.db import Database  # noqa: E402
from tools._testing import patch_db  # noqa: E402
from bot.games import Quest, get_game  # noqa: E402
from bot.handlers.common import HELP_TEXT, WELCOME_TEXT  # noqa: E402
from bot.services import build_profile_text, build_top_text  # noqa: E402


def show(title: str, text: str, markup=None) -> None:
    print("\n" + "═" * 58)
    print(f"  {title}")
    print("═" * 58)
    print(text.replace("<b>", "").replace("</b>", "")
              .replace("<i>", "").replace("</i>", "")
              .replace("<pre>", "").replace("</pre>", "")
              .replace("<blockquote>", "").replace("</blockquote>", ""))
    if markup is not None and getattr(markup, "inline_keyboard", None):
        print("  кнопки:")
        for row in markup.inline_keyboard:
            print("    [" + "] [".join(button.text for button in row) + "]")


async def main() -> None:
    db = Database(":memory:")
    await db.connect()


    patch_db(db)

    try:
        await _render(db)
    finally:
        await db.close()


async def _render(db: Database) -> None:
    from bot.db import today_iso

    today = today_iso()

    async def seed(tg_id: int, points: int, times: int = 1) -> None:
        for _ in range(times):
            quest_id = await db.create_quest(tg_id, today, "quiz", "medium", {"q": "?"})
            await db.finish_quest(quest_id, points, "done")

    # игрок с историей
    await db.create_user(1)
    await db.set_nickname(1, "Вася")
    await db.set_difficulty(1, "medium")
    await db.add_result(1, 420, True)
    await db.add_result(1, 380, True)
    await db.add_result(1, 310, True)
    await db.add_result(1, 0, False)
    await db.add_result(1, 240, True)
    await db.touch_day(1, today)
    await seed(1, 420)
    await seed(1, 380)
    await seed(1, 310)
    await seed(1, 240)

    await db.create_user(2)
    await db.set_nickname(2, "Петя")
    await db.add_result(2, 1180, True)
    await seed(2, 1180)

    await db.create_user(3)
    await db.set_nickname(3, "Оля")
    await db.add_result(3, 940, True)
    await seed(3, 940)

    await db.create_user(4)
    await db.set_nickname(4, "Миша")
    await db.add_result(4, 610, True)
    await seed(4, 610)

    show("ПРИВЕТСТВИЕ", WELCOME_TEXT)

    show(
        "ВЫБОР СЛОЖНОСТИ",
        "\n".join(
            [
                style.header("🤝", "ПРИЯТНО ПОЗНАКОМИТЬСЯ!", "Вася"),
                "",
                "Выбери сложность квестов — её можно поменять в любой момент.",
                "",
                f"{DIFFICULTY_TITLES['easy']}",
                "",
                f"{DIFFICULTY_TITLES['medium']}",
                "",
                f"{DIFFICULTY_TITLES['hard']}",
            ]
        ).replace("<b>", "").replace("</b>", ""),
    )

    profile = await build_profile_text(1)
    show("ПРОФИЛЬ", profile)

    top, _ = await build_top_text("all", 1)
    show("РЕЙТИНГ", top)

    # квесты
    rng = random.Random(7)
    for game_type in ("quiz", "fast", "timeline", "riddle", "word"):
        game = get_game(game_type)
        payload = await game.build("medium", rng)
        quest = Quest(id=1, tg_id=1, day="2026-10-21", game_type=game_type,
                      difficulty="medium", payload=payload)
        render = game.render(quest)
        show(f"КВЕСТ: {game_type.upper()}", render.text, render.markup)

    # вопрос, присланный игроком
    from bot.games.userquiz import UserQuizGame

    question_id = await db.add_user_question(
        2,
        "Столица Австралии?",
        "Канберра",
        ["Сидней", "Мельбурн", "Перт"],
        "География",
        "medium",
    )
    await db.approve_question(question_id, 9001)
    payload = await UserQuizGame.build("medium", rng, exclude_author=1)
    if payload is not None:
        quest = Quest(id=2, tg_id=1, day="2026-10-21",
                      game_type="userquiz", difficulty="medium",
                      payload=payload)
        render = UserQuizGame.render(quest)
        show("КВЕСТ: ВОПРОС ИГРОКА", render.text, render.markup)

    # свой вопрос: раздел и список
    from bot.handlers.ask import (
        _mine_markup,
        _my_questions_text,
        ask_home_markup,
        build_ask_home_text,
    )

    await db.add_user_question(
        1,
        "Какой город является столицей Японии?",
        "Токио",
        ["Осака", "Киото", "Нагоя"],
        "География",
        "easy",
    )
    show("СВОЙ ВОПРОС", await build_ask_home_text(1), ask_home_markup())
    show("МОИ ВОПРОСЫ", await _my_questions_text(1), _mine_markup())

    # удержание: недельная сводка, история боёв
    from bot.db import today_iso
    from bot.keyboards import main_menu
    from bot.services import build_pvp_history_text, build_week_text

    # квесты текущей недели, чтобы сводка была не пустой
    for points in (420, 380, 310, 240):
        quest_id = await db.create_quest(1, today, "quiz", "medium", {"q": "?"})
        await db.finish_quest(quest_id, points, "done")

    # сыгранный матч для истории
    match_id = await db.create_pvp_match(
        1, "quiz", "medium", {"q": "?", "options": ["a"], "correct": 0}, "PREVW"
    )
    await db.accept_pvp(match_id, 2)
    await db.finish_pvp(match_id, 1, 40)
    await db.finish_pvp(match_id, 2, 20)

    show("НЕДЕЛЯ", await build_week_text(1), main_menu())
    show("ИСТОРИЯ БОЁВ", await build_pvp_history_text(1), main_menu())

    # результат
    from bot.services import complete_quest
    from bot.games import Render

    quest = Quest(id=999, tg_id=1, day=today, game_type="fast",
                  difficulty="medium", payload={}, risky=0, started_at=0)
    summary, _points = await complete_quest(
        quest,
        Render(text="", outcome="solved"),
    )
    show("РЕЗУЛЬТАТ КВЕСТА", summary)

    show("СПРАВКА", HELP_TEXT)


if __name__ == "__main__":
    asyncio.run(main())

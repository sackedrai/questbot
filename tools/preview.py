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
from bot.games import Quest, get_game  # noqa: E402
from bot.handlers.common import HELP_TEXT, WELCOME_TEXT  # noqa: E402
from bot.services import build_profile_text, build_top_text  # noqa: E402


def show(title: str, text: str) -> None:
    print("\n" + "═" * 58)
    print(f"  {title}")
    print("═" * 58)
    print(text.replace("<b>", "").replace("</b>", "")
              .replace("<i>", "").replace("</i>", "")
              .replace("<pre>", "").replace("</pre>", "")
              .replace("<blockquote>", "").replace("</blockquote>", ""))


async def main() -> None:
    db = Database(":memory:")
    await db.connect()

    import bot.services as services_module

    services_module.db = db

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
    await db.create_user(1, "vasya", "Вася")
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

    await db.create_user(2, "petya", "Петя")
    await db.set_nickname(2, "Петя")
    await db.add_result(2, 1180, True)
    await seed(2, 1180)

    await db.create_user(3, "olya", "Оля")
    await db.set_nickname(3, "Оля")
    await db.add_result(3, 940, True)
    await seed(3, 940)

    await db.create_user(4, "misha", "Миша")
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
        show(f"КВЕСТ: {game_type.upper()}", render.text)

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

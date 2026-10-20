"""Адаптивная сложность.

Игрок не выбирает уровень - бот подбирает его сам по результатам
последних квестов: играющему хорошо - сложнее, играющему тяжело -
проще. Плюс немного случайности, чтобы квесты не шли по одному сценарию.
"""

from __future__ import annotations

import random

from .db import db

LEVELS = ("easy", "medium", "hard")

TITLES = {
    "easy": "🟢 Лёгкий",
    "medium": "🟡 Средний",
    "hard": "🔴 Сложный",
}

DESCRIPTIONS = {
    "easy": "факты и логика, без эзотерики",
    "medium": "придётся подумать, но без гугла",
    "hard": "для тех, кто читает википедию по ночам",
}


async def pick_difficulty(
    tg_id: int, rng: random.Random | None = None
) -> str:
    """Подобрать сложность под текущую форму игрока."""
    rng = rng or random
    results = await db.recent_results(tg_id, limit=6)

    if not results:
        # новичку начинаем с лёгкого
        return "easy"

    done = [row for row in results if row["status"] == "done"]
    accuracy = len(done) / len(results)

    if accuracy >= 0.8:
        level = 2
    elif accuracy >= 0.5:
        level = 1
    else:
        level = 0

    # иногда полегче, иногда потяжелее - так квесты не однообразны
    roll = rng.random()
    if roll < 0.15:
        level -= 1
    elif roll > 0.85:
        level += 1

    return LEVELS[max(0, min(2, level))]


async def current_level(tg_id: int) -> str:
    """Текущий уровень без случайности - для показа в профиле."""
    results = await db.recent_results(tg_id, limit=6)
    if not results:
        return "easy"
    done = [row for row in results if row["status"] == "done"]
    accuracy = len(done) / len(results)
    if accuracy >= 0.8:
        return "hard"
    if accuracy >= 0.5:
        return "medium"
    return "easy"


def describe(difficulty: str) -> str:
    """Человеческое описание уровня."""
    title = TITLES.get(difficulty, difficulty)
    return f"{title} — {DESCRIPTIONS.get(difficulty, '')}"

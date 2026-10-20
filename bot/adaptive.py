"""Адаптивная сложность.

Игрок не выбирает уровень - бот подбирает его сам по результатам
последних квестов: играющему хорошо - сложнее, играющему тяжело -
проще. Плюс немного случайности, чтобы квесты не шли по одному сценарию.
"""

from __future__ import annotations

import random

from .db import db

LEVELS = ("easy", "medium", "hard")

# Пока столько недавних результатов - игрок считается новичком
NOVICE_RESULTS = 3
# Новичку сложнее среднего не даём (0 - лёгкий, 1 - средний, 2 - сложный)
NOVICE_MAX_LEVEL = 1

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


async def _base_level(tg_id: int, limit: int = 6) -> tuple[str, int]:
    """Уровень по последним результатам, без случайности.

    Возвращает (уровень, сколько недавних результатов учтено).
    Новичку (мало результатов) сложный уровень не выдаётся: одна удачная
    попытка не должна сразу кидать игрока в сложные вопросы.
    """
    results = await db.recent_results(tg_id, limit=limit)
    if not results:
        return "easy", 0

    done = [row for row in results if row["status"] == "done"]
    accuracy = len(done) / len(results)

    if accuracy >= 0.8:
        level = 2
    elif accuracy >= 0.5:
        level = 1
    else:
        level = 0

    if len(results) < NOVICE_RESULTS and level > NOVICE_MAX_LEVEL:
        level = NOVICE_MAX_LEVEL
    return LEVELS[level], len(results)


async def pick_difficulty(
    tg_id: int, rng: random.Random | None = None
) -> str:
    """Подобрать сложность под текущую форму игрока."""
    rng = rng or random
    base, count = await _base_level(tg_id)
    level = LEVELS.index(base)

    # иногда полегче, иногда потяжелее - так квесты не однообразны
    roll = rng.random()
    if roll < 0.15:
        level -= 1
    elif roll > 0.85:
        level += 1

    # новичку и с random-подбрасыванием сложный уровень не достаётся
    if count < NOVICE_RESULTS and level > NOVICE_MAX_LEVEL:
        level = NOVICE_MAX_LEVEL

    return LEVELS[max(0, min(2, level))]


async def current_level(tg_id: int) -> str:
    """Текущий уровень без случайности - для показа в профиле."""
    base, _ = await _base_level(tg_id)
    return base


def describe(difficulty: str) -> str:
    """Человеческое описание уровня."""
    title = TITLES.get(difficulty, difficulty)
    return f"{title} — {DESCRIPTIONS.get(difficulty, '')}"

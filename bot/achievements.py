"""Достижения.

Простые «заслуги», которые игрок видит в профиле и получает сразу после
квеста. Считаются по статистике игрока, без отдельной сложной логики.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from .db import db

# Проверка достижения: получает строку игрока и отвечает, заслужено ли.
Check = Callable[[Any], bool]

ACHIEVEMENTS: dict[str, dict[str, Any]] = {
    "first_quest": {
        "title": "🎯 Первый квест",
        "hint": "Пройди первый квест",
        "check": lambda u: (u["quests_done"] or 0) >= 1,
    },
    "quest_10": {
        "title": "🏅 Десять квестов",
        "hint": "Пройди 10 квестов",
        "check": lambda u: (u["quests_done"] or 0) >= 10,
    },
    "quest_50": {
        "title": "🎖 Полсотни квестов",
        "hint": "Пройди 50 квестов",
        "check": lambda u: (u["quests_done"] or 0) >= 50,
    },
    "streak_3": {
        "title": "🔥 Три дня подряд",
        "hint": "Сыграй три дня подряд",
        "check": lambda u: (u["best_streak"] or 0) >= 3,
    },
    "streak_7": {
        "title": "🔥 Неделя подряд",
        "hint": "Сыграй семь дней подряд",
        "check": lambda u: (u["best_streak"] or 0) >= 7,
    },
    "streak_30": {
        "title": "🔥 Месяц подряд",
        "hint": "Сыграй тридцать дней подряд",
        "check": lambda u: (u["best_streak"] or 0) >= 30,
    },
    "pvp_win": {
        "title": "⚔️ Первая победа",
        "hint": "Выиграй матч один на один",
        "check": lambda u: (u["pvp_wins"] or 0) >= 1,
    },
    "pvp_5": {
        "title": "⚔️ Пять побед",
        "hint": "Выиграй пять матчей",
        "check": lambda u: (u["pvp_wins"] or 0) >= 5,
    },
    "sniper": {
        "title": "🎯 Снайпер",
        "hint": "20 квестов без единой ошибки",
        "check": lambda u: (u["correct"] or 0) >= 20 and (u["wrong"] or 0) == 0,
    },
}


async def check_achievements(tg_id: int) -> list[str]:
    """Выдать новые достижения. Возвращает их названия."""
    user = await db.get_user(tg_id)
    if user is None:
        return []

    earned = await db.earned_achievements(tg_id)
    fresh: list[str] = []
    for code, spec in ACHIEVEMENTS.items():
        if code in earned:
            continue
        try:
            ok = bool(spec["check"](user))
        except Exception:  # noqa: BLE001 - проверка не должна ломать игру
            ok = False
        if ok:
            await db.grant_achievement(tg_id, code)
            fresh.append(str(spec["title"]))
    return fresh


async def achievements_summary(tg_id: int) -> tuple[int, int]:
    """(сколько получено, сколько всего есть)."""
    earned = await db.earned_achievements(tg_id)
    return len(earned), len(ACHIEVEMENTS)


async def achievements_list(tg_id: int) -> list[str]:
    """Список названий полученных достижений (для профиля)."""
    earned = await db.earned_achievements(tg_id)
    titles = []
    for code in earned:
        spec = ACHIEVEMENTS.get(code)
        if spec:
            titles.append(str(spec["title"]))
    return titles

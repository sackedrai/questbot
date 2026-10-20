"""Подсчёт очков."""

from __future__ import annotations

from .config import (
    BASE_POINTS,
    FAST_BONUS_SECONDS,
    HINT_PENALTY,
    RISKY_MULTIPLIER,
    STREAK_BONUS_MAX_DAYS,
    STREAK_BONUS_PER_DAY,
)


def calculate_points(
    *,
    difficulty: str,
    streak: int = 0,
    elapsed: float | None = None,
    timed: bool = False,
    hint_used: bool = False,
    risky: bool = False,
    extra_mult: float = 1.0,
) -> tuple[int, list[tuple[str, str]]]:
    """Посчитать очки за квест.

    Возвращает (очки, разбивка) — разбивка это список пар
    (подпись, значение), из которого собирается красивая таблица.
    """
    base = BASE_POINTS.get(difficulty, BASE_POINTS["medium"])
    multiplier = 1.0
    rows: list[tuple[str, str]] = [("Базовые очки", str(base))]

    if timed and elapsed is not None:
        fast_threshold, mid_threshold = FAST_BONUS_SECONDS
        if elapsed <= fast_threshold:
            multiplier *= 1.5
            rows.append(("Скорость", "×1.5"))
        elif elapsed <= mid_threshold:
            multiplier *= 1.2
            rows.append(("Скорость", "×1.2"))

    streak_multiplier = 1 + min(streak, STREAK_BONUS_MAX_DAYS) * STREAK_BONUS_PER_DAY
    if streak_multiplier > 1:
        multiplier *= streak_multiplier
        rows.append(("Серия дней", f"×{streak_multiplier:.2f}"))

    if hint_used:
        multiplier *= HINT_PENALTY
        rows.append(("Подсказка", f"×{HINT_PENALTY}"))

    if risky:
        multiplier *= RISKY_MULTIPLIER
        rows.append(("Риск", f"×{RISKY_MULTIPLIER}"))

    if extra_mult != 1.0:
        multiplier *= extra_mult
        rows.append(("Точность", f"×{extra_mult:.2f}"))

    return int(round(base * multiplier)), rows


def level_for_points(points: int) -> tuple[int, int, int]:
    """Уровень по очкам.

    Возвращает (уровень, очки_в_уровне, очки_нужны_для_следующего).
    """
    level = 1
    while points >= level * 500:
        points -= level * 500
        level += 1
    return level, points, level * 500


def progress_bar(current: int, total: int, width: int = 10) -> str:
    if total <= 0:
        return "░" * width
    filled = int(width * current / total)
    filled = max(0, min(width, filled))
    return "█" * filled + "░" * (width - filled)

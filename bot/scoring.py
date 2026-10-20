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
) -> tuple[int, list[str]]:
    """Посчитать очки за квест.

    Возвращает (очки, список бонусов) — список нужен для показа игроку.
    """
    base = BASE_POINTS.get(difficulty, BASE_POINTS["medium"])
    multiplier = 1.0
    reasons: list[str] = []

    if timed and elapsed is not None:
        fast_threshold, mid_threshold = FAST_BONUS_SECONDS
        if elapsed <= fast_threshold:
            multiplier *= 1.5
            reasons.append("скорость ×1.5")
        elif elapsed <= mid_threshold:
            multiplier *= 1.2
            reasons.append("скорость ×1.2")

    streak_multiplier = 1 + min(streak, STREAK_BONUS_MAX_DAYS) * STREAK_BONUS_PER_DAY
    if streak_multiplier > 1:
        multiplier *= streak_multiplier
        reasons.append(f"серия ×{streak_multiplier:.2f}")

    if hint_used:
        multiplier *= HINT_PENALTY
        reasons.append(f"подсказка ×{HINT_PENALTY}")

    if risky:
        multiplier *= RISKY_MULTIPLIER
        reasons.append(f"риск ×{RISKY_MULTIPLIER}")

    if extra_mult != 1.0:
        multiplier *= extra_mult
        reasons.append(f"точность ×{extra_mult:.2f}")

    return int(round(base * multiplier)), reasons


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

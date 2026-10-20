"""Сервисный слой: выдача квестов, подсчёт итогов, тексты профиля и рейтинга."""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Optional

from aiogram.types import InlineKeyboardMarkup

from .config import (
    BONUS_QUEST_PER_DAY,
    QUEST_PER_DAY,
    RISK_PENALTY,
)
from .db import db, today_iso
from .daily import STATE_ACTIVE, STATE_COOLDOWN, availability
from .games import Quest, Render, get_game
from .scoring import calculate_points, level_for_points
from . import adaptive, style

GAME_TYPES = ("quiz", "fast", "timeline", "riddle", "word")

SCOPE_TITLES = {
    "today": "очки за сегодня",
    "week": "очки за неделю",
    "all": "очки за всё время",
    "quests_today": "квесты за сегодня",
    "quests": "квесты за всё время",
    "pvp": "рейтинг PvP",
}


@dataclass
class QuestStart:
    """Результат попытки выдать квест."""

    text: str
    markup: Optional[InlineKeyboardMarkup] = None
    needs_input: bool = False
    quest_id: Optional[int] = None
    blocked: bool = False
    existing: bool = False  # это уже выданный квест, показанный заново


async def start_quest(
    tg_id: int,
    risky: bool = False,
    *,
    pvp_id: int = 0,
    game_type: str | None = None,
    difficulty: str | None = None,
    payload: dict | None = None,
) -> QuestStart:
    """Выдать игроку новый квест.

    Для PvP передаются готовые game_type/difficulty/payload - тогда у обоих
    игроков одинаковое задание.
    """
    user = await db.get_user(tg_id)
    if user is None:
        return QuestStart(text="Сначала пройди регистрацию: /start", blocked=True)

    day = today_iso()

    if pvp_id == 0:
        avail = await availability(tg_id, risky=risky)
        if avail.state == STATE_ACTIVE:
            # показываем текущий незаконченный квест заново,
            # чтобы не было тупика
            active = await db.get_active_quest(tg_id)
            if active is not None:
                game = get_game(active["game_type"])
                quest = Quest.from_row(active)
                render = game.render(quest)
                return QuestStart(
                    text=render.text,
                    markup=render.markup,
                    needs_input=render.needs_input,
                    quest_id=active["id"],
                    existing=True,
                )
        if avail.state == STATE_COOLDOWN:
            return QuestStart(
                text="\n".join(
                    [
                        style.header(
                            "⏳",
                            "СЛЕДУЮЩИЙ КВЕСТ ЧЕРЕЗ",
                            avail.human_due() + "  ·  " + avail.human_left(),
                        ),
                        style.note(
                            "Следующий квест доступен через 24 часа после прошлого."
                        ),
                    ]
                ),
                blocked=True,
            )

    rng = random.Random(f"{tg_id}:{day}:{time.time_ns()}")
    if difficulty is None:
        difficulty = await adaptive.pick_difficulty(tg_id, rng)
    if game_type is None:
        game_type = rng.choice(GAME_TYPES)
    game = get_game(game_type)

    if payload is None:
        payload = await game.build(difficulty, rng)
    quest_id = await db.create_quest(
        tg_id, day, game_type, difficulty, payload, risky, pvp_id
    )

    quest = Quest(
        id=quest_id,
        tg_id=tg_id,
        day=day,
        game_type=game_type,
        difficulty=difficulty,
        payload=payload,
        risky=1 if risky else 0,
        started_at=time.time(),
    )
    render = game.render(quest)

    header = ""
    if pvp_id:
        header = style.header("⚔️", "МАТЧ PvP") + "\n"
    elif risky:
        header = (
            style.header(
                "⚡",
                "РИСКОВАННЫЙ КВЕСТ",
                f"успех ×2 очка  ·  провал −{RISK_PENALTY}",
            )
            + "\n"
        )
    elif difficulty:
        header = style.note(f"Сложность: {adaptive.describe(difficulty)}") + "\n"

    return QuestStart(
        text=header + render.text,
        markup=render.markup,
        needs_input=render.needs_input,
        quest_id=quest_id,
    )


async def complete_quest(quest: Quest, render: Render) -> tuple[str, int]:
    """Подсчитать итог квеста, записать в базу и вернуть (текст, очки)."""
    game = get_game(quest.game_type)
    solved = render.outcome == "solved"
    elapsed = max(0.0, time.time() - quest.started_at)
    is_pvp = bool(quest.pvp_id)

    if solved:
        if is_pvp:
            # матч не влияет на серию дней
            user = await db.get_user(quest.tg_id)
            streak = user["streak"] if user else 0
        else:
            streak = await db.touch_day(quest.tg_id, quest.day)
        points, breakdown = calculate_points(
            difficulty=quest.difficulty,
            streak=streak,
            elapsed=elapsed,
            timed=game.timed,
            hint_used=render.hint_used,
            risky=bool(quest.risky),
            extra_mult=render.extra_mult,
        )
    else:
        user = await db.get_user(quest.tg_id)
        streak = user["streak"] if user else 0
        points = -RISK_PENALTY if quest.risky else 0
        breakdown = []

    await db.add_result(quest.tg_id, points, solved, count_quest=not is_pvp)
    await db.finish_quest(quest.id, points, "done" if solved else "failed")

    if is_pvp:
        await db.finish_pvp(quest.pvp_id, quest.tg_id, points)
        day_summary = await db.daily_summary(quest.tg_id, quest.day)
        table = style.stats(
            [("", label, value) for label, value in breakdown],
            total=("ИТОГО", style.points_line(points)),
        )
        return (
            "\n".join(
                [
                    style.header("⚔️", "ТВОЙ РЕЗУЛЬТАТ В МАТЧЕ"),
                    table,
                    "",
                    style.note("Ждём соперника."),
                ]
            ),
            points,
        )

    day_summary = await db.daily_summary(quest.tg_id, quest.day)
    day_points = day_summary["points"]

    if solved:
        table = style.stats(
            [("", label, value) for label, value in breakdown],
            total=("ИТОГО", style.points_line(points)),
        )
        summary = "\n".join(
            [
                style.header("🏆", "КВЕСТ ПРОЙДЕН!"),
                table,
                "",
                f"🔥 Серия: <b>{streak}</b> дн.  ·  "
                f"Сегодня: <b>{style.number(day_points)}</b> очков",
            ]
        )
    else:
        if points < 0:
            tail = (
                f"💸 Списано очков: <b>{style.points_line(points)}</b>\n"
                "Серия не прервана — можно попробовать ещё раз."
            )
        else:
            tail = "Серия не прервана — можно попробовать ещё раз."
        summary = "\n".join(
            [
                style.header("💔", "КВЕСТ НЕ ПРОЙДЕН"),
                "",
                tail,
            ]
        )

    return summary, points


async def build_profile_text(tg_id: int) -> str:
    """Карточка профиля игрока."""
    user = await db.get_user(tg_id)
    if user is None:
        return "Сначала пройди регистрацию: /start"

    level, in_level, need = level_for_points(user["points"])
    done = user["quests_done"]
    correct = user["correct"]
    accuracy = round(100 * correct / done) if done else 0
    nickname = user["nickname"] or "Без имени"

    day_summary = await db.daily_summary(tg_id, today_iso())
    today_points = day_summary["points"]
    best_day = await db.best_day_points(tg_id)
    adaptive_level = await adaptive.current_level(tg_id)

    parts = [
        style.header("👤", "ПРОФИЛЬ", f"{nickname}  ·  🎖 уровень {level}"),
        style.progress_block(
            in_level,
            need,
            f"до уровня {level + 1}: {style.number(need - in_level)} очков",
        ),
        style.section("💎 ОЧКИ"),
        style.stats(
            [
                ("", "Всего", style.number(user["points"])),
                ("", "Сегодня", style.number(today_points)),
                ("", "Лучший день", style.number(best_day)),
            ]
        ),
        style.section("🔥 СЕРИЯ"),
        style.stats(
            [
                ("", "Текущая", f"{user['streak']} дн."),
                ("", "Рекорд", f"{user['best_streak']} дн."),
            ]
        ),
        style.section("🎯 СТАТИСТИКА"),
        style.stats(
            [
                ("", "Квестов", str(done)),
                ("", "Успешно", f"{correct}  ({accuracy}%)"),
                ("", "Провалено", str(user["wrong"])),
            ]
        ),
        style.section("⚔️ PvP"),
        style.stats(
            [
                ("", "Побед", str(user["pvp_wins"] or 0)),
                ("", "Поражений", str(user["pvp_losses"] or 0)),
                ("", "Очки матчей", style.number(user["pvp_points"] or 0)),
            ]
        ),
        style.section("🎚 СЛОЖНОСТЬ"),
        f"{adaptive.TITLES.get(adaptive_level, adaptive_level)} — авто",
        style.note(adaptive.DESCRIPTIONS.get(adaptive_level, "")),
        style.footer(),
    ]
    return "\n".join(parts)


async def build_top_text(scope: str = "all", tg_id: Optional[int] = None) -> tuple[str, str]:
    """Карточка рейтинга. Возвращает (текст, scope)."""
    scope = scope if scope in SCOPE_TITLES else "all"
    rows = await db.leaderboard(scope=scope, limit=10)

    parts = [style.header("🏆", "РЕЙТИНГ", SCOPE_TITLES[scope])]

    if not rows:
        parts.append(style.note("Пока никто ничего не заработал. Начни первым!"))
        return "\n".join(parts), scope

    table_rows = []
    for row in rows:
        name = row["nickname"] or "Аноним"
        points = row["scope_points"] if scope != "all" else row["total_points"]
        table_rows.append((name, style.number(points)))
    parts.append(style.leaderboard(table_rows))

    if tg_id is not None:
        place = await db.user_position(tg_id, scope)
        if place:
            parts.append("")
            parts.append(f"👤 Твоё место: <b>{place}</b>")

    parts.append(style.footer())
    return "\n".join(parts), scope

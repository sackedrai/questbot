"""Сервисный слой: выдача квестов, подсчёт итогов, тексты профиля и рейтинга."""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Optional

from aiogram.types import InlineKeyboardMarkup

from .config import (
    BONUS_QUEST_PER_DAY,
    DIFFICULTY_HINTS,
    DIFFICULTY_TITLES,
    QUEST_PER_DAY,
    RISK_PENALTY,
)
from .db import db, today_iso
from .games import Quest, Render, get_game
from .scoring import calculate_points, level_for_points, progress_bar

GAME_TYPES = ("quiz", "fast", "timeline", "riddle", "word")

SCOPE_TITLES = {
    "today": "за сегодня",
    "week": "за неделю",
    "all": "за всё время",
}


@dataclass
class QuestStart:
    """Результат попытки выдать квест."""

    text: str
    markup: Optional[InlineKeyboardMarkup] = None
    needs_input: bool = False
    quest_id: Optional[int] = None
    blocked: bool = False


async def start_quest(tg_id: int, risky: bool) -> QuestStart:
    """Выдать игроку новый квест."""
    user = await db.get_user(tg_id)
    if user is None:
        return QuestStart(text="Сначала пройди регистрацию: /start", blocked=True)

    day = today_iso()
    used = await db.count_quests_today(tg_id, day, risky)
    limit = BONUS_QUEST_PER_DAY if risky else QUEST_PER_DAY
    if used >= limit:
        if risky:
            return QuestStart(
                text="⚡ Рискованный квест на сегодня уже использован.",
                blocked=True,
            )
        return QuestStart(
            text=(
                "Сегодняшний квест уже пройден.\n\n"
                "Можно взять <b>рискованный</b> квест: +×2 очка за успех, "
                f"но −{RISK_PENALTY} очков при провале."
            ),
            blocked=True,
        )

    difficulty = user["difficulty"] or "medium"
    rng = random.Random(f"{tg_id}:{day}:{used}:{time.time_ns()}")
    game_type = rng.choice(GAME_TYPES)
    game = get_game(game_type)

    payload = await game.build(difficulty, rng)
    quest_id = await db.create_quest(tg_id, day, game_type, difficulty, payload, risky)

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
    if risky:
        header = (
            "⚡ <b>Рискованный квест</b>\n"
            f"<i>Успех — ×2 очка. Провал — −{RISK_PENALTY} очков.</i>\n\n"
        )

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

    if solved:
        streak = await db.touch_day(quest.tg_id, quest.day)
        points, reasons = calculate_points(
            difficulty=quest.difficulty,
            streak=streak,
            elapsed=elapsed,
            timed=game.timed,
            hint_used=render.hint_used,
            risky=bool(quest.risky),
            extra_mult=render.extra_mult,
        )
        bonus_block = ""
        if reasons:
            bonus_block = "\n\n<b>Бонусы:</b>\n" + "\n".join(f"• {r}" for r in reasons)
        summary = (
            f"🏆 <b>Квест пройден!</b>\n\n"
            f"Очки: <b>+{points}</b>{bonus_block}\n"
            f"🔥 Серия дней: <b>{streak}</b>"
        )
    else:
        user = await db.get_user(quest.tg_id)
        streak = user["streak"] if user else 0
        points = -RISK_PENALTY if quest.risky else 0
        if points < 0:
            summary = (
                "💔 <b>Квест провален.</b>\n\n"
                f"Списано очков: <b>−{abs(points)}</b>\n"
                "Серия не прервана — можно попробовать ещё раз."
            )
        else:
            summary = (
                "💔 <b>Квест провален.</b>\n"
                "<i>Очки не начислены. Серия не прервана — можно попробовать ещё раз.</i>"
            )

    await db.add_result(quest.tg_id, points, solved)
    await db.finish_quest(quest.id, points, "done" if solved else "failed")

    day_summary = await db.daily_summary(quest.tg_id, quest.day)
    summary += (
        "\n\n<b>Сегодня:</b> "
        f"{day_summary['done']} квестов, {day_summary['points']} очков"
    )
    return summary, points


async def build_profile_text(tg_id: int) -> str:
    """Текст профиля игрока."""
    user = await db.get_user(tg_id)
    if user is None:
        return "Сначала пройди регистрацию: /start"

    level, in_level, need = level_for_points(user["points"])
    done = user["quests_done"]
    correct = user["correct"]
    accuracy = round(100 * correct / done) if done else 0
    nickname = user["nickname"] or user["display_name"] or "Без имени"

    return (
        "👤 <b>Профиль</b>\n\n"
        f"Имя в рейтинге: <b>{nickname}</b>\n"
        f"Уровень: <b>{level}</b>  {progress_bar(in_level, need)}\n"
        f"Очков до следующего уровня: {need - in_level}\n\n"
        f"💎 Очки всего: <b>{user['points']}</b>\n"
        f"🔥 Серия: <b>{user['streak']}</b> дн. (рекорд: {user['best_streak']})\n"
        f"🎯 Квестов пройдено: <b>{done}</b> (успешно {correct})\n"
        f"📊 Точность: <b>{accuracy}%</b>\n"
        f"⚙️ Сложность: {DIFFICULTY_TITLES.get(user['difficulty'], user['difficulty'])}\n"
        f"<i>{DIFFICULTY_HINTS.get(user['difficulty'], '')}</i>"
    )


async def build_top_text(scope: str = "all", tg_id: Optional[int] = None) -> tuple[str, str]:
    """Текст рейтинга. Возвращает (текст, scope)."""
    scope = scope if scope in SCOPE_TITLES else "all"
    rows = await db.leaderboard(scope=scope, limit=10)
    title = f"🏆 <b>Рейтинг {SCOPE_TITLES[scope]}</b>\n"

    if not rows:
        return title + "\n<i>Пока никто ничего не заработал. Начни первым!</i>", scope

    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    lines = []
    for position, row in enumerate(rows, start=1):
        name = row["nickname"] or row["display_name"] or row["username"] or "Аноним"
        points = row["scope_points"] if scope != "all" else row["total_points"]
        marker = medals.get(position, f"{position}.")
        lines.append(f"{marker} <b>{name}</b> — {points}")

    text = title + "\n" + "\n".join(lines)

    if tg_id is not None:
        place = await db.user_position(tg_id, scope)
        if place:
            text += f"\n\n<i>Твоё место: {place}</i>"
    return text, scope

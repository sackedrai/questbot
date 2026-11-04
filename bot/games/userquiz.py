"""Викторина из вопроса, который прислал игрок.

Вопросы проходят модерацию и лежат в таблице ``user_questions``. Игра
намеренно не входит в ``GAME_TYPES``: обычный квест выбирает её только
тогда, когда есть свежий одобренный вопрос, а не каждый раз.
"""

from __future__ import annotations

import html
import json
import random
from typing import Any, Optional

from aiogram.utils.keyboard import InlineKeyboardBuilder

from .. import style
from ..db import db
from .base import Quest, Render, add_skip
from .quiz import QuizGame


class UserQuizGame(QuizGame):
    """Вопрос игрока с четырьмя вариантами ответа."""

    type = "userquiz"
    title = "Вопрос игрока"
    timed = False

    @classmethod
    async def build(
        cls,
        difficulty: str,
        rng: random.Random,
        exclude: Optional[set[str]] = None,
        exclude_author: int = 0,
    ) -> Optional[dict[str, Any]]:
        """Собрать вопрос, которого игрок ещё не видел.

        Возвращает ``None``, если одобренных вопросов нет или все они уже
        попадались игроку. Тогда сервис выдаст обычную мини-игру.
        """
        rows = await db.get_approved_questions()
        pool = [row for row in rows if int(row["tg_id"]) != int(exclude_author)]
        matching = [row for row in pool if row["difficulty"] == difficulty]
        pool = matching or pool
        used = exclude or set()
        fresh = [row for row in pool if cls.item_key(row) not in used]
        if not fresh:
            return None
        return cls.payload_from_row(rng.choice(fresh), rng)

    @classmethod
    def payload_from_row(
        cls, row: Any, rng: random.Random
    ) -> Optional[dict[str, Any]]:
        """Превратить строку базы в payload викторины."""
        try:
            wrong = json.loads(row["options"] or "[]")
        except (TypeError, ValueError):
            wrong = []
        answer = str(row["answer"]).strip()
        wrong = [str(item).strip() for item in wrong if str(item).strip()]
        options = [answer, *wrong]
        if len(options) < 2:
            return None
        rng.shuffle(options)
        return {
            "q": str(row["question"]),
            "options": options,
            "correct": options.index(answer),
            "cat": str(row["category"] or "Свои вопросы"),
            "uid": int(row["id"]),
            "_key": cls.item_key(row),
            "_exhausted": False,
        }

    @classmethod
    def item_key(cls, item: Any) -> str:
        return f"userquiz:{item['id']}"

    @classmethod
    def payload_key(cls, payload: dict[str, Any]) -> str:
        uid = payload.get("uid")
        return f"userquiz:{uid}" if uid else ""

    @classmethod
    def render(cls, quest: Quest) -> Render:
        payload = quest.payload
        question = html.escape(str(payload.get("q", "")))
        category = html.escape(str(payload.get("cat", "Свои вопросы")))
        builder = InlineKeyboardBuilder()
        for index, option in enumerate(payload["options"]):
            builder.button(text=str(option), callback_data=f"g:{quest.id}:{index}")
        builder.adjust(1)
        add_skip(builder, quest.id, rows_before=4)
        return Render(
            text="\n".join(
                [
                    style.header(
                        "🧠",
                        "ВОПРОС ИГРОКА",
                        f"категория: {category}",
                    ),
                    "",
                    style.question(question),
                    style.note("Вопрос прислал другой игрок · выбери ответ ↓"),
                ]
            ),
            markup=builder.as_markup(),
        )

    @classmethod
    async def on_choice(cls, quest: Quest, choice: str) -> Render:
        payload = quest.payload
        try:
            index = int(choice)
        except ValueError:
            return Render(text="Некорректный выбор.")

        options = payload["options"]
        if not 0 <= index < len(options):
            return Render(text="Некорректный выбор.")

        correct = payload["correct"]
        answer = html.escape(str(options[correct]))
        if index == correct:
            return Render(
                text="\n".join(
                    [
                        style.header("✅", "ВЕРНО!"),
                        style.answer(answer),
                    ]
                ),
                outcome="solved",
                detail=str(options[correct]),
            )
        return Render(
            text="\n".join(
                [
                    style.header("❌", "НЕВЕРНО"),
                    style.answer(answer),
                    style.note("Очки за этот квест не начислены."),
                ]
            ),
            outcome="failed",
            detail=str(options[correct]),
        )

"""Викторина: вопрос и четыре варианта ответа."""

from __future__ import annotations

import random
from typing import Any

from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..content import QUIZ
from .base import BaseGame, Quest, Render


class QuizGame(BaseGame):
    type = "quiz"
    title = "Викторина"
    timed = False

    @classmethod
    async def build(cls, difficulty: str, rng: random.Random) -> dict[str, Any]:
        pool = [item for item in QUIZ if item.get("diff") == difficulty] or list(QUIZ)
        item = rng.choice(pool)
        options = list(item["options"])
        order = list(range(len(options)))
        rng.shuffle(order)
        return {
            "q": item["q"],
            "options": [options[i] for i in order],
            "correct": order.index(item["correct"]),
            "cat": item["cat"],
        }

    @classmethod
    def render(cls, quest: Quest) -> Render:
        payload = quest.payload
        builder = InlineKeyboardBuilder()
        for index, option in enumerate(payload["options"]):
            builder.button(text=option, callback_data=f"g:{quest.id}:{index}")
        builder.adjust(1)
        return Render(
            text=(
                "🧠 <b>Викторина</b>\n\n"
                f"{payload['q']}\n\n"
                f"<i>Категория: {payload['cat']}</i>"
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
        if index == correct:
            return Render(
                text=f"✅ <b>Верно!</b>\n\nПравильный ответ: <b>{options[correct]}</b>",
                outcome="solved",
                detail=options[correct],
            )
        return Render(
            text=(
                "❌ <b>Неверно.</b>\n\n"
                f"Правильный ответ: <b>{options[correct]}</b>\n"
                "<i>Очки за этот квест не начислены.</i>"
            ),
            outcome="failed",
            detail=options[correct],
        )

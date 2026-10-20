"""Викторина: вопрос и четыре варианта ответа."""

from __future__ import annotations

import random
from typing import Any

from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..content import QUIZ
from .. import style
from .base import BaseGame, Quest, Render, add_skip, pick_unseen


class QuizGame(BaseGame):
    type = "quiz"
    title = "Викторина"
    timed = False

    @classmethod
    async def build(
        cls,
        difficulty: str,
        rng: random.Random,
        exclude: set[str] | None = None,
    ) -> dict[str, Any]:
        pool = [item for item in QUIZ if item.get("diff") == difficulty] or list(QUIZ)
        item, exhausted = pick_unseen(pool, cls.item_key, rng, exclude)
        options = list(item["options"])
        order = list(range(len(options)))
        rng.shuffle(order)
        return {
            "q": item["q"],
            "options": [options[i] for i in order],
            "correct": order.index(item["correct"]),
            "cat": item["cat"],
            "_key": cls.item_key(item),
            "_exhausted": exhausted,
        }

    @classmethod
    def item_key(cls, item: dict[str, Any]) -> str:
        return f"quiz:{item['q']}"

    @classmethod
    def payload_key(cls, payload: dict[str, Any]) -> str:
        return cls.item_key({"q": payload.get("q", "")})

    @classmethod
    def render(cls, quest: Quest) -> Render:
        payload = quest.payload
        builder = InlineKeyboardBuilder()
        for index, option in enumerate(payload["options"]):
            builder.button(text=option, callback_data=f"g:{quest.id}:{index}")
        builder.adjust(1)
        add_skip(builder, quest.id, rows_before=4)
        return Render(
            text="\n".join(
                [
                    style.header(
                        "🧠",
                        "ВИКТОРИНА",
                        f"категория: {payload['cat']}",
                    ),
                    "",
                    style.question(payload["q"]),
                    style.note("Выбери ответ ↓"),
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
        if index == correct:
            return Render(
                text="\n".join(
                    [
                        style.header("✅", "ВЕРНО!"),
                        style.answer(options[correct]),
                    ]
                ),
                outcome="solved",
                detail=options[correct],
            )
        return Render(
            text="\n".join(
                [
                    style.header("❌", "НЕВЕРНО"),
                    style.answer(options[correct]),
                    style.note("Очки за этот квест не начислены."),
                ]
            ),
            outcome="failed",
            detail=options[correct],
        )

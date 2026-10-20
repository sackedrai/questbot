"""Быстрый квест: короткие вопросы, где решает скорость ответа."""

from __future__ import annotations

import random
from typing import Any

from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..content import FAST_QUIZ
from .. import style
from .base import Quest, Render, add_skip, pick_unseen
from .quiz import QuizGame


class FastGame(QuizGame):
    type = "fast"
    title = "Быстрый квест"
    timed = True

    @classmethod
    async def build(
        cls,
        difficulty: str,
        rng: random.Random,
        exclude: set[str] | None = None,
    ) -> dict[str, Any]:
        item, exhausted = pick_unseen(FAST_QUIZ, cls.item_key, rng, exclude)
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
        return f"fast:{item['q']}"

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
                    style.header("⚡", "БЫСТРЫЙ КВЕСТ", "за скорость дают бонус"),
                    "",
                    style.question(payload["q"]),
                    style.note("Отвечай быстро ↓"),
                ]
            ),
            markup=builder.as_markup(),
        )

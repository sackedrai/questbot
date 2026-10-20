"""Загадка: ответ вводится текстом, подсказка стоит очков."""

from __future__ import annotations

import random
from typing import Any

from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..config import HINT_PENALTY
from ..content import RIDDLES
from .. import style
from .base import BaseGame, Quest, Render, add_skip, is_answer_match

MAX_TRIES = 5


class RiddleGame(BaseGame):
    type = "riddle"
    title = "Загадка"

    @classmethod
    async def build(cls, difficulty: str, rng: random.Random) -> dict[str, Any]:
        item = rng.choice(RIDDLES)
        return {
            "q": item["q"],
            "answers": list(item["answers"]),
            "hint": item["hint"],
            "tries": 0,
            "hint_used": False,
        }

    @classmethod
    def render(cls, quest: Quest) -> Render:
        payload = quest.payload
        lines = [
            style.header("🧩", "ЗАГАДКА"),
            "",
            style.question(payload["q"]),
            "",
            f"<i>Попыток: {payload.get('tries', 0)}/{MAX_TRIES}</i>",
        ]
        if payload.get("hint_used"):
            lines += ["", f"💡 {style.note('Подсказка: ' + payload['hint'])}"]

        builder = InlineKeyboardBuilder()
        hint_shown = (
            not payload.get("hint_used") and payload.get("tries", 0) >= 2
        )
        if hint_shown:
            builder.button(
                text=f"💡 Подсказка (штраф ×{HINT_PENALTY})",
                callback_data=f"g:{quest.id}:hint",
            )
            builder.adjust(1)
        add_skip(builder, quest.id, rows_before=1 if hint_shown else 0)
        return Render(
            text="\n".join(lines),
            markup=builder.as_markup(),
            needs_input=True,
        )

    @classmethod
    async def on_text(cls, quest: Quest, text: str) -> Render:
        payload = quest.payload
        if is_answer_match(text, payload["answers"]):
            return Render(
                text="\n".join(
                    [
                        style.header("✅", "ВЕРНО!"),
                        style.answer(payload["answers"][0]),
                    ]
                ),
                outcome="solved",
                hint_used=bool(payload.get("hint_used")),
                detail=payload["answers"][0],
            )

        payload["tries"] = payload.get("tries", 0) + 1
        if payload["tries"] >= MAX_TRIES:
            return Render(
                text="\n".join(
                    [
                        style.header("❌", "СДАЁШЬСЯ"),
                        style.answer(payload["answers"][0]),
                        style.note("Очки за этот квест не начислены."),
                    ]
                ),
                outcome="failed",
                hint_used=bool(payload.get("hint_used")),
                detail=payload["answers"][0],
            )
        return Render(
            text="\n".join(
                [
                    style.header("❌", "НЕ ПОДХОДИТ"),
                    f"<i>Попыток: {payload['tries']}/{MAX_TRIES}</i>",
                ]
            ),
            markup=cls.render(quest).markup,
            needs_input=True,
        )

    @classmethod
    async def on_choice(cls, quest: Quest, choice: str) -> Render:
        if choice != "hint":
            return Render(text="Некорректное действие.")
        payload = quest.payload
        if payload.get("hint_used"):
            return Render(text="Подсказка уже была.", markup=cls.render(quest).markup)
        payload["hint_used"] = True
        return Render(
            text=cls.render(quest).text,
            markup=cls.render(quest).markup,
            needs_input=True,
            hint_used=True,
        )

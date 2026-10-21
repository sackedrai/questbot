"""Правда или ложь: утверждение, и нужно выбрать - правда это или нет."""

from __future__ import annotations

import random
from typing import Any

from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..content import TRUE_FALSE
from .. import style
from .base import BaseGame, Quest, Render, add_skip, pick_unseen


class TruthGame(BaseGame):
    type = "truth"
    title = "Правда или ложь"
    timed = False

    @classmethod
    async def build(
        cls,
        difficulty: str,
        rng: random.Random,
        exclude: set[str] | None = None,
    ) -> dict[str, Any]:
        pool = [item for item in TRUE_FALSE if item.get("diff") == difficulty] or list(
            TRUE_FALSE
        )
        item, exhausted = pick_unseen(pool, cls.item_key, rng, exclude)
        return {
            "t": item["t"],
            "a": bool(item["a"]),
            "why": item.get("why", ""),
            "cat": item.get("cat", "Факты"),
            "_key": cls.item_key(item),
            "_exhausted": exhausted,
        }

    @classmethod
    def item_key(cls, item: dict[str, Any]) -> str:
        return f"truth:{item['t']}"

    @classmethod
    def payload_key(cls, payload: dict[str, Any]) -> str:
        return cls.item_key({"t": payload.get("t", "")})

    @classmethod
    def render(cls, quest: Quest) -> Render:
        payload = quest.payload
        builder = InlineKeyboardBuilder()
        builder.button(text="✅ Правда", callback_data=f"g:{quest.id}:t")
        builder.button(text="❌ Ложь", callback_data=f"g:{quest.id}:f")
        builder.adjust(1)
        add_skip(builder, quest.id, rows_before=2)
        return Render(
            text="\n".join(
                [
                    style.header(
                        "⚖️",
                        "ПРАВДА ИЛИ ЛОЖЬ",
                        f"категория: {payload['cat']}",
                    ),
                    "",
                    style.question(payload["t"]),
                    style.note("Правда это или ложь? ↓"),
                ]
            ),
            markup=builder.as_markup(),
        )

    @classmethod
    async def on_choice(cls, quest: Quest, choice: str) -> Render:
        payload = quest.payload
        choice = (choice or "").strip().lower()
        if choice not in ("t", "f"):
            return Render(text="Некорректный выбор.")

        said_true = choice == "t"
        is_true = bool(payload["a"])
        why = payload.get("why") or ""
        answer = "Верно" if is_true else "Неверно"

        if said_true == is_true:
            lines = [style.header("✅", "ВЕРНО!"), style.answer(answer)]
            if why:
                lines.append(style.note(why))
            return Render(
                text="\n".join(lines),
                outcome="solved",
                detail=answer,
            )

        lines = [style.header("❌", "НЕВЕРНО"), style.answer(answer)]
        if why:
            lines.append(style.note(why))
        lines.append(style.note("Очки за этот квест не начислены."))
        return Render(
            text="\n".join(lines),
            outcome="failed",
            detail=answer,
        )

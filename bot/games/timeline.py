"""Хронология: расставить события в правильном порядке."""

from __future__ import annotations

import random
from typing import Any

from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..config import TIMELINE_MAX_MISTAKES
from ..content import TIMELINE_SETS
from .base import BaseGame, Quest, Render


class TimelineGame(BaseGame):
    type = "timeline"
    title = "Хронология"

    @classmethod
    async def build(cls, difficulty: str, rng: random.Random) -> dict[str, Any]:
        # Явно сортируем по числовому ключу — так порядок не зависит от
        # того, как события лежат в исходном наборе.
        items = sorted(
            (dict(item) for item in rng.choice(TIMELINE_SETS)),
            key=lambda item: item["year_num"],
        )
        order = list(range(len(items)))
        rng.shuffle(order)
        return {"items": items, "order": order, "collected": [], "mistakes": 0}

    @classmethod
    def render(cls, quest: Quest) -> Render:
        payload = quest.payload
        items = payload["items"]
        collected: list[int] = payload.get("collected", [])
        mistakes: int = payload.get("mistakes", 0)

        if collected:
            lines = ["<b>Собранная последовательность:</b>"]
            for index in collected:
                lines.append(f"• {items[index]['text']} ({items[index]['year']})")
            block = "\n".join(lines)
        else:
            block = "<i>Пока ничего не отсортировано</i>"

        text = (
            "🕰 <b>Хронология</b>\n\n"
            "События перемешаны. Нажимай на самое раннее из оставшихся — "
            "и так до конца.\n\n"
            f"{block}\n\n"
            f"⚠️ Ошибок: {mistakes}/{TIMELINE_MAX_MISTAKES}"
        )

        builder = InlineKeyboardBuilder()
        for index in payload["order"]:
            if index in collected:
                continue
            builder.button(
                text=items[index]["text"],
                callback_data=f"g:{quest.id}:{index}",
            )
        builder.adjust(1)
        return Render(text=text, markup=builder.as_markup())

    @classmethod
    async def on_choice(cls, quest: Quest, choice: str) -> Render:
        payload = quest.payload
        items = payload["items"]
        try:
            index = int(choice)
        except ValueError:
            return Render(text="Некорректный выбор.")
        if not 0 <= index < len(items):
            return Render(text="Некорректный выбор.")

        collected: list[int] = payload.setdefault("collected", [])
        if index in collected:
            return Render(
                text="Это событие уже в последовательности.",
                markup=cls.render(quest).markup,
            )

        expected = next(i for i in range(len(items)) if i not in collected)
        if index == expected:
            collected.append(index)
            if len(collected) == len(items):
                extra = 1.0 + 0.1 * (TIMELINE_MAX_MISTAKES - payload.get("mistakes", 0))
                return Render(
                    text=(
                        "✅ <b>Верно!</b>\n\n"
                        "Все события собраны в хронологическом порядке:\n"
                        + "\n".join(f"{n + 1}. {items[i]['text']} ({items[i]['year']})"
                                   for n, i in enumerate(collected))
                    ),
                    outcome="solved",
                    extra_mult=round(extra, 2),
                    detail=items[collected[-1]]["text"],
                )
            return Render(
                text=f"✅ Верно! Следующее: <b>{items[expected]['text']}</b>",
                markup=cls.render(quest).markup,
            )

        payload["mistakes"] = payload.get("mistakes", 0) + 1
        if payload["mistakes"] >= TIMELINE_MAX_MISTAKES:
            return Render(
                text=(
                    "❌ <b>Слишком много ошибок.</b>\n\n"
                    "Правильный порядок:\n"
                    + "\n".join(f"{n + 1}. {item['text']} ({item['year']})"
                               for n, item in enumerate(items))
                ),
                outcome="failed",
                detail="неправильный порядок",
            )
        return Render(
            text=(
                "❌ Не по порядку — это событие было позже.\n\n"
                f"⚠️ Ошибок: {payload['mistakes']}/{TIMELINE_MAX_MISTAKES}"
            ),
            markup=cls.render(quest).markup,
        )

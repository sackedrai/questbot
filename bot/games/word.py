"""Угадай слово: виселица, где угадывают по одной букве."""

from __future__ import annotations

import random
from typing import Any

from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..config import WORD_LIVES
from ..content import WORDS
from .. import style
from .base import BaseGame, Quest, Render, add_skip, normalize_answer, pick_unseen


class WordGame(BaseGame):
    type = "word"
    title = "Угадай слово"

    @classmethod
    async def build(
        cls,
        difficulty: str,
        rng: random.Random,
        exclude: set[str] | None = None,
    ) -> dict[str, Any]:
        item, exhausted = pick_unseen(WORDS, cls.item_key, rng, exclude)
        word = item["w"]
        return {
            "word": word,
            "cat": item["cat"],
            "revealed": [],
            "wrong": [],
            "lives": WORD_LIVES,
            "_key": cls.item_key(item),
            "_exhausted": exhausted,
        }

    @classmethod
    def item_key(cls, item: dict[str, Any]) -> str:
        return f"word:{item['w']}"

    @classmethod
    def payload_key(cls, payload: dict[str, Any]) -> str:
        return cls.item_key({"w": payload.get("word", "")})

    @classmethod
    def render(cls, quest: Quest) -> Render:
        payload = quest.payload
        word = payload["word"]
        revealed = set(payload.get("revealed", []))
        mask = " ".join(ch if i in revealed else "•" for i, ch in enumerate(word))

        lines = [
            style.header(
                "🔤",
                "УГАДАЙ СЛОВО",
                f"{payload['cat']}  ·  {len(word)} букв",
            ),
            "",
            f"<pre>{mask}</pre>",
            "",
            f"❤️  <b>{payload.get('lives', WORD_LIVES)}</b>"
            + (
                f"   ❌ {', '.join(payload['wrong'])}"
                if payload.get("wrong")
                else ""
            ),
            "",
            style.note("Отправь одну букву или всё слово целиком"),
        ]
        builder = InlineKeyboardBuilder()
        add_skip(builder, quest.id, rows_before=0)
        return Render(
            text="\n".join(lines),
            markup=builder.as_markup(),
            needs_input=True,
        )

    @classmethod
    async def on_text(cls, quest: Quest, text: str) -> Render:
        payload = quest.payload
        raw = text.strip()
        if not raw:
            return Render(text="Пустое сообщение — отправь букву.", needs_input=True)

        word = payload["word"]
        wrong: list[str] = payload.setdefault("wrong", [])
        revealed: list[int] = payload.setdefault("revealed", [])

        if len(raw) == 1 and raw.isalpha():
            letter = raw.upper()
            if letter in wrong:
                return Render(
                    text=f"Буква «{letter}» уже пробовал.",
                    needs_input=True,
                )
            if letter in word:
                for index, char in enumerate(word):
                    if char == letter and index not in revealed:
                        revealed.append(index)
                if len(revealed) == len(word):
                    extra = cls._extra_mult(len(wrong))
                    return Render(
                        text="\n".join(
                            [
                                style.header("✅", "ВЕРНО!"),
                                style.answer(word),
                            ]
                        ),
                        outcome="solved",
                        extra_mult=extra,
                        detail=word,
                    )
                return Render(text=cls.render(quest).text, needs_input=True)

            wrong.append(letter)
            payload["lives"] = payload.get("lives", WORD_LIVES) - 1
            if payload["lives"] <= 0:
                return Render(
                    text="\n".join(
                        [
                            style.header("❌", "ЖИЗНИ КОНЧИЛИСЬ"),
                            style.answer(word),
                            style.note("Очки за этот квест не начислены."),
                        ]
                    ),
                    outcome="failed",
                    detail=word,
                )
            return Render(text=cls.render(quest).text, needs_input=True)

        # игрок назвал слово целиком
        if normalize_answer(raw) == normalize_answer(word):
            extra = cls._extra_mult(len(wrong))
            return Render(
                text="\n".join(
                    [
                        style.header("✅", "ВЕРНО!"),
                        style.answer(word),
                    ]
                ),
                outcome="solved",
                extra_mult=extra,
                detail=word,
            )

        wrong.append(raw[:1].upper())
        payload["lives"] = payload.get("lives", WORD_LIVES) - 1
        if payload["lives"] <= 0:
            return Render(
                text="\n".join(
                    [
                        style.header("❌", "ЖИЗНИ КОНЧИЛИСЬ"),
                        style.answer(word),
                        style.note("Очки за этот квест не начислены."),
                    ]
                ),
                outcome="failed",
                detail=word,
            )
        return Render(
            text="\n".join(
                [
                    style.header("❌", "НЕ ТО СЛОВО"),
                    cls.render(quest).text.split("\n", 2)[-1],
                ]
            ),
            needs_input=True,
        )

    @staticmethod
    def _extra_mult(wrong_count: int) -> float:
        if wrong_count == 0:
            return 1.15
        return round(max(0.6, 1.0 - 0.07 * wrong_count), 2)

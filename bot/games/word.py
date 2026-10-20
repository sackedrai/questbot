"""Угадай слово: виселица, где угадывают по одной букве."""

from __future__ import annotations

import random
from typing import Any

from ..config import WORD_LIVES
from ..content import WORDS
from .base import BaseGame, Quest, Render, normalize_answer


class WordGame(BaseGame):
    type = "word"
    title = "Угадай слово"

    @classmethod
    async def build(cls, difficulty: str, rng: random.Random) -> dict[str, Any]:
        item = rng.choice(WORDS)
        word = item["w"]
        return {
            "word": word,
            "cat": item["cat"],
            "revealed": [],
            "wrong": [],
            "lives": WORD_LIVES,
        }

    @classmethod
    def render(cls, quest: Quest) -> Render:
        payload = quest.payload
        word = payload["word"]
        revealed = set(payload.get("revealed", []))
        mask = "".join(ch if i in revealed else "•" for i, ch in enumerate(word))

        lines = [
            "🔤 <b>Угадай слово</b>",
            "",
            f"Категория: <i>{payload['cat']}</i>",
            f"Длина: {len(word)} букв",
            "",
            f"<code>{mask}</code>",
            "",
            f"❤️  Жизней: {payload.get('lives', WORD_LIVES)}",
        ]
        if payload.get("wrong"):
            lines.append(f"❌ Уже пробовал: {', '.join(payload['wrong'])}")
        lines += ["", "<i>Отправь одну букву или всё слово целиком</i>"]
        return Render(text="\n".join(lines), needs_input=True)

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
                        text=f"✅ <b>Верно!</b>\n\nСлово: <b>{word}</b>",
                        outcome="solved",
                        extra_mult=extra,
                        detail=word,
                    )
                return Render(text=cls.render(quest).text, needs_input=True)

            wrong.append(letter)
            payload["lives"] = payload.get("lives", WORD_LIVES) - 1
            if payload["lives"] <= 0:
                return Render(
                    text=(
                        "❌ <b>Жизни кончились.</b>\n\n"
                        f"Слово было: <b>{word}</b>\n"
                        "<i>Очки за этот квест не начислены.</i>"
                    ),
                    outcome="failed",
                    detail=word,
                )
            return Render(text=cls.render(quest).text, needs_input=True)

        # игрок назвал слово целиком
        if normalize_answer(raw) == normalize_answer(word):
            extra = cls._extra_mult(len(wrong))
            return Render(
                text=f"✅ <b>Верно!</b>\n\nСлово: <b>{word}</b>",
                outcome="solved",
                extra_mult=extra,
                detail=word,
            )

        wrong.append(raw[:1].upper())
        payload["lives"] = payload.get("lives", WORD_LIVES) - 1
        if payload["lives"] <= 0:
            return Render(
                text=(
                    "❌ <b>Жизни кончились.</b>\n\n"
                    f"Слово было: <b>{word}</b>\n"
                    "<i>Очки за этот квест не начислены.</i>"
                ),
                outcome="failed",
                detail=word,
            )
        return Render(
            text=f"❌ Не то слово.\n\n" + cls.render(quest).text.split("\n", 2)[-1],
            needs_input=True,
        )

    @staticmethod
    def _extra_mult(wrong_count: int) -> float:
        if wrong_count == 0:
            return 1.15
        return round(max(0.6, 1.0 - 0.07 * wrong_count), 2)

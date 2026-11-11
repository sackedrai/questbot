"""Угадай слово: виселица, где угадывают по одной букве."""

from __future__ import annotations

import random
from typing import Any

from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..config import HINT_PENALTY, WORD_LIVES
from ..content import WORDS
from .. import style
from .base import (
    BaseGame,
    Quest,
    Render,
    add_skip,
    normalize_answer,
    pick_by_difficulty,
)


class WordGame(BaseGame):
    type = "word"
    title = "Угадай слово"

    @staticmethod
    def lives_for(word: str) -> int:
        """Сколько жизней у слова такой длины.

        Раньше было 7 на любое слово, и «ЭКОСИСТЕМА» (11 букв) была
        неугадываемой. Теперь чем длиннее слово, тем больше попыток.
        """
        length = len(word)
        if length <= 4:
            return 5
        if length <= 6:
            return 6
        if length <= 8:
            return 7
        return 9

    @classmethod
    async def build(
        cls,
        difficulty: str,
        rng: random.Random,
        exclude: set[str] | None = None,
    ) -> dict[str, Any]:
        item, exhausted = pick_by_difficulty(
            WORDS, difficulty, cls.item_key, rng, exclude
        )
        word = item["w"]
        return {
            "word": word,
            "cat": item["cat"],
            "revealed": [],
            "wrong": [],
            "lives": cls.lives_for(word),
            "hint_used": False,
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
        # Подсказка открывает одну букву, но стоит очков - как в загадке.
        hint_shown = (
            not payload.get("hint_used")
            and len(revealed) < len(word)
            and payload.get("lives", WORD_LIVES) > 0
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
        raw = text.strip()
        if not raw:
            return Render(
                text="Пустое сообщение — отправь букву.",
                needs_input=True,
                keep_markup=cls.render(quest).markup,
            )

        word = payload["word"]
        wrong: list[str] = payload.setdefault("wrong", [])
        revealed: list[int] = payload.setdefault("revealed", [])

        if len(raw) == 1 and raw.isalpha():
            letter = raw.upper()
            if letter in wrong:
                return Render(
                    text=f"Буква «{letter}» уже пробовал.",
                    needs_input=True,
                    keep_markup=cls.render(quest).markup,
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
                        hint_used=bool(payload.get("hint_used")),
                        detail=word,
                    )
                return Render(
                    text=cls.render(quest).text,
                    needs_input=True,
                    keep_markup=cls.render(quest).markup,
                )

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
                    hint_used=bool(payload.get("hint_used")),
                    detail=word,
                )
            return Render(
                text=cls.render(quest).text,
                needs_input=True,
                keep_markup=cls.render(quest).markup,
            )

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
                hint_used=bool(payload.get("hint_used")),
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
                hint_used=bool(payload.get("hint_used")),
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
            keep_markup=cls.render(quest).markup,
        )

    @classmethod
    async def on_choice(cls, quest: Quest, choice: str) -> Render:
        """Подсказка: открывает одну неназванную букву."""
        payload = quest.payload
        if choice != "hint":
            return Render(
                text="Некорректное действие.",
                keep_markup=cls.render(quest).markup,
            )
        if payload.get("hint_used"):
            return Render(
                text="Подсказка уже была.",
                markup=cls.render(quest).markup,
                needs_input=True,
            )

        word = payload["word"]
        revealed: list[int] = payload.setdefault("revealed", [])
        hidden = [i for i in range(len(word)) if i not in revealed]
        if not hidden:
            return Render(
                text="Все буквы уже открыты.",
                markup=cls.render(quest).markup,
                needs_input=True,
            )

        payload["hint_used"] = True
        revealed.append(hidden[0])
        return Render(
            text=cls.render(quest).text,
            markup=cls.render(quest).markup,
            needs_input=True,
            hint_used=True,
        )

    @staticmethod
    def _extra_mult(wrong_count: int) -> float:
        if wrong_count == 0:
            return 1.15
        return round(max(0.6, 1.0 - 0.07 * wrong_count), 2)

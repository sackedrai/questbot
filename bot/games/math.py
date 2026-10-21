"""Счёт: арифметика, которую бот генерирует сам.

В отличие от остальных игр, у этого типа нет банка заданий - примеры
собираются на лету. Поэтому вариантов бесконечно много, а с ротатором
повторов не бывает вовсе.
"""

from __future__ import annotations

import random
from typing import Any

from aiogram.utils.keyboard import InlineKeyboardBuilder

from .. import style
from .base import BaseGame, Quest, Render, add_skip, pick_unseen


def _make_problem(
    difficulty: str, rng: random.Random
) -> tuple[str, int, str]:
    """Собрать пример. Возвращает (текст, ответ, категория)."""
    if difficulty == "easy":
        a, b = rng.randint(2, 20), rng.randint(2, 20)
        if rng.random() < 0.5:
            return f"{a} + {b} = ?", a + b, "Сложение"
        if b > a:
            a, b = b, a
        return f"{a} − {b} = ?", a - b, "Вычитание"

    if difficulty == "medium":
        pick = rng.random()
        if pick < 0.35:
            a, b = rng.randint(3, 12), rng.randint(3, 12)
            return f"{a} × {b} = ?", a * b, "Умножение"
        if pick < 0.7:
            b = rng.randint(2, 12)
            a = b * rng.randint(2, 9)
            return f"{a} ÷ {b} = ?", a // b, "Деление"
        a, b = rng.randint(20, 99), rng.randint(10, 40)
        return f"{a} + {b} = ?", a + b, "Сложение"

    # сложный: два шага
    pick = rng.random()
    if pick < 0.35:
        a, b, c = rng.randint(2, 9), rng.randint(2, 9), rng.randint(2, 9)
        return f"({a} + {b}) × {c} = ?", (a + b) * c, "Два шага"
    if pick < 0.7:
        a, b, c = rng.randint(2, 9), rng.randint(2, 9), rng.randint(2, 9)
        return f"{a} × {b} + {c} = ?", a * b + c, "Два шага"
    c = rng.randint(2, 9)
    k = rng.randint(3, 9)
    a = rng.randint(10, 40)
    b = c * k - a
    if b < 1:
        a, b = 1, c * k - 1
    return f"({a} + {b}) ÷ {c} = ?", k, "Два шага"


def _make_options(answer: int, rng: random.Random) -> list[int]:
    """Ответ и три близких к нему варианта."""
    options = {answer}
    step = max(1, answer // 8)
    guard = 0
    while len(options) < 4 and guard < 50:
        guard += 1
        delta = rng.choice([-3, -2, -1, 1, 2, 3]) * step
        candidate = answer + delta
        if candidate >= 0:
            options.add(candidate)
    while len(options) < 4:  # совсем крайний случай
        options.add(answer + len(options))
    return sorted(options)


class MathGame(BaseGame):
    type = "math"
    title = "Счёт"
    timed = True

    @classmethod
    async def build(
        cls,
        difficulty: str,
        rng: random.Random,
        exclude: set[str] | None = None,
    ) -> dict[str, Any]:
        question, answer, cat = _make_problem(difficulty, rng)
        options = _make_options(answer, rng)
        order = list(range(len(options)))
        rng.shuffle(order)
        shuffled = [options[i] for i in order]
        return {
            "q": question,
            "options": [str(value) for value in shuffled],
            "correct": shuffled.index(answer),
            "cat": cat,
            "_key": f"math:{question}",
            "_exhausted": False,
        }

    @classmethod
    def item_key(cls, item: dict[str, Any]) -> str:
        return f"math:{item.get('q', '')}"

    @classmethod
    def payload_key(cls, payload: dict[str, Any]) -> str:
        return cls.item_key({"q": payload.get("q", "")})

    @classmethod
    def render(cls, quest: Quest) -> Render:
        payload = quest.payload
        builder = InlineKeyboardBuilder()
        for index, option in enumerate(payload["options"]):
            builder.button(text=option, callback_data=f"g:{quest.id}:{index}")
        builder.adjust(2)
        add_skip(builder, quest.id, rows_before=2)
        return Render(
            text="\n".join(
                [
                    style.header(
                        "🧮",
                        "СЧЁТ",
                        f"категория: {payload['cat']}",
                    ),
                    "",
                    style.question(payload["q"]),
                    style.note("Посчитай и выбери ответ ↓"),
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

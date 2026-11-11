"""Базовые классы для мини-игр."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Optional, Sequence

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

_PUNCT = re.compile(r"[^\w\s]", flags=re.UNICODE)


def pick_unseen(
    pool: Sequence[Any],
    key_of: Callable[[Any], str],
    rng: Any,
    exclude: Optional[set[str]] = None,
) -> tuple[Any, bool]:
    """Выбрать задание, которого игрок ещё не проходил.

    ``exclude`` - ключи уже пройденных заданий (ротатор).
    Возвращает пару (задание, банк_исчерпан). Если непроходимых заданий не
    осталось - берём из полного пула: контент прокрутился заново, об этом
    честно говорим игроку.
    """
    exclude = exclude or set()
    fresh = [item for item in pool if key_of(item) not in exclude]
    if fresh:
        return rng.choice(fresh), False
    return rng.choice(list(pool)), True


def pick_by_difficulty(
    pool: Sequence[Any],
    difficulty: str,
    key_of: Callable[[Any], str],
    rng: Any,
    exclude: Optional[set[str]] = None,
    diff_of: Optional[Callable[[Any], str]] = None,
) -> tuple[Any, bool]:
    """Выбрать задание нужной сложности, не проходившееся раньше.

    Раньше сложность влияла только на викторину и «Правда или ложь»:
    остальные пять игр выбирали задание из всего пула, и игроку с
    уровнем «🟢 Лёгкий» могло выпасть то же самое, что и с «🔴 Сложный».
    Теперь фильтр общий для всех игр.

    ``diff_of`` - как достать сложность из элемента. По умолчанию это
    поле ``diff`` (у хронологии сложность лежит на наборе, а не на
    событии, поэтому там передают свою функцию).

    Если заданий нужной сложности нет или все пройдены - берём из
    полного пула: контент не должен кончаться из-за разметки.
    """
    exclude = exclude or set()
    getter = diff_of or (lambda item: str(item.get("diff", "")))

    level = [item for item in pool if getter(item) == difficulty]
    if level:
        fresh = [item for item in level if key_of(item) not in exclude]
        if fresh:
            return rng.choice(fresh), False

    return pick_unseen(pool, key_of, rng, exclude)



def normalize_answer(text: str) -> str:
    """Привести ответ к сравнимому виду: нижний регистр, без «ё» и пунктуации."""
    lowered = text.strip().lower().replace("ё", "е")
    cleaned = _PUNCT.sub("", lowered)
    return re.sub(r"\s+", " ", cleaned).strip()


def is_answer_match(given: str, accepted: list[str]) -> bool:
    """Мягкое сравнение: точное совпадение или вхождение в ответ."""
    given_norm = normalize_answer(given)
    if not given_norm:
        return False
    for option in accepted:
        option_norm = normalize_answer(option)
        if not option_norm:
            continue
        if given_norm == option_norm:
            return True
        if len(option_norm) >= 4 and option_norm in given_norm:
            return True
    return False


@dataclass
class Quest:
    """Один выданный квест."""

    id: int
    tg_id: int
    day: str
    game_type: str
    difficulty: str
    payload: dict[str, Any]
    points: int = 0
    status: str = "active"
    risky: int = 0
    started_at: float = 0.0
    pvp_id: int = 0

    @classmethod
    def from_row(cls, row: Any) -> "Quest":
        return cls(
            id=row["id"],
            tg_id=row["tg_id"],
            day=row["day"],
            game_type=row["game_type"],
            difficulty=row["difficulty"],
            payload=json.loads(row["payload"]),
            points=row["points"],
            status=row["status"],
            risky=row["risky"],
            started_at=row["started_at"],
            pvp_id=row["pvp_id"] if "pvp_id" in row.keys() else 0,
        )


@dataclass
class Render:
    """Результат отрисовки шага игры."""

    text: str
    markup: Optional[InlineKeyboardMarkup] = None
    outcome: Optional[str] = None  # "solved" | "failed"
    hint_used: bool = False
    extra_mult: float = 1.0
    needs_input: bool = False
    detail: str = ""
    # Разметка, которую надо вернуть, если своя пустая. Без неё
    # сообщение об ошибке («Некорректный выбор») срывает клавиатуру
    # с экрана квеста - и игрок остаётся без кнопок вообще.
    keep_markup: Optional[InlineKeyboardMarkup] = None


def add_skip(
    builder: InlineKeyboardBuilder, quest_id: int, rows_before: int = 0
) -> InlineKeyboardBuilder:
    """Кнопки «Сдаться» и «В меню» одной строкой внизу.

    ``rows_before`` - сколько строк уже занято кнопками игры: ширины
    задаются списком, иначе последние кнопки съезжают в одну строку
    вместе с предыдущими.
    """
    builder.row()
    builder.button(text="⏭ Сдаться", callback_data=f"skip:{quest_id}")
    builder.button(text="🔙 В меню", callback_data="menu:home")
    builder.adjust(*([1] * rows_before + [2]))
    return builder


class BaseGame:
    """Интерфейс мини-игры.

    Каждая игра умеет: собрать задание, нарисовать его и обработать
    действие игрока (нажатие кнопки или текстовый ответ).
    """

    type: str = ""
    title: str = ""
    timed: bool = False

    @classmethod
    async def build(
        cls,
        difficulty: str,
        rng: Any,
        exclude: Optional[set[str]] = None,
    ) -> dict[str, Any]:
        """Собрать задание.

        ``exclude`` - ключи заданий, которые игрок уже проходил: если такие
        есть, выбираем из оставшихся. В payload кладём ``_key`` (ключ
        задания для ротатора) и ``_exhausted`` (банк исчерпан).
        """
        raise NotImplementedError

    @classmethod
    def item_key(cls, item: Any) -> str:
        """Ключ задания - по нему ротатор видит, что игрок это уже проходил."""
        return str(item)

    @classmethod
    def payload_key(cls, payload: dict[str, Any]) -> str:
        """Ключ задания по сохранённому payload.

        Нужен, чтобы восстановить ключи у квестов, выданных до появления
        ротатора.
        """
        return ""

    @classmethod
    def render(cls, quest: Quest) -> Render:
        raise NotImplementedError

    @classmethod
    async def on_choice(cls, quest: Quest, choice: str) -> Render:
        return Render(
            text="Этот квест не поддерживает нажатия.",
            keep_markup=cls.render(quest).markup,
        )

    @classmethod
    async def on_text(cls, quest: Quest, text: str) -> Render:
        return Render(
            text="Этот квест не принимает текстовый ответ.",
            keep_markup=cls.render(quest).markup,
        )

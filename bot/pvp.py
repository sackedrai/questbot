"""PvP один на один.

Двое игроков получают одинаковый квест. Кто набрал больше очков -
победил. При равном счёте - ничья.
"""

from __future__ import annotations

import random
import secrets

from . import adaptive
from .db import db
from .games import get_game

GAME_TYPES = ("quiz", "fast", "timeline", "riddle", "word")

# Без похожих символов (0/O, 1/I), чтобы код можно было продиктовать
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

GAME_TITLES = {
    "quiz": "🧠 Викторина",
    "fast": "⚡ Быстрый квест",
    "timeline": "🕰 Хронология",
    "riddle": "🧩 Загадка",
    "word": "🔤 Угадай слово",
}


def make_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))


async def create_challenge(player1: int) -> str:
    """Создать вызов на бой и вернуть код для ссылки."""
    game_type = random.choice(GAME_TYPES)
    difficulty = await adaptive.pick_difficulty(player1)
    game = get_game(game_type)
    payload = await game.build(difficulty, random.Random())

    for _ in range(8):
        code = make_code()
        if await db.get_pvp_by_code(code) is None:
            await db.create_pvp_match(player1, game_type, difficulty, payload, code)
            return code
    raise RuntimeError("не удалось создать код вызова")


async def accept_challenge(code: str, player2: int) -> tuple[str, object]:
    """Принять вызов. Возвращает (статус, матч)."""
    match = await db.get_pvp_by_code(code.upper().strip())
    if match is None:
        return "not_found", None
    if match["player2"]:
        return "taken", match
    if match["player1"] == player2:
        return "self", match
    if match["status"] != "waiting":
        return "closed", match

    await db.accept_pvp(match["id"], player2)
    return "ok", await db.get_pvp_match(match["id"])


async def player_name(tg_id: int) -> str:
    user = await db.get_user(tg_id)
    if user is None:
        return "Игрок"
    return user["nickname"] or user["display_name"] or "Игрок"


async def opponent_of(match, tg_id: int) -> int:
    return match["player2"] if match["player1"] == tg_id else match["player1"]


async def format_match(match, tg_id: int) -> str:
    """Текст со счётом матча для конкретного игрока."""
    from . import style

    me = match["player1"] if match["player1"] == tg_id else match["player2"]
    my_points = match["points1"] if me == match["player1"] else match["points2"]
    their = await opponent_of(match, tg_id)
    their_points = match["points2"] if me == match["player1"] else match["points1"]
    my_name = await player_name(me)
    their_name = await player_name(their)

    if match["status"] != "finished":
        return "\n".join(
            [
                style.header("⚔️", "МАТЧ НЕ ЗАВЕРШЁН"),
                f"Ты: <b>{my_points if my_points >= 0 else '—'}</b>",
                f"{their_name}: <b>{their_points if their_points >= 0 else '—'}</b>",
            ]
        )

    if match["winner"] == me:
        verdict = "🏆 <b>ТЫ ПОБЕДИЛ!</b>"
    elif match["winner"] == their:
        verdict = "😔 <b>ПОРАЖЕНИЕ</b>"
    else:
        verdict = "🤝 <b>НИЧЬЯ</b>"

    return "\n".join(
        [
            style.header("⚔️", "МАТЧ ОКОНЧЕН"),
            verdict,
            "",
            style.stats(
                [
                    ("", my_name, str(my_points)),
                    ("", their_name, str(their_points)),
                ]
            ),
        ]
    )

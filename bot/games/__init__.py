"""Реестр мини-игр."""

from __future__ import annotations

from .base import BaseGame, Quest, Render
from .fast import FastGame
from .math import MathGame
from .quiz import QuizGame
from .riddle import RiddleGame
from .timeline import TimelineGame
from .truth import TruthGame
from .word import WordGame

GAMES: dict[str, type[BaseGame]] = {
    game.type: game
    for game in (
        QuizGame,
        FastGame,
        TimelineGame,
        RiddleGame,
        WordGame,
        TruthGame,
        MathGame,
    )
}

# Игры, где игрок отвечает текстом
TEXT_GAMES = ("riddle", "word")

# Игры, где решает скорость ответа
TIMED_GAMES = ("fast", "math")

# Порядок выбора случайной мини-игры. Единственный источник: и сервис
# выдачи квестов, и PvP берут список отсюда.
GAME_TYPES = ("quiz", "fast", "timeline", "riddle", "word", "truth", "math")


def get_game(game_type: str) -> type[BaseGame]:
    try:
        return GAMES[game_type]
    except KeyError as exc:  # pragma: no cover - защита от опечаток
        raise KeyError(f"Неизвестный тип игры: {game_type}") from exc


__all__ = ["GAMES", "TEXT_GAMES", "TIMED_GAMES", "get_game", "BaseGame", "Quest", "Render"]

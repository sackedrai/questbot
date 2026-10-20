"""Состояния FSM."""

from aiogram.fsm.state import State, StatesGroup


class Onboarding(StatesGroup):
    """Первое знакомство: ник и сложность."""

    nickname = State()
    difficulty = State()


class Game(StatesGroup):
    """Активный квест, ожидающий текстовый ответ."""

    answer = State()

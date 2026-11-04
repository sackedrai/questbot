"""Состояния FSM."""

from aiogram.fsm.state import State, StatesGroup


class Onboarding(StatesGroup):
    """Первое знакомство: ник и сложность."""

    nickname = State()
    difficulty = State()
    tz = State()


class Game(StatesGroup):
    """Активный квест, ожидающий текстовый ответ."""

    answer = State()


class AdminPanel(StatesGroup):
    """Админка: ждём текст объявления."""

    broadcast = State()


class AskQuestion(StatesGroup):
    """Игрок придумывает свой вопрос для общего банка."""

    waiting_question = State()
    waiting_answer = State()
    waiting_options = State()
    waiting_category = State()
    waiting_difficulty = State()

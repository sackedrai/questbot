"""Клавиатуры."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .config import DIFFICULTY_TITLES


def main_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🎯 Квест дня", callback_data="menu:quest")
    builder.button(text="⚡ Рискованный квест ×2", callback_data="menu:risk")
    builder.button(text="🏆 Рейтинг", callback_data="menu:top")
    builder.button(text="👤 Профиль", callback_data="menu:profile")
    builder.button(text="ℹ️ Как играть", callback_data="menu:help")
    builder.adjust(1)
    return builder.as_markup()


def difficulty_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for key in ("easy", "medium", "hard"):
        builder.button(text=DIFFICULTY_TITLES[key], callback_data=f"diff:{key}")
    builder.adjust(1)
    return builder.as_markup()


def after_quest_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⚡ Ещё один (риск ×2)", callback_data="menu:risk")
    builder.button(text="🏆 Рейтинг", callback_data="menu:top")
    builder.button(text="👤 Профиль", callback_data="menu:profile")
    builder.button(text="🔙 В меню", callback_data="menu:home")
    builder.adjust(1)
    return builder.as_markup()


def top_menu(active_scope: str = "all") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    marks = {"today": "✅ ", "week": "✅ ", "all": "✅ "}
    builder.button(text=f"{marks['today']}Сегодня", callback_data="top:today")
    builder.button(text=f"{marks['week']}Неделя", callback_data="top:week")
    builder.button(text=f"{marks['all']}Всё время", callback_data="top:all")
    builder.adjust(1)
    return builder.as_markup()

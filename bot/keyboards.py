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
    builder.button(text="🧹 Очистить чат", callback_data="menu:clear")
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
    scopes = (("today", "📅 Сегодня"), ("week", "🗓 Неделя"), ("all", "🌍 Всё время"))
    for key, title in scopes:
        mark = "• " if key == active_scope else ""
        builder.button(text=f"{mark}{title}", callback_data=f"top:{key}")
    builder.adjust(1)
    return builder.as_markup()

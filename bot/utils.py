"""Мелкие утилиты для хендлеров."""

from __future__ import annotations

from typing import Optional

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup, Message


async def safe_edit(
    message: Message,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
) -> None:
    """Изменить сообщение, а если это невозможно — отправить новое.

    Telegram не даёт отредактировать сообщение, если текст не изменился,
    поэтому в таком случае просто отправляем новое.
    """
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest:
        await message.answer(text, reply_markup=reply_markup)

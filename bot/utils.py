"""Мелкие утилиты для хендлеров."""

from __future__ import annotations

from typing import Iterable, Optional

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


async def cleanup_chat(
    bot: Bot,
    chat_id: int,
    db,
    keep: Iterable[int] = (),
    limit: int = 50,
) -> int:
    """Удалить из чата ранее отправленные ботом сообщения.

    Возвращает количество удалённых сообщений. Сообщения, которые Telegram
    уже не даёт удалить (старше 48 часов), просто забываются.
    """
    keep_ids = set(keep)
    message_ids = await db.chat_messages(chat_id, limit=limit)
    removed = 0
    forgotten: list[int] = []

    for message_id in message_ids:
        if message_id in keep_ids:
            continue
        try:
            await bot.delete_message(chat_id, message_id)
            removed += 1
            forgotten.append(message_id)
        except TelegramBadRequest:
            # слишком старое или уже удалено - больше не мучаемся
            forgotten.append(message_id)
        except Exception:
            continue

    await db.forget_messages(chat_id, forgotten)
    return removed

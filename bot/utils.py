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

    Если текст не изменился, Telegram отвечает ошибкой "message is not
    modified" - в этом случае просто ничего не делаем, иначе сообщение
    размножится в чате.
    """
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc).lower():
            return
        await message.answer(text, reply_markup=reply_markup)


async def wipe_chat(
    bot: Bot,
    chat_id: int,
    db,
    up_to_id: int,
    margin: int = 20,
    window: int = 100,
    keep: Iterable[int] = (),
) -> tuple[int, int]:
    """Удалить из чата все сообщения - и бота, и пользователя.

    В личном чате бот имеет право удалять сообщения обеих сторон,
    поэтому можно вычистить переписку целиком.

    Возвращает (удалено, проверено). Сообщения старше 48 часов Telegram
    удалять не даёт - их просто пропускаем.
    """
    keep_ids = set(keep)
    tracked = await db.chat_messages(chat_id, limit=200)
    if tracked:
        low = max(1, min(tracked) - margin)
    else:
        low = max(1, up_to_id - window)

    candidates = [
        i for i in range(low, up_to_id + 1) if i > 0 and i not in keep_ids
    ]
    if not candidates:
        return 0, 0

    deleted = 0
    failed: list[int] = []

    # сначала пачками - так быстрее
    for start in range(0, len(candidates), 50):
        chunk = candidates[start:start + 50]
        try:
            await bot.delete_messages(chat_id, chunk)
            deleted += len(chunk)
        except Exception:
            failed.extend(chunk)

    # что пачкой не вышло - пробуем по одному
    for message_id in failed:
        try:
            await bot.delete_message(chat_id, message_id)
            deleted += 1
        except Exception:
            continue

    await db.forget_messages(chat_id, candidates)
    return deleted, len(candidates)


async def auto_clean(
    bot: Bot,
    chat_id: int,
    db,
    up_to_id: int = 0,
    keep: Iterable[int] = (),
) -> int:
    """Убрать из чата прошлые сообщения - и бота, и игрока.

    В личном чате бот имеет право удалять сообщения обеих сторон, так
    что в чате остаётся ровно то, что бот показывает сейчас.

    ``up_to_id`` - до какого сообщения чистим включительно. Если не
    задан, берём последнее сообщение бота в этом чате.
    """
    if not up_to_id:
        tracked = await db.chat_messages(chat_id, limit=200)
        up_to_id = max(tracked, default=0)
    if not up_to_id:
        return 0
    deleted, _ = await wipe_chat(
        bot, chat_id, db, up_to_id=up_to_id, keep=keep
    )
    return deleted


async def open_screen(
    bot: Bot,
    message: Message,
    db,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
) -> Message:
    """Открыть новый экран: сперва убрать из чата прошлые сообщения.

    Экраны, которые бот правит на месте (safe_edit), чистить не нужно -
    а вот новые сообщения иначе копятся в чате.
    """
    await auto_clean(bot, message.chat.id, db, up_to_id=message.message_id)
    return await message.answer(text, reply_markup=reply_markup)

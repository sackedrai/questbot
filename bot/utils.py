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

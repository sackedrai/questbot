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


# Сколько последних номеров сообщений чистим «вслепую» - на случай, если
# сообщение игрока не отследилось. Больше не нужно: перебор большого
# диапазона недопустим, номера в чате растут быстро, и удаление тысячи
# сообщений по одному занимает десятки минут.
BLIND_WINDOW = 30

# Сколько известных сообщений держим в базе для чистки
TRACKED_LIMIT = 100


async def _delete_ids(
    bot: Bot,
    chat_id: int,
    db,
    ids: Iterable[int],
) -> int:
    """Удалить перечисленные сообщения и забыть их в базе."""
    deleted = 0
    forgotten: list[int] = []
    for message_id in ids:
        try:
            await bot.delete_message(chat_id, message_id)
            deleted += 1
        except Exception:  # noqa: BLE001 - старое или уже удалено
            pass
        forgotten.append(message_id)
    await db.forget_messages(chat_id, forgotten)
    return deleted


async def wipe_chat(
    bot: Bot,
    chat_id: int,
    db,
    up_to_id: int,
    window: int = 100,
    keep: Iterable[int] = (),
) -> tuple[int, int]:
    """Удалить из чата сообщения - и бота, и пользователя.

    В личном чате бот имеет право удалять сообщения обеих сторон,
    поэтому можно вычистить переписку целиком.

    Возвращает (удалено, проверено). Сообщения старше 48 часов Telegram
    удалять не даёт - их просто пропускаем.
    """
    keep_ids = set(keep)
    tracked = await db.chat_messages(chat_id, limit=TRACKED_LIMIT)
    targets = {i for i in tracked if i <= up_to_id}
    low = max(1, up_to_id - window)
    targets.update(range(low, up_to_id + 1))
    ids = sorted(i for i in targets if i not in keep_ids)
    if not ids:
        return 0, 0
    deleted = await _delete_ids(bot, chat_id, db, ids)
    return deleted, len(ids)


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
    keep_ids = set(keep)
    tracked = await db.chat_messages(chat_id, limit=TRACKED_LIMIT)
    if not up_to_id:
        up_to_id = max(tracked, default=0)
    if not up_to_id:
        return 0
    targets = {i for i in tracked if i <= up_to_id}
    low = max(1, up_to_id - BLIND_WINDOW)
    targets.update(range(low, up_to_id + 1))
    ids = sorted(i for i in targets if i not in keep_ids)
    return await _delete_ids(bot, chat_id, db, ids)


async def keep_only(
    bot: Bot,
    chat_id: int,
    db,
    keep_id: int,
) -> int:
    """Оставить в чате только одно сообщение бота - остальные удалить.

    Нужно при возврате в меню: в чате могли остаться другие экраны
    (например, сообщение с вызовом на бой), и тогда меню получалось бы
    не одно, а два.

    Сообщения, которые Telegram уже не даёт удалить (старше 48 часов),
    просто забываем - иначе таблица в базе будет расти вечно.
    """
    message_ids = await db.chat_messages(chat_id, limit=200)
    removed = 0
    forgotten: list[int] = []

    for message_id in message_ids:
        if message_id == keep_id:
            continue
        try:
            await bot.delete_message(chat_id, message_id)
            removed += 1
        except Exception:  # noqa: BLE001 - старое или уже удалено
            pass
        forgotten.append(message_id)

    await db.forget_messages(chat_id, forgotten)
    return removed


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

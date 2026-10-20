"""Обработчик самопроверки.

Бот периодически подсовывает диспетчеру фейковое сообщение с командой
/__selfcheck. Обработчик молча отмечает в базе, что он жив - и никто в
Telegram ничего не видит. Если команда падает, растёт счётчик ошибок и
сторож сообщает владельцу.
"""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from ..selfcheck import SELFCHECK_COMMAND, mark_selfcheck_ok

router = Router()


@router.message(Command(SELFCHECK_COMMAND.lstrip("/")))
async def on_selfcheck(message: Message) -> None:
    """Молча отмечаем, что обработчики живы."""
    await mark_selfcheck_ok()

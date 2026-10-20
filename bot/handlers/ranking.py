"""Хендлеры рейтинга."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from ..keyboards import top_menu
from ..services import build_top_text
from ..utils import safe_edit

router = Router()


@router.message(Command("top"))
async def cmd_top(message: Message) -> None:
    text, scope = await build_top_text("all", message.from_user.id)
    await message.answer(text, reply_markup=top_menu(scope))


@router.callback_query(F.data.startswith("top:"))
async def on_top_scope(callback: CallbackQuery) -> None:
    scope = callback.data.split(":", 1)[1]
    text, scope = await build_top_text(scope, callback.from_user.id)
    await safe_edit(callback.message, text, top_menu(scope))
    await callback.answer()

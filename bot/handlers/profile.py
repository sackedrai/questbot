"""Хендлер профиля."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from ..keyboards import main_menu
from ..services import build_profile_text

router = Router()


@router.message(Command("profile"))
async def cmd_profile(message: Message) -> None:
    text = await build_profile_text(message.from_user.id)
    await message.answer(text, reply_markup=main_menu())

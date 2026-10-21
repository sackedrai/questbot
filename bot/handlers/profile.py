"""Хендлер профиля."""

from __future__ import annotations

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import Message

from ..db import db
from ..keyboards import main_menu
from ..services import build_profile_text
from ..utils import open_screen

router = Router()


@router.message(Command("profile"))
async def cmd_profile(message: Message, bot: Bot) -> None:
    text = await build_profile_text(message.from_user.id)
    await open_screen(bot, message, db, text, reply_markup=main_menu())

"""Хендлеры выдачи квестов."""

from __future__ import annotations

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from ..db import db
from ..keyboards import main_menu
from ..services import start_quest
from ..states import Game
from ..utils import open_screen

router = Router()


async def _give_quest(
    message: Message, state: FSMContext, bot: Bot, risky: bool
) -> None:
    result = await start_quest(message.from_user.id, risky=risky)
    if result.blocked:
        await message.answer(result.text, reply_markup=main_menu())
        return

    if result.needs_input:
        await state.set_state(Game.answer)
        await state.update_data(quest_id=result.quest_id)
    else:
        await state.clear()

    # чистим прошлые сообщения, чтобы в чате остался только квест
    await open_screen(bot, message, db, result.text, reply_markup=result.markup)


@router.message(Command("quest"))
async def cmd_quest(message: Message, state: FSMContext, bot: Bot) -> None:
    await _give_quest(message, state, bot, risky=False)


@router.message(Command("risk"))
async def cmd_risk(message: Message, state: FSMContext, bot: Bot) -> None:
    await _give_quest(message, state, bot, risky=True)

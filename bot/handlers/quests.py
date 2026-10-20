"""Хендлеры выдачи квестов."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from ..services import start_quest
from ..states import Game

router = Router()


async def _give_quest(message: Message, state: FSMContext, risky: bool) -> None:
    result = await start_quest(message.from_user.id, risky=risky)
    if result.blocked:
        await message.answer(result.text)
        return

    if result.needs_input:
        await state.set_state(Game.answer)
        await state.update_data(quest_id=result.quest_id)
    else:
        await state.clear()

    await message.answer(result.text, reply_markup=result.markup)


@router.message(Command("quest"))
async def cmd_quest(message: Message, state: FSMContext) -> None:
    await _give_quest(message, state, risky=False)


@router.message(Command("risk"))
async def cmd_risk(message: Message, state: FSMContext) -> None:
    await _give_quest(message, state, risky=True)

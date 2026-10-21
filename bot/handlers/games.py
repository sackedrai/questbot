"""Игровые хендлеры: кнопки внутри квестов и текстовые ответы."""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ..db import db
from ..games import Quest, get_game
from ..keyboards import after_quest_menu, main_menu
from ..services import complete_quest
from ..states import Game
from .. import style
from ..utils import safe_edit
router = Router()


@router.callback_query(F.data.startswith("g:"))
async def on_game_callback(
    callback: CallbackQuery, state: FSMContext, bot: Bot
) -> None:
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer()
        return

    try:
        quest_id = int(parts[1])
    except ValueError:
        await callback.answer()
        return
    choice = parts[2]

    row = await db.get_quest(quest_id)
    if row is None:
        await callback.answer("Квест не найден", show_alert=True)
        return
    if row["tg_id"] != callback.from_user.id:
        await callback.answer("Это не твой квест 👀", show_alert=True)
        return
    if row["status"] != "active":
        await callback.answer("Квест уже завершён", show_alert=True)
        return

    quest = Quest.from_row(row)
    game = get_game(quest.game_type)
    render = await game.on_choice(quest, choice)
    await db.update_quest_payload(quest.id, quest.payload)

    if render.outcome is None:
        await safe_edit(callback.message, render.text, render.markup)
        await callback.answer()
        return

    summary, _points = await complete_quest(quest, render)
    await state.clear()

    if quest.pvp_id:
        await _announce_pvp(callback, bot, quest, summary)
        await callback.answer()
        return

    await safe_edit(callback.message, f"{render.text}\n\n{summary}", after_quest_menu())
    await callback.answer()


async def _announce_pvp(callback: CallbackQuery, bot: Bot, quest: Quest, summary: str) -> None:
    """Сообщить о результате матча обоим игрокам."""
    from ..pvp import format_match, opponent_of

    match = await db.get_pvp_match(quest.pvp_id)
    if match is None:
        await safe_edit(callback.message, summary, main_menu())
        return

    if match["status"] != "finished":
        await safe_edit(callback.message, summary, main_menu())
        return

    final = await format_match(match, quest.tg_id)
    await safe_edit(callback.message, final, main_menu())

    opponent = await opponent_of(match, quest.tg_id)
    if opponent:
        try:
            await bot.send_message(opponent, await format_match(match, opponent))
        except Exception:  # noqa: BLE001
            pass


@router.callback_query(F.data.startswith("skip:"))
async def on_skip(callback: CallbackQuery, state: FSMContext) -> None:
    """Отказ от квеста: без штрафа, слот освобождается."""
    try:
        quest_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer()
        return

    row = await db.get_quest(quest_id)
    if row is None:
        await callback.answer("Квест не найден", show_alert=True)
        return
    if row["tg_id"] != callback.from_user.id:
        await callback.answer("Это не твой квест 👀", show_alert=True)
        return
    if row["status"] != "active":
        await callback.answer("Квест уже завершён", show_alert=True)
        return

    await db.finish_quest(quest_id, 0, "skipped")
    await state.clear()

    pvp_id = row["pvp_id"] if "pvp_id" in row.keys() else 0
    if pvp_id:
        # в матче отказ считается нулевым счётом
        await db.finish_pvp(pvp_id, callback.from_user.id, 0)

    await safe_edit(
        callback.message,
        "\n".join(
            [
                style.header("⏭", "КВЕСТ ПРОПУЩЕН"),
                style.note("Ничего страшного — сегодня он оказался не твоим."),
                style.note("Можно взять новый квест — кнопка ниже."),
            ]
        ),
        main_menu(),
    )
    await callback.answer()


@router.message(Game.answer, F.text, ~F.text.startswith("/"))
async def on_game_text(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    quest_id = data.get("quest_id")

    row = await db.get_quest(quest_id) if quest_id else None
    if row is None:
        row = await db.get_active_quest(message.from_user.id)
    if row is None or row["status"] != "active":
        await state.clear()
        await message.answer(
            "Активного квеста нет. Нажми «Квест дня».",
            reply_markup=main_menu(),
        )
        return

    quest = Quest.from_row(row)
    game = get_game(quest.game_type)
    render = await game.on_text(quest, message.text)
    await db.update_quest_payload(quest.id, quest.payload)

    if render.outcome is None:
        await message.answer(render.text, reply_markup=render.markup)
        return

    summary, _points = await complete_quest(quest, render)
    await state.clear()
    await message.answer(
        f"{render.text}\n\n{summary}",
        reply_markup=after_quest_menu(),
    )

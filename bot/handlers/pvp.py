"""Хендлеры PvP: вызов, принятие, выдача одинакового квеста обоим."""

from __future__ import annotations

import json

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..db import db
from ..pvp import accept_challenge, create_challenge, player_name
from ..services import start_quest
from ..utils import auto_clean, open_screen, safe_edit
from .. import style

router = Router()


async def _invite_link(bot: Bot, code: str) -> str:
    me = await bot.me()
    return f"https://t.me/{me.username}?start=pvp_{code}"


async def create_flow(message: Message, bot: Bot, edit: bool = False) -> None:
    """Создать вызов и отдать ссылку сопернику.

    ``edit`` - править текущее сообщение на месте (вызов из меню). Иначе
    отправляем новый экран, предварительно убрав прошлые.
    """
    code = await create_challenge(message.from_user.id)
    link = await _invite_link(bot, code)
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 В меню", callback_data="menu:home")
    builder.adjust(1)
    text = "\n".join(
        [
            style.header("⚔️", "ВЫЗОВ НА БОЙ"),
            "Отправь другу ссылку — он придёт по ней,\n"
            "и вы оба получите <b>одинаковый квест</b>.",
            "",
            f"<code>{link}</code>",
            "",
            style.note(f"Код вызова: {code}"),
            style.note("Кто наберёт больше очков — победил."),
        ]
    )
    if edit:
        await safe_edit(message, text, builder.as_markup())
    else:
        await open_screen(bot, message, db, text, reply_markup=builder.as_markup())


async def accept_flow(message: Message, bot: Bot, code: str) -> None:
    """Принять вызов и выдать одинаковый квест обоим игрокам."""
    status, match = await accept_challenge(code, message.from_user.id)

    if status == "not_found":
        await message.answer(
            "\n".join(
                [
                    style.header("❓", "ВЫЗОВ НЕ НАЙДЕН"),
                    style.note("Проверь код или попроси друга прислать ссылку целиком."),
                ]
            )
        )
        return
    if status == "self":
        await message.answer(style.note("Нельзя вызвать самого себя 😄"))
        return
    if status == "taken":
        await message.answer(style.note("Этот вызов уже приняли."))
        return
    if status == "closed":
        await message.answer(style.note("Этот матч уже закончился."))
        return

    payload = json.loads(match["payload"])
    for player_id in (match["player1"], match["player2"]):
        result = await start_quest(
            player_id,
            pvp_id=match["id"],
            game_type=match["game_type"],
            difficulty=match["difficulty"],
            payload=payload,
        )
        if result.blocked:
            continue
        header = (
            "⚔️ <b>МАТЧ PvP</b>\n"
            "<i>Одинаковый квест у обоих. Кто наберёт больше очков — победил.</i>\n\n"
        )
        try:
            # в чате остаётся только квест матча
            await auto_clean(bot, player_id, db)
            await bot.send_message(
                player_id, header + result.text, reply_markup=result.markup
            )
        except Exception:  # noqa: BLE001
            continue

    challenger = await player_name(match["player1"])
    await open_screen(
        bot,
        message,
        db,
        "\n".join(
            [
                style.header("⚔️", "МАТЧ НАЧАЛСЯ"),
                f"Соперник: <b>{challenger}</b>",
                style.note("Квест у обоих одинаковый. Удачи!"),
            ]
        ),
    )


@router.message(Command("pvp"))
async def cmd_pvp(message: Message, bot: Bot) -> None:
    """/pvp — вызвать соперника. /pvp КОД — принять вызов."""
    parts = (message.text or "").split()
    code = parts[1].strip().upper() if len(parts) > 1 else ""
    if code:
        await accept_flow(message, bot, code)
    else:
        await create_flow(message, bot)

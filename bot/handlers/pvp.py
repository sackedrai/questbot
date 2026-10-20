"""Хендлеры PvP: вызов, принятие, выдача одинакового квеста обоим."""

from __future__ import annotations

import json

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import Message

from ..db import db
from ..pvp import accept_challenge, create_challenge, format_match, player_name
from ..services import start_quest
from .. import style

router = Router()


async def _invite_link(bot: Bot, code: str) -> str:
    me = await bot.me()
    return f"https://t.me/{me.username}?start=pvp_{code}"


async def create_flow(message: Message, bot: Bot) -> None:
    """Создать вызов и отдать ссылку сопернику."""
    code = await create_challenge(message.from_user.id)
    link = await _invite_link(bot, code)
    await message.answer(
        "\n".join(
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
    )


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
            await bot.send_message(
                player_id, header + result.text, reply_markup=result.markup
            )
        except Exception:  # noqa: BLE001
            continue

    challenger = await player_name(match["player1"])
    await message.answer(
        "\n".join(
            [
                style.header("⚔️", "МАТЧ НАЧАЛСЯ"),
                f"Соперник: <b>{challenger}</b>",
                style.note("Квест у обоих одинаковый. Удачи!"),
            ]
        )
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

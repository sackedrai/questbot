"""Настройки игрока: часовой пояс, уведомления, общая информация."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .. import adaptive, style
from ..db import db
from ..keyboards import main_menu
from ..states import Onboarding
from ..utils import safe_edit

router = Router()


async def _settings_markup(tg_id: int) -> tuple[str, InlineKeyboardBuilder]:
    user = await db.get_user(tg_id)
    tz = int(user["tz_offset"]) if user and user["tz_offset"] is not None else 3
    notify = bool(user["notify"]) if user else True
    level = await adaptive.current_level(tg_id)

    text = "\n".join(
        [
            style.header("⚙️", "НАСТРОЙКИ"),
            style.stats(
                [
                    ("", "Часовой пояс", f"UTC+{tz}"),
                    ("", "Уведомления", "включены" if notify else "выключены"),
                    ("", "Сложность", adaptive.TITLES.get(level, level)),
                ]
            ),
            style.note("Сложность подбирается автоматически."),
        ]
    )

    builder = InlineKeyboardBuilder()
    builder.button(text=f"🕐 Часовой пояс: UTC+{tz}", callback_data="set:tz")
    builder.button(
        text=f"🔔 Уведомления: {'вкл' if notify else 'выкл'}",
        callback_data="set:notify",
    )
    builder.button(text="🎚 Как работает сложность", callback_data="set:difficulty")
    builder.adjust(1)
    return text, builder


@router.message(Command("settings"))
async def cmd_settings(message: Message) -> None:
    text, builder = await _settings_markup(message.from_user.id)
    await message.answer(text, reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("set:"))
async def on_set(callback: CallbackQuery, state: FSMContext) -> None:
    action = callback.data.split(":", 1)[1]
    tg_id = callback.from_user.id

    if action == "notify":
        enabled = await db.notify_enabled(tg_id)
        await db.set_notify(tg_id, not enabled)
        text, builder = await _settings_markup(tg_id)
        await safe_edit(
            callback.message,
            text,
            builder.as_markup(),
        )
        await callback.answer(
            "Уведомления включены" if not enabled else "Уведомления выключены"
        )
        return

    if action == "difficulty":
        level = await adaptive.current_level(tg_id)
        await safe_edit(
            callback.message,
            "\n".join(
                [
                    style.header("🎚", "СЛОЖНОСТЬ АВТОМАТИЧЕСКАЯ", adaptive.describe(level)),
                    style.note("Бот смотрит на твои последние квесты."),
                    style.note("Хорошо играешь - сложнее, тяжело - проще."),
                    style.note("Иногда уровень меняется случайно, чтобы было разнообразие."),
                ]
            ),
            main_menu(),
        )
        await callback.answer()
        return

    if action == "tz":
        await state.set_state(Onboarding.tz)
        await safe_edit(
            callback.message,
            "\n".join(
                [
                    style.header("🕐", "ЧАСОВОЙ ПОЯС"),
                    style.note("Напиши смещение в часах от UTC. Например: 3 или -5."),
                ]
            ),
        )
        await callback.answer()
        return

    await callback.answer()

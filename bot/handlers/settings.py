"""Настройки игрока: часовой пояс, уведомления, общая информация."""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .. import adaptive, style
from ..db import db
from ..keyboards import main_menu
from ..states import Onboarding
from ..utils import open_screen, safe_edit

router = Router()


async def _settings_markup(tg_id: int) -> tuple[str, InlineKeyboardBuilder]:
    user = await db.get_user(tg_id)
    tz = int(user["tz_offset"]) if user and user["tz_offset"] is not None else 3
    notify = bool(user["notify"]) if user else True
    level = await adaptive.current_level(tg_id)
    locked = bool(user and user["adaptive_locked"])
    locked_diff = user["locked_difficulty"] if user and user["adaptive_locked"] else None

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
            style.note(
                f"Сложность зафиксирована: {adaptive.TITLES.get(locked_diff, locked_diff)}"
                if locked
                else "Сложность подбирается автоматически."
            ),
        ]
    )

    builder = InlineKeyboardBuilder()
    builder.button(text=f"🕐 Часовой пояс: UTC+{tz}", callback_data="set:tz")
    builder.button(
        text=f"🔔 Уведомления: {'вкл' if notify else 'выкл'}",
        callback_data="set:notify",
    )
    builder.button(text="🎚 Как работает сложность", callback_data="set:difficulty")
    if locked:
        builder.button(
            text="✅ Вернуть адаптивную сложность",
            callback_data="set:unlock_difficulty",
        )
    else:
        builder.button(text="🔄 Сбросить сложность", callback_data="set:reset_difficulty")
    builder.button(text="🔙 В меню", callback_data="menu:home")
    builder.adjust(1)
    return text, builder


@router.message(Command("settings"))
async def cmd_settings(message: Message, bot: Bot) -> None:
    text, builder = await _settings_markup(message.from_user.id)
    await open_screen(bot, message, db, text, reply_markup=builder.as_markup())


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

    if action == "reset_difficulty":
        await db.lock_difficulty(tg_id, "easy")
        text, builder = await _settings_markup(tg_id)
        await safe_edit(
            callback.message,
            "\n".join(
                [
                    style.header("🔄", "СЛОЖНОСТЬ СБРОШЕНА"),
                    style.note("Снова начнём с лёгкого уровня."),
                    style.note("Адаптивный подбор выключен — вернёшь его кнопкой ниже."),
                ]
            ),
            builder.as_markup(),
        )
        await callback.answer("Сложность сброшена на лёгкую")
        return

    if action == "unlock_difficulty":
        await db.unlock_difficulty(tg_id)
        text, builder = await _settings_markup(tg_id)
        await safe_edit(
            callback.message,
            "\n".join(
                [
                    style.header("✅", "АДАПТИВНАЯ СЛОЖНОСТЬ ВКЛЮЧЕНА"),
                    style.note("Бот снова подбирает уровень сам по твоим результатам."),
                ]
            ),
            builder.as_markup(),
        )
        await callback.answer("Адаптивная сложность возвращена")
        return

    if action == "tz":
        # запоминаем, где игрок был: смена пояса не должна выбивать
        # его из активного текстового квеста
        await state.update_data(tz_prev_state=await state.get_state())
        await state.set_state(Onboarding.tz)
        builder = InlineKeyboardBuilder()
        builder.button(text="🔙 В меню", callback_data="menu:home")
        builder.adjust(1)
        await safe_edit(
            callback.message,
            "\n".join(
                [
                    style.header("🕐", "ЧАСОВОЙ ПОЯС"),
                    style.note("Напиши смещение в часах от UTC. Например: 3 или -5."),
                ]
            ),
            builder.as_markup(),
        )
        await callback.answer()
        return

    await callback.answer()

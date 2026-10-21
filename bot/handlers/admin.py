"""Хендлеры админ-раздела.

Доступны только владельцу (ADMIN_CHAT_ID). Всё, что меняет данные, делает
сам бот - он держит рабочую базу.
"""

from __future__ import annotations


from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .. import admin as admin_mod
from .. import style
from ..achievements import ACHIEVEMENTS
from ..db import db
from ..keyboards import admin_menu, main_menu
from ..states import AdminPanel

router = Router()


def _denied() -> str:
    # нейтрально: не хотим подсказывать, что админка существует
    return style.note("Неизвестная команда.")


@router.message(Command("admin"))
async def cmd_admin(message: Message, bot: Bot) -> None:
    """Меню админки."""
    if not admin_mod.is_admin(message.from_user.id):
        await message.answer(_denied())
        return

    await message.answer(
        await _admin_home_text(message.from_user.id), reply_markup=admin_menu()
    )


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    """Короткая сводка по игрокам."""
    if not admin_mod.is_admin(message.from_user.id):
        await message.answer(_denied())
        return
    await message.answer(
        await admin_mod.build_stats_text(), reply_markup=admin_menu()
    )


@router.message(Command("players"))
async def cmd_players(message: Message) -> None:
    """Список игроков."""
    if not admin_mod.is_admin(message.from_user.id):
        await message.answer(_denied())
        return
    await message.answer(
        await admin_mod.build_players_text(), reply_markup=admin_menu()
    )


@router.callback_query(F.data.startswith("adm:"))
async def on_admin(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    """Обработка кнопок админки."""
    if not admin_mod.is_admin(callback.from_user.id):
        await callback.answer("Неизвестная команда.", show_alert=True)
        return

    action = callback.data.split(":", 1)[1]
    await callback.answer()

    if action == "stats":
        await _edit(callback, await admin_mod.build_stats_text(), admin_menu())
    elif action == "players":
        await _edit(callback, await admin_mod.build_players_text(), admin_menu())
    elif action == "fix":
        await _edit(callback, await _players_picker(), await _players_markup())
    elif action.startswith("user:"):
        tg_id = int(action.split(":", 1)[1])
        await _edit(callback, await admin_mod.build_player_card(tg_id), _player_actions(tg_id))
    elif action.startswith("reset:"):
        tg_id = int(action.split(":", 1)[1])
        await _edit(callback, await admin_mod.reset_player(tg_id), _player_actions(tg_id))
    elif action.startswith("plus:"):
        tg_id = int(action.split(":", 1)[1])
        await _edit(callback, await admin_mod.change_points(tg_id, 50), _player_actions(tg_id))
    elif action.startswith("minus:"):
        tg_id = int(action.split(":", 1)[1])
        await _edit(callback, await admin_mod.change_points(tg_id, -50), _player_actions(tg_id))
    elif action.startswith("grant:"):
        tg_id = int(action.split(":", 1)[1])
        await _edit(callback, await _achievements_picker(tg_id), _achievements_markup(tg_id))
    elif action.startswith("give:"):
        _, tg_id, code = action.split(":", 2)
        await _edit(
            callback,
            await admin_mod.grant_achievement(int(tg_id), code),
            _player_actions(int(tg_id)),
        )
    elif action == "export":
        data = await admin_mod.players_csv_bytes()
        await bot.send_document(
            callback.from_user.id,
            BufferedInputFile(data, filename="players.csv"),
            caption="Выгрузка игроков",
        )
        # отдельное сообщение с кнопками: документ живёт своей жизнью
        await callback.message.answer(
            style.note("Выгрузка отправлена выше."),
            reply_markup=admin_menu(),
        )
    elif action == "vacuum":
        await _edit(callback, await admin_mod.vacuum(), admin_menu())
    elif action == "broadcast":
        await state.set_state(AdminPanel.broadcast)
        await _edit(
            callback,
            "\n".join(
                [
                    style.header("📣", "ОБЪЯВЛЕНИЕ", "напиши текст - разошлём всем"),
                    style.note("Можно отменить кнопкой ниже или командой /cancel"),
                ]
            ),
            _cancel_markup(),
        )
    elif action == "back":
        await _edit(
            callback,
            await _admin_home_text(callback.from_user.id),
            admin_menu(),
        )
    elif action == "cancel":
        await state.clear()
        await _edit(callback, "Отменено.", admin_menu())
    elif action == "menu":
        await _edit(callback, "Меню админки закрыто.", main_menu())


@router.message(AdminPanel.broadcast, F.text)
async def on_broadcast(message: Message, state: FSMContext, bot: Bot) -> None:
    """Рассылает набранный текст всем игрокам."""
    if not admin_mod.is_admin(message.from_user.id):
        await state.clear()
        await message.answer(_denied())
        return
    text = (message.text or "").strip()
    if not text:
        await state.clear()
        await message.answer("Пустое объявление - отменено.", reply_markup=main_menu())
        return
    await state.clear()
    sent, total = await admin_mod.broadcast(bot, text)
    await message.answer(
        "\n".join(
            [
                style.header("📣", "ОБЪЯВЛЕНИЕ ОТПРАВЛЕНО", f"{sent} из {total}"),
                style.footer(),
            ]
        ),
        reply_markup=main_menu(),
    )


@router.message(F.text == "/cancel")
async def on_cancel(message: Message) -> None:
    if not admin_mod.is_admin(message.from_user.id):
        return
    await message.answer("Отменено.", reply_markup=main_menu())


def _cancel_markup() -> InlineKeyboardMarkup:
    """Кнопка отмены (объявление, ввод текста)."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Отмена", callback_data="adm:cancel")
    builder.adjust(1)
    return builder.as_markup()


async def _admin_home_text(viewer_id: int | None = None) -> str:
    """Текст главного экрана админки."""
    return "\n".join(
        [
            style.header("🛠", "АДМИНКА", "всё управление ботом здесь"),
            await admin_mod.build_admins_text(viewer_id),
            style.note("Выбери раздел:"),
            style.footer(),
        ]
    )


async def _edit(
    callback: CallbackQuery,
    text: str,
    markup: InlineKeyboardMarkup,
) -> None:
    """Перерисовать сообщение админки.

    ``markup`` обязателен: экран без кнопок - это тупик, из которого
    некуда выйти. Лучше TypeError при разработке, чем жалоба в игре.
    """
    try:
        await callback.message.edit_text(text, reply_markup=markup)
    except Exception:  # noqa: BLE001 - сообщение могло не измениться
        await callback.message.answer(text, reply_markup=markup)


async def _players_picker() -> str:
    """Список игроков для починки."""
    users = await db.all_users()
    if not users:
        return style.note("Игроков пока нет.")
    return "\n".join(
        [
            style.header("🛠", "ПОЧИНИТЬ ИГРОКА", "выбери игрока"),
            style.note(
                "· ".join(
                    f"{user['nickname'] or 'Без имени'} ({user['tg_id']})"
                    for user in users[:20]
                )
            ),
        ]
    )


async def _players_markup() -> InlineKeyboardMarkup:
    """Клавиатура выбора игрока."""
    builder = InlineKeyboardBuilder()
    for user in await db.all_users():
        name = user["nickname"] or str(user["tg_id"])
        builder.button(
            text=f"{name[:18]} · {user['points']} очк",
            callback_data=f"adm:user:{user['tg_id']}",
        )
    builder.button(text="🔙 В админку", callback_data="adm:back")
    builder.adjust(1)
    return builder.as_markup()


def _player_actions(tg_id: int) -> InlineKeyboardMarkup:
    """Кнопки действий над игроком."""
    builder = InlineKeyboardBuilder()
    builder.button(text="♻️ Сбросить серию", callback_data=f"adm:reset:{tg_id}")
    builder.button(text="➕ 50 очков", callback_data=f"adm:plus:{tg_id}")
    builder.button(text="➖ 50 очков", callback_data=f"adm:minus:{tg_id}")
    builder.button(text="🏅 Выдать достижение", callback_data=f"adm:grant:{tg_id}")
    builder.button(text="🔙 В админку", callback_data="adm:back")
    builder.adjust(2, 2, 1)
    return builder.as_markup()


async def _achievements_picker(tg_id: int) -> str:
    """Список достижений для выдачи."""
    return "\n".join(
        [
            style.header("🏅", "ВЫДАТЬ ДОСТИЖЕНИЕ", f"игрок {tg_id}"),
            style.note("· ".join(spec["title"] for spec in ACHIEVEMENTS.values())),
        ]
    )


def _achievements_markup(tg_id: int) -> InlineKeyboardMarkup:
    """Клавиатура выбора достижения."""
    builder = InlineKeyboardBuilder()
    for code, spec in ACHIEVEMENTS.items():
        builder.button(
            text=spec["title"][:24], callback_data=f"adm:give:{tg_id}:{code}"
        )
    builder.button(text="🔙 В меню", callback_data="adm:menu")
    builder.adjust(1)
    return builder.as_markup()

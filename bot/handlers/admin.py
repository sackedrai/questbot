"""Хендлеры админ-раздела.

Доступны только владельцу (ADMIN_CHAT_ID). Всё, что меняет данные, делает
сам бот - он держит рабочую базу.
"""

from __future__ import annotations

import html
import json

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


@router.message(Command("moderate"))
async def cmd_moderate(message: Message) -> None:
    """Очередь вопросов игроков на модерацию."""
    if not admin_mod.is_admin(message.from_user.id):
        await message.answer(_denied())
        return
    text, markup = await _questions_screen()
    await message.answer(text, reply_markup=markup)


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
    elif action == "questions":
        text, markup = await _questions_screen()
        await _edit(callback, text, markup)
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


@router.callback_query(F.data.startswith("qmod:"))
async def on_question_moderation(callback: CallbackQuery, bot: Bot) -> None:
    """Карточка вопроса и решения по нему."""
    if not admin_mod.is_admin(callback.from_user.id):
        await callback.answer("Неизвестная команда.", show_alert=True)
        return

    action = callback.data.split(":", 1)[1]
    if action == "back":
        text, markup = await _questions_screen()
        await _edit(callback, text, markup)
        await callback.answer()
        return

    try:
        kind, raw_id = action.split(":", 1)
        question_id = int(raw_id)
    except (ValueError, TypeError):
        await callback.answer("Некорректный вопрос.", show_alert=True)
        return

    if kind == "view":
        text, markup = await _question_card(question_id)
        await _edit(callback, text, markup)
        await callback.answer()
        return

    if kind not in ("approve", "reject"):
        await callback.answer("Неизвестное действие.", show_alert=True)
        return

    row = await db.get_user_question(question_id)
    if row is None or row["status"] != "pending":
        await callback.answer(
            "Вопрос уже обработан или не найден.", show_alert=True
        )
        return

    approved = kind == "approve"
    ok = (
        await db.approve_question(question_id, callback.from_user.id)
        if approved
        else await db.reject_question(question_id, callback.from_user.id)
    )
    if not ok:
        await callback.answer(
            "Не удалось: возможно, вопрос уже обработан.", show_alert=True
        )
        return

    await _notify_question_author(bot, row, approved)
    text, markup = await _questions_screen()
    await _edit(callback, text, markup)
    await callback.answer("Вопрос опубликован" if approved else "Вопрос отклонён")


async def _notify_question_author(bot: Bot, row, approved: bool) -> None:
    """Сообщить автору решение по его вопросу."""
    try:
        if approved:
            text = "\n".join(
                [
                    style.header("✅", "ВОПРОС ОПУБЛИКОВАН", "спасибо!"),
                    style.note(
                        "Твой вопрос добавлен в банк и может выпасть "
                        "в ежедневном квесте."
                    ),
                ]
            )
        else:
            text = "\n".join(
                [
                    style.header("📝", "ВОПРОС НЕ ПОДОШЁЛ"),
                    style.note(
                        "Спасибо, что предложил вопрос. Админ решил, что "
                        "он пока не подходит для игры."
                    ),
                ]
            )
        await bot.send_message(
            int(row["tg_id"]), text, reply_markup=main_menu()
        )
    except Exception:  # noqa: BLE001 - игрок мог заблокировать бота
        pass


@router.message(AdminPanel.broadcast, F.text, ~Command("cancel"))
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


@router.message(AdminPanel.broadcast, Command("cancel"))
async def on_cancel(message: Message, state: FSMContext) -> None:
    """Отмена объявления. Не перехватывает /cancel других сценариев."""
    if not admin_mod.is_admin(message.from_user.id):
        await state.clear()
        return
    await state.clear()
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


# ----------------------------------------------------------------------
# модерация вопросов игроков
# ----------------------------------------------------------------------
def _button_label(text: object, limit: int = 24) -> str:
    """Обрезать подпись кнопки по символам и байтам Telegram."""
    clean = " ".join(str(text).split()) or "без текста"
    result = ""
    for char in clean:
        candidate = result + char
        if len(candidate) > limit or len(candidate.encode("utf-8")) > 56:
            break
        result = candidate
    if result != clean:
        result = result.rstrip() + "…"
    return result


def _questions_markup(rows) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for row in rows[:10]:
        builder.button(
            text=f"#{row['id']} · {_button_label(row['question'])}",
            callback_data=f"qmod:view:{row['id']}",
        )
    builder.button(text="🔙 В админку", callback_data="adm:back")
    builder.adjust(1)
    return builder.as_markup()


async def _questions_screen() -> tuple[str, InlineKeyboardMarkup]:
    """Текст и кнопки очереди модерации."""
    rows = await db.get_pending_questions(limit=50)
    if not rows:
        text = "\n".join(
            [
                style.header("📝", "ВОПРОСЫ ИГРОКОВ", "очередь пуста"),
                style.note("Новых вопросов на проверке нет."),
            ]
        )
    else:
        lines = [
            style.header(
                "📝",
                "ВОПРОСЫ ИГРОКОВ",
                f"{len(rows)} на проверке",
            ),
            style.note("Выбери вопрос, чтобы увидеть варианты и решить."),
        ]
        if len(rows) > 10:
            lines.append(
                style.note(f"Показаны первые 10 из {len(rows)}.")
            )
        text = "\n".join(lines)
    return text, _questions_markup(rows)


async def _question_card(question_id: int) -> tuple[str, InlineKeyboardMarkup]:
    """Полная карточка вопроса для решения админа."""
    row = await db.get_user_question(question_id)
    if row is None:
        text = "\n".join(
            [
                style.header("📝", "ВОПРОС", f"#{question_id}"),
                style.note("Вопрос не найден."),
            ]
        )
        return text, _questions_markup([])

    if row["status"] != "pending":
        status = {
            "approved": "опубликован",
            "rejected": "отклонён",
        }.get(row["status"], row["status"])
        text = "\n".join(
            [
                style.header("📝", "ВОПРОС", f"#{question_id}"),
                style.note(f"Статус: {status}. Решение уже принято."),
            ]
        )
        return text, _questions_markup([])

    author = await db.get_user(int(row["tg_id"]))
    author_name = (
        (author["nickname"] if author else "") or str(row["tg_id"])
    )
    try:
        wrong = json.loads(row["options"] or "[]")
    except (TypeError, ValueError):
        wrong = []
    if not isinstance(wrong, list):
        wrong = []

    question = html.escape(str(row["question"]))
    answer = html.escape(str(row["answer"]))
    category = html.escape(str(row["category"] or "Свои вопросы"))
    levels = {"easy": "лёгкая", "medium": "средняя", "hard": "сложная"}
    level = levels.get(row["difficulty"], row["difficulty"])

    lines = [
        style.header("📝", "ВОПРОС НА МОДЕРАЦИИ", f"#{question_id} · от {author_name}"),
        style.question(question),
        style.section("ВАРИАНТЫ"),
        f"✅ {answer}",
    ]
    for item in wrong:
        lines.append(f"⚪ {html.escape(str(item))}")
    lines.extend(
        [
            style.stats(
                [
                    ("", "Категория", category),
                    ("", "Сложность", level),
                ]
            ),
            style.note(
                "После публикации вопрос сможет выпасть любому игроку. "
                "Проверь, что верный ответ действительно один."
            ),
        ]
    )

    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Опубликовать", callback_data=f"qmod:approve:{question_id}"
    )
    builder.button(
        text="❌ Отклонить", callback_data=f"qmod:reject:{question_id}"
    )
    builder.button(text="🔙 К очереди", callback_data="qmod:back")
    builder.adjust(2, 1)
    return "\n".join(lines), builder.as_markup()

"""Свой вопрос: игрок предлагает задание, админ проверяет его.

Вопросы не попадают в игру сразу: сначала они лежат в статусе ``pending``.
После одобрения вопрос может выпасть любому игроку как отдельная мини-игра
``userquiz``.
"""

from __future__ import annotations

import html
import re

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .. import style
from ..db import db
from ..keyboards import main_menu
from ..states import AskQuestion
from ..utils import open_screen, safe_edit

router = Router()

MAX_PENDING = 3
MAX_QUESTION = 200
MAX_CATEGORY = 24
MAX_OPTION = 28
# Telegram ограничивает подпись кнопки 64 байтами. Кириллица занимает
# два байта на символ, поэтому проверяем и длину, и размер в байтах.
MAX_OPTION_BYTES = 56
DEFAULT_CATEGORY = "Свои вопросы"


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _option_ok(text: str) -> bool:
    return (
        1 <= len(text) <= MAX_OPTION
        and len(text.encode("utf-8")) <= MAX_OPTION_BYTES
    )


def _cancel_markup() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Отмена", callback_data="ask:cancel")
    builder.adjust(1)
    return builder.as_markup()


def _category_markup() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⏭ Пропустить", callback_data="ask:skipcat")
    builder.button(text="🔙 Отмена", callback_data="ask:cancel")
    builder.adjust(2)
    return builder.as_markup()


def _difficulty_markup() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🟢 Лёгкий", callback_data="ask:diff:easy")
    builder.button(text="🟡 Средний", callback_data="ask:diff:medium")
    builder.button(text="🔴 Сложный", callback_data="ask:diff:hard")
    builder.button(text="🔙 Отмена", callback_data="ask:cancel")
    builder.adjust(3, 1)
    return builder.as_markup()


def _finish_markup() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📖 Мои вопросы", callback_data="ask:mine")
    builder.button(text="🔙 В меню", callback_data="menu:home")
    builder.adjust(1)
    return builder.as_markup()


def _mine_markup() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📝 Ещё вопрос", callback_data="ask:new")
    builder.button(text="🔙 В меню", callback_data="menu:home")
    builder.adjust(1)
    return builder.as_markup()


async def build_ask_home_text(tg_id: int) -> str:
    """Экран раздела «Свой вопрос»."""
    stats = await db.question_stats(tg_id)
    return "\n".join(
        [
            style.header("📝", "СВОЙ ВОПРОС", "предложи задание для всех"),
            "Придумай вопрос с четырьмя вариантами ответа. Админ проверит "
            "его и добавит в общий банк.",
            style.stats(
                [
                    ("", "Всего отправлено", str(stats["total"])),
                    ("", "На проверке", str(stats["pending"])),
                    ("", "Опубликовано", str(stats["approved"])),
                ]
            ),
            style.note(
                f"Одновременно на проверке может быть не больше {MAX_PENDING} "
                "вопросов."
            ),
            style.note("Вопрос должен быть понятным и иметь один верный ответ."),
            style.note(
                "Не указывай личные данные: после публикации вопрос увидят все."
            ),
        ]
    )


def ask_home_markup() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📝 Придумать вопрос", callback_data="ask:new")
    builder.button(text="📖 Мои вопросы", callback_data="ask:mine")
    builder.button(text="🔙 В меню", callback_data="menu:home")
    builder.adjust(1)
    return builder.as_markup()


def _prompt(title: str, step: str, body: str, hint: str = "") -> str:
    lines = [style.header("📝", title, step), body]
    if hint:
        lines.append(style.note(hint))
    lines.append(style.note("В любой момент можно нажать «Отмена»."))
    return "\n".join(lines)


async def _can_ask(tg_id: int) -> bool:
    pending = await db.count_user_questions(tg_id, "pending")
    return pending < MAX_PENDING


async def _registered(message: Message) -> bool:
    user = await db.get_user(message.from_user.id)
    if user is not None and user["nickname"]:
        return True
    await message.answer("Сначала пройди регистрацию: /start", reply_markup=main_menu())
    return False


@router.message(Command("ask"))
async def cmd_ask(message: Message, bot: Bot) -> None:
    """Открыть раздел со своими вопросами."""
    if not await _registered(message):
        return
    await open_screen(
        bot,
        message,
        db,
        await build_ask_home_text(message.from_user.id),
        ask_home_markup(),
    )


@router.message(Command("myquestions"))
async def cmd_myquestions(message: Message, bot: Bot) -> None:
    """Показать свои вопросы и их статусы."""
    if not await _registered(message):
        return
    text = await _my_questions_text(message.from_user.id)
    await open_screen(bot, message, db, text, _mine_markup())


async def _my_questions_text(tg_id: int) -> str:
    stats = await db.question_stats(tg_id)
    rows = await db.get_user_questions(tg_id, limit=20)
    if not rows:
        return "\n".join(
            [
                style.header("📝", "МОИ ВОПРОСЫ", "пока пусто"),
                style.note(
                    "Ты ещё не предлагал вопросы. Нажми «Ещё вопрос», чтобы "
                    "добавить первый."
                ),
            ]
        )

    lines = [
        style.header(
            "📝",
            "МОИ ВОПРОСЫ",
            f"всего {stats['total']} · в игре {stats['approved']}",
        )
    ]
    marks = {"pending": "⏳", "approved": "✅", "rejected": "❌"}
    for row in rows:
        mark = marks.get(row["status"], "❓")
        question = html.escape(str(row["question"]))
        lines.append(f"{mark} #{row['id']} · {question[:80]}")
    if stats["pending"]:
        lines.append(style.note("⏳ — ждёт проверки администратором."))
    return "\n".join(lines)


@router.callback_query(F.data == "ask:home")
async def on_ask_home(callback: CallbackQuery) -> None:
    await safe_edit(
        callback.message,
        await build_ask_home_text(callback.from_user.id),
        ask_home_markup(),
    )
    await callback.answer()


@router.callback_query(F.data == "ask:new")
async def on_ask_new(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _can_ask(callback.from_user.id):
        await callback.answer(
            f"На проверке уже {MAX_PENDING} вопроса. Дождись решения админа.",
            show_alert=True,
        )
        return
    await state.clear()
    await state.set_state(AskQuestion.waiting_question)
    await safe_edit(
        callback.message,
        _prompt(
            "СВОЙ ВОПРОС",
            "шаг 1 из 5",
            "Напиши текст вопроса одним сообщением.",
            f"От 5 до {MAX_QUESTION} символов.",
        ),
        _cancel_markup(),
    )
    await callback.answer()


@router.callback_query(F.data == "ask:mine")
async def on_ask_mine(callback: CallbackQuery) -> None:
    await safe_edit(
        callback.message,
        await _my_questions_text(callback.from_user.id),
        _mine_markup(),
    )
    await callback.answer()


@router.callback_query(F.data == "ask:cancel")
async def on_ask_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await safe_edit(
        callback.message,
        await build_ask_home_text(callback.from_user.id),
        ask_home_markup(),
    )
    await callback.answer("Отменено")


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext, bot: Bot) -> None:
    current = await state.get_state()
    if not current or not current.startswith(f"{AskQuestion.__name__}:"):
        return
    await state.clear()
    await open_screen(
        bot,
        message,
        db,
        await build_ask_home_text(message.from_user.id),
        ask_home_markup(),
    )


# ------------------------------------------------------------------
# шаг 1: текст вопроса
# ------------------------------------------------------------------
@router.message(AskQuestion.waiting_question, F.text, ~F.text.startswith("/"))
async def on_question_text(
    message: Message, state: FSMContext, bot: Bot
) -> None:
    text = _one_line(message.text)
    if not 5 <= len(text) <= MAX_QUESTION:
        await open_screen(
            bot,
            message,
            db,
            _prompt(
                "СВОЙ ВОПРОС",
                "шаг 1 из 5",
                "Напиши текст вопроса одним сообщением.",
                f"Нужно от 5 до {MAX_QUESTION} символов. Попробуй ещё раз.",
            ),
            _cancel_markup(),
        )
        return

    await state.update_data(question=text)
    await state.set_state(AskQuestion.waiting_answer)
    await open_screen(
        bot,
        message,
        db,
        _prompt(
            "СВОЙ ВОПРОС",
            "шаг 2 из 5",
            "Напиши правильный ответ на свой вопрос.",
            f"Коротко, до {MAX_OPTION} символов — это будет вариант в кнопке.",
        ),
        _cancel_markup(),
    )


# ------------------------------------------------------------------
# шаг 2: правильный ответ
# ------------------------------------------------------------------
@router.message(AskQuestion.waiting_answer, F.text, ~F.text.startswith("/"))
async def on_answer_text(
    message: Message, state: FSMContext, bot: Bot
) -> None:
    text = _one_line(message.text)
    if not _option_ok(text):
        await open_screen(
            bot,
            message,
            db,
            _prompt(
                "СВОЙ ВОПРОС",
                "шаг 2 из 5",
                "Напиши правильный ответ на свой вопрос.",
                f"Ответ должен быть коротким: до {MAX_OPTION} символов.",
            ),
            _cancel_markup(),
        )
        return

    await state.update_data(answer=text)
    await state.set_state(AskQuestion.waiting_options)
    await open_screen(
        bot,
        message,
        db,
        _prompt(
            "СВОЙ ВОПРОС",
            "шаг 3 из 5",
            "Напиши три неверных варианта через запятую.",
            "Например: Сидней, Мельбурн, Перт",
        ),
        _cancel_markup(),
    )


# ------------------------------------------------------------------
# шаг 3: три неверных варианта
# ------------------------------------------------------------------
@router.message(AskQuestion.waiting_options, F.text, ~F.text.startswith("/"))
async def on_options_text(
    message: Message, state: FSMContext, bot: Bot
) -> None:
    data = await state.get_data()
    answer = str(data.get("answer", ""))
    parts = [
        _one_line(part)
        for part in re.split(r"[,;\n]+", message.text)
        if part.strip()
    ]
    error = ""
    if len(parts) != 3:
        error = "Нужно ровно три варианта через запятую."
    elif any(not _option_ok(part) for part in parts):
        error = f"Каждый вариант — до {MAX_OPTION} символов."
    elif len({part.casefold() for part in parts}) != 3:
        error = "Варианты не должны повторяться."
    elif answer.casefold() in {part.casefold() for part in parts}:
        error = "Неверные варианты не должны совпадать с правильным ответом."

    if error:
        await open_screen(
            bot,
            message,
            db,
            _prompt(
                "СВОЙ ВОПРОС",
                "шаг 3 из 5",
                "Напиши три неверных варианта через запятую.",
                error,
            ),
            _cancel_markup(),
        )
        return

    await state.update_data(options=parts)
    await state.set_state(AskQuestion.waiting_category)
    await open_screen(
        bot,
        message,
        db,
        _prompt(
            "СВОЙ ВОПРОС",
            "шаг 4 из 5",
            "Напиши категорию вопроса или пропусти этот шаг.",
            f"Например: История, Наука, Кино, IT. До {MAX_CATEGORY} символов.",
        ),
        _category_markup(),
    )


# ------------------------------------------------------------------
# шаг 4: категория
# ------------------------------------------------------------------
async def _to_difficulty(
    message: Message, state: FSMContext, bot: Bot, category: str
) -> None:
    await state.update_data(category=category)
    await state.set_state(AskQuestion.waiting_difficulty)
    await open_screen(
        bot,
        message,
        db,
        _prompt(
            "СВОЙ ВОПРОС",
            "шаг 5 из 5",
            "Выбери сложность вопроса:",
            "От неё зависит, сколько очков получит игрок за верный ответ.",
        ),
        _difficulty_markup(),
    )


@router.message(AskQuestion.waiting_category, F.text, ~F.text.startswith("/"))
async def on_category_text(
    message: Message, state: FSMContext, bot: Bot
) -> None:
    raw = _one_line(message.text)
    if raw in ("-", "пропустить", "Пропустить"):
        category = DEFAULT_CATEGORY
    elif not 2 <= len(raw) <= MAX_CATEGORY:
        await open_screen(
            bot,
            message,
            db,
            _prompt(
                "СВОЙ ВОПРОС",
                "шаг 4 из 5",
                "Напиши категорию вопроса или пропусти этот шаг.",
                f"Нужно от 2 до {MAX_CATEGORY} символов.",
            ),
            _category_markup(),
        )
        return
    else:
        category = raw
    await _to_difficulty(message, state, bot, category)


@router.callback_query(F.data == "ask:skipcat", AskQuestion.waiting_category)
async def on_category_skip(
    callback: CallbackQuery, state: FSMContext, bot: Bot
) -> None:
    await _to_difficulty(
        callback.message, state, bot, DEFAULT_CATEGORY
    )
    await callback.answer()


# ------------------------------------------------------------------
# шаг 5: сложность и сохранение
# ------------------------------------------------------------------
async def _submit_question(
    message: Message,
    state: FSMContext,
    bot: Bot,
    tg_id: int,
    difficulty: str,
) -> None:
    data = await state.get_data()
    question = str(data.get("question", ""))
    answer = str(data.get("answer", ""))
    options = list(data.get("options") or [])
    category = str(data.get("category", DEFAULT_CATEGORY))
    if not question or not answer or len(options) != 3:
        await state.clear()
        await open_screen(
            bot,
            message,
            db,
            "\n".join(
                [
                    style.header("⚠️", "НЕ ПОЛУЧИЛОСЬ", "данные потерялись"),
                    style.note("Начни заново: /ask"),
                ]
            ),
            main_menu(),
        )
        return

    await db.add_user_question(
        tg_id=tg_id,
        question=question,
        answer=answer,
        options=options,
        category=category,
        difficulty=difficulty,
    )
    await state.clear()
    await open_screen(
        bot,
        message,
        db,
        "\n".join(
            [
                style.header("✅", "ВОПРОС ОТПРАВЛЕН", "спасибо!"),
                style.question(html.escape(question)),
                style.note(
                    "Админ проверит вопрос. Если всё в порядке, он появится "
                    "в ежедневных квестах."
                ),
            ]
        ),
        _finish_markup(),
    )


_DIFFICULTIES = {
    "1": "easy",
    "лёгкий": "easy",
    "легкий": "easy",
    "easy": "easy",
    "2": "medium",
    "средний": "medium",
    "medium": "medium",
    "3": "hard",
    "сложный": "hard",
    "hard": "hard",
}


@router.callback_query(F.data.startswith("ask:diff:"), AskQuestion.waiting_difficulty)
async def on_difficulty_callback(
    callback: CallbackQuery, state: FSMContext, bot: Bot
) -> None:
    difficulty = callback.data.rsplit(":", 1)[1]
    if difficulty not in ("easy", "medium", "hard"):
        await callback.answer("Неизвестная сложность.", show_alert=True)
        return
    await _submit_question(
        callback.message,
        state,
        bot,
        callback.from_user.id,
        difficulty,
    )
    await callback.answer("Отправлено на проверку")


@router.message(AskQuestion.waiting_difficulty, F.text, ~F.text.startswith("/"))
async def on_difficulty_text(
    message: Message, state: FSMContext, bot: Bot
) -> None:
    difficulty = _DIFFICULTIES.get(_one_line(message.text).casefold())
    if difficulty is None:
        await open_screen(
            bot,
            message,
            db,
            _prompt(
                "СВОЙ ВОПРОС",
                "шаг 5 из 5",
                "Выбери сложность вопроса:",
                "Нажми кнопку ниже или напиши: лёгкий, средний, сложный.",
            ),
            _difficulty_markup(),
        )
        return
    await _submit_question(
        message, state, bot, message.from_user.id, difficulty
    )

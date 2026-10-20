"""Общие хендлеры: старт, онбординг, главное меню."""

from __future__ import annotations

import html

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ..config import DIFFICULTY_HINTS, DIFFICULTY_TITLES
from ..db import db
from ..keyboards import difficulty_menu, main_menu, top_menu
from ..services import build_profile_text, build_top_text, start_quest
from ..states import Game, Onboarding
from ..utils import safe_edit

router = Router()

HELP_TEXT = (
    "<b>Как играть</b>\n\n"
    "🎯 Каждый день доступен один квест — это мини-игра на 1–2 минуты.\n\n"
    "<b>Какие бывают игры</b>\n"
    "• 🧠 Викторина — вопрос и четыре варианта\n"
    "• ⚡ Быстрый квест — короткий вопрос, решает скорость\n"
    "• 🕰 Хронология — расставь события по порядку\n"
    "• 🧩 Загадка — ответ одним сообщением\n"
    "• 🔤 Угадай слово — угадывай по буквам\n\n"
    "<b>Очки</b>\n"
    "• Зависит от сложности: 10 / 20 / 30\n"
    "• 🔥 Серия дней множит очки (максимум ×1.5)\n"
    "• ⚡ Быстрый ответ даёт ×1.2 или ×1.5\n"
    "• 💡 Подсказка отнимает 40% очков\n"
    "• ⚡ Рискованный квест: ×2 очка, но −10 при провале\n\n"
    "<b>Команды</b>\n"
    "/quest — квест дня\n"
    "/risk — рискованный квест\n"
    "/top — рейтинг\n"
    "/profile — профиль\n"
    "/difficulty — сменить сложность\n"
    "/help — эта справка"
)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    tg_id = message.from_user.id
    user = await db.get_user(tg_id)
    if user is None:
        await db.create_user(
            tg_id,
            message.from_user.username or "",
            message.from_user.full_name or "",
        )
        user = await db.get_user(tg_id)

    if not user["nickname"]:
        await state.set_state(Onboarding.nickname)
        await message.answer(
            "Привет! 👋\n\n"
            "Как тебя звать в рейтинге? Напиши имя (до 20 символов)."
        )
        return

    await message.answer(
        f"С возвращением, <b>{html.escape(user['nickname'])}</b>!",
        reply_markup=main_menu(),
    )


@router.message(Onboarding.nickname, F.text)
async def on_nickname(message: Message, state: FSMContext) -> None:
    nickname = html.escape(message.text.strip()[:20]) or "Аноним"
    await db.set_nickname(message.from_user.id, nickname)
    await state.clear()
    await message.answer(
        f"Приятно познакомиться, <b>{nickname}</b>!\n\n"
        "Выбери сложность квестов:",
        reply_markup=difficulty_menu(),
    )


@router.callback_query(F.callback_data.startswith("diff:"))
async def on_difficulty(callback: CallbackQuery, state: FSMContext) -> None:
    difficulty = callback.data.split(":", 1)[1]
    if difficulty not in DIFFICULTY_TITLES:
        await callback.answer()
        return
    await db.set_difficulty(callback.from_user.id, difficulty)
    await state.clear()
    await safe_edit(
        callback.message,
        f"Сложность: {DIFFICULTY_TITLES[difficulty]}\n"
        f"<i>{DIFFICULTY_HINTS[difficulty]}</i>\n\n"
        "Сменить можно в любой момент через /difficulty",
        main_menu(),
    )
    await callback.answer()


@router.message(Command("difficulty"))
async def cmd_difficulty(message: Message) -> None:
    await message.answer("Выбери сложность квестов:", reply_markup=difficulty_menu())


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT, reply_markup=main_menu())


@router.callback_query(F.callback_data.startswith("menu:"))
async def on_menu(callback: CallbackQuery, state: FSMContext) -> None:
    action = callback.data.split(":", 1)[1]
    tg_id = callback.from_user.id

    if action == "home":
        await safe_edit(callback.message, "Что делаем?", main_menu())
    elif action == "help":
        await safe_edit(callback.message, HELP_TEXT, main_menu())
    elif action == "profile":
        await safe_edit(callback.message, await build_profile_text(tg_id), main_menu())
    elif action == "top":
        text, scope = await build_top_text("all", tg_id)
        await safe_edit(callback.message, text, top_menu(scope))
    elif action in ("quest", "risk"):
        result = await start_quest(tg_id, risky=(action == "risk"))
        if result.blocked:
            await safe_edit(callback.message, result.text, main_menu())
        else:
            if result.needs_input:
                await state.set_state(Game.answer)
                await state.update_data(quest_id=result.quest_id)
            else:
                await state.clear()
            await safe_edit(callback.message, result.text, result.markup)

    await callback.answer()

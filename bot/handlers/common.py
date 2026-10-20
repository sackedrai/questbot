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
from .. import style
from ..utils import cleanup_chat, safe_edit, wipe_chat

router = Router()

HELP_TEXT = "\n".join(
    [
        style.header("📖", "КАК ИГРАТЬ", "коротко о главном"),
        "",
        "<pre>🎯 Квест дня       одна мини-игра в день\n"
        "⚡ Рискованный     ×2 очка, но −10 за провал\n"
        "🏆 Рейтинг         кто сколько заработал\n"
        "👤 Профиль         очки, серия, уровень</pre>",
        style.section("НАЧИСЛЕНИЕ ОЧКОВ"),
        "<pre>Сложность        10 / 20 / 30 очков\n"
        "Серия дней       ×1.05 в день, максимум ×1.5\n"
        "Скорость         ×1.5 или ×1.2\n"
        "Подсказка        ×0.6\n"
        "Риск             ×2 очка, минус 10 за провал</pre>",
        style.section("КОМАНДЫ"),
        "<pre>/quest        квест дня\n"
        "/risk         рискованный квест\n"
        "/top          рейтинг\n"
        "/profile      профиль\n"
        "/difficulty  сменить сложность\n"
        "/clear        очистить чат полностью\n"
        "/help         эта справка</pre>",
        "",
        style.note("Кнопка «Сдаться» — если квест оказался не по силам. "
                   "Без штрафа, можно взять новый."),
        style.note("/clear — удалит всю переписку в чате, включая твои сообщения."),
        style.footer(),
    ]
)

WELCOME_TEXT = "\n".join(
    [
        style.header("👋", "ПРИВЕТ!", "добро пожаловать в QuestBot"),
        "",
        "Каждый день — один мини-квест на пару минут.\n"
        "Кто набрал больше очков, тот и в рейтинге выше.",
        "",
        "<pre>🧠 Викторина     ⚡ Быстрый квест\n"
        "🕰 Хронология    🧩 Загадка\n"
        "🔤 Угадай слово</pre>",
        "",
        style.note("Придумай имя для рейтинга — до 20 символов."),
        style.note("Напиши его следующим сообщением."),
    ]
)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, bot: Bot) -> None:
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
        await message.answer(WELCOME_TEXT)
        return

    await message.answer(
        "\n".join(
            [
                style.header("👋", "С ВОЗВРАЩЕНИЕМ", f"{user['nickname']}!"),
                style.note("Квест дня уже ждёт тебя."),
            ]
        ),
        reply_markup=main_menu(),
    )


@router.message(Onboarding.nickname, F.text)
async def on_nickname(message: Message, state: FSMContext, bot: Bot) -> None:
    nickname = html.escape(message.text.strip()[:20]) or "Аноним"
    await db.set_nickname(message.from_user.id, nickname)
    await state.clear()
    sent = await message.answer(
        "\n".join(
            [
                style.header("🤝", "ПРИЯТНО ПОЗНАКОМИТЬСЯ!", nickname),
                "",
                "Выбери сложность квестов — её можно поменять в любой момент.",
                "",
                f"{DIFFICULTY_TITLES['easy']}\n"
                f"   {style.note(DIFFICULTY_HINTS['easy'])}",
                "",
                f"{DIFFICULTY_TITLES['medium']}\n"
                f"   {style.note(DIFFICULTY_HINTS['medium'])}",
                "",
                f"{DIFFICULTY_TITLES['hard']}\n"
                f"   {style.note(DIFFICULTY_HINTS['hard'])}",
            ]
        ),
        reply_markup=difficulty_menu(),
    )
    return sent


@router.callback_query(F.data.startswith("diff:"))
async def on_difficulty(callback: CallbackQuery, state: FSMContext) -> None:
    difficulty = callback.data.split(":", 1)[1]
    if difficulty not in DIFFICULTY_TITLES:
        await callback.answer()
        return
    await db.set_difficulty(callback.from_user.id, difficulty)
    await state.clear()
    await safe_edit(
        callback.message,
        "\n".join(
            [
                style.header("⚙️", "НАСТРОЙКА ГОТОВА"),
                "",
                f"Сложность: <b>{DIFFICULTY_TITLES[difficulty]}</b>",
                style.note(DIFFICULTY_HINTS[difficulty]),
                "",
                style.note("Поменять можно в любой момент: /difficulty"),
            ]
        ),
        main_menu(),
    )
    await callback.answer()


@router.message(Command("difficulty"))
async def cmd_difficulty(message: Message) -> None:
    await message.answer("Выбери сложность квестов:", reply_markup=difficulty_menu())


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT, reply_markup=main_menu())


@router.message(Command("clear"))
async def cmd_clear(message: Message, bot: Bot) -> None:
    """Удалить всю переписку в чате - и бота, и пользователя."""
    deleted, total = await wipe_chat(
        bot, message.chat.id, db, up_to_id=message.message_id
    )
    await message.answer(
        "\n".join(
            [
                style.header("🧹", "ЧАТ ОЧИЩЕН"),
                style.note(f"Удалено сообщений: {deleted} из {total}"),
            ]
        )
    )


@router.callback_query(F.data.startswith("menu:"))
async def on_menu(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    action = callback.data.split(":", 1)[1]
    tg_id = callback.from_user.id

    if action == "home":
        await safe_edit(
            callback.message,
            "\n".join(
                [
                    style.header("🗺", "ГЛАВНОЕ МЕНЮ"),
                    style.note("Выбирай, что делаем."),
                ]
            ),
            main_menu(),
        )
    elif action == "help":
        await safe_edit(callback.message, HELP_TEXT, main_menu())
    elif action == "profile":
        await safe_edit(callback.message, await build_profile_text(tg_id), main_menu())
    elif action == "top":
        text, scope = await build_top_text("all", tg_id)
        await safe_edit(callback.message, text, top_menu(scope))
    elif action == "clear":
        # само меню не удаляем - его же будем редактировать
        tracked = await db.chat_messages(callback.message.chat.id, limit=200)
        up_to = max([callback.message.message_id, *tracked], default=0)
        deleted, total = await wipe_chat(
            bot,
            callback.message.chat.id,
            db,
            up_to_id=up_to,
            keep={callback.message.message_id},
        )
        await safe_edit(
            callback.message,
            "\n".join(
                [
                    style.header("🧹", "ЧАТ ОЧИЩЕН"),
                    style.note(f"Удалено сообщений: {deleted} из {total}"),
                ]
            ),
            main_menu(),
        )
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

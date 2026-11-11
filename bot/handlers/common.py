"""Общие хендлеры: старт, онбординг, главное меню."""

from __future__ import annotations

import html

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..db import db
from ..keyboards import main_menu, top_menu
from ..services import (
    build_profile_text,
    build_pvp_history_text,
    build_top_text,
    build_week_text,
    start_quest,
)
from ..daily import availability, STATE_ACTIVE, STATE_COOLDOWN
from ..states import Game, Onboarding
from .. import style
from ..utils import keep_only, open_screen, safe_edit, wipe_chat

router = Router()

# Часовые пояса на выбор: (название, смещение в часах от UTC)
TZ_CHOICES: tuple[tuple[str, int], ...] = (
    ("Калининград", 2),
    ("Москва", 3),
    ("Самара", 4),
    ("Екатеринбург", 5),
    ("Омск", 6),
    ("Красноярск", 7),
    ("Иркутск", 8),
    ("Владивосток", 10),
)

HELP_TEXT = "\n".join(
    [
        style.header("📖", "КАК ИГРАТЬ", "коротко о главном"),
        "",
        "<pre>🎯 Квест дня       одна мини-игра в день\n"
        "⚡ Рискованный     ×2 очка, но −10 за провал\n"
        "🏆 Рейтинг         кто сколько заработал\n"
        "👤 Профиль         очки, серия, уровень\n"
        "🏅 Достижения      награды за квесты и серию</pre>",
        style.section("НАЧИСЛЕНИЕ ОЧКОВ"),
        "<pre>Сложность        10 / 20 / 30 очков\n"
        "Серия дней       ×1.05 в день, максимум ×1.5\n"
        "Скорость         ×1.5 или ×1.2\n"
        "Подсказка        ×0.6\n"
        "Риск             ×2 очка, минус 10 за провал</pre>",
        style.section("ЧТО ЕЩЁ УМЕЕТ БОТ"),
        "<pre>🎚 Сложность      подбирается автоматически\n"
        "⚔️ PvP           вызов на бой, одинаковый квест\n"
        "🏆 Рейтинг       очки, квесты и PvP - отдельно\n"
        "🔁 Ротатор       не выдаёт то, что ты уже проходил\n"
        "🔥 Серия         защита от одного пропущенного дня\n"
        "📝 Свой вопрос   предложи задание в общий банк\n"
        "🔔 Уведомления   можно отключить в настройках</pre>",
        style.section("КОМАНДЫ"),
        "<pre>/quest        квест дня\n"
        "/risk         рискованный квест\n"
        "/pvp          вызвать соперника на бой\n"
        "/top          рейтинг\n"
        "/profile      профиль\n"
        "/settings     настройки\n"
        "/difficulty   текущий уровень сложности\n"
        "/tz           часовой пояс\n"
        "/invite       ссылка для друзей\n"
        "/next         время до следующего квеста\n"
        "/ask          предложить свой вопрос\n"
        "/myquestions  мои вопросы\n"
        "/clear        очистить чат полностью\n"
        "/help         эта справка</pre>",
        "",
        style.note("Следующий квест приходит через 24 часа после прошлого - "
                   "в то же самое время."),
        style.note("Пропустил день - серия сохранится: раз в неделю есть защита."),
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
        "🔤 Угадай слово  ⚖️ Правда или ложь\n"
        "🧮 Счёт</pre>",
        "",
        style.note("Придумай имя для рейтинга — до 20 символов."),
        style.note("Напиши его следующим сообщением."),
    ]
)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, bot: Bot) -> None:
    tg_id = message.from_user.id

    # deep-link: /start pvp_КОД - принять вызов
    text = message.text or ""
    if "pvp_" in text:
        from .pvp import accept_flow

        parts = text.split("pvp_", 1)[1].split()
        code = parts[0].strip().upper() if parts else ""
        if not code:
            await message.answer(
                style.note("В ссылке нет кода вызова. Попроси друга прислать её целиком."),
                reply_markup=main_menu(),
            )
            return
        user = await db.get_user(tg_id)
        if user is None:
            await db.create_user(tg_id)
            await db.set_nickname(tg_id, (message.from_user.full_name or "Игрок")[:20])
        await accept_flow(message, bot, code)
        return

    user = await db.get_user(tg_id)
    if user is None:
        await db.create_user(tg_id)
        user = await db.get_user(tg_id)

    if not user["nickname"]:
        await state.set_state(Onboarding.nickname)
        await open_screen(bot, message, db, WELCOME_TEXT)
        return

    await open_screen(
        bot,
        message,
        db,
        "\n".join(
            [
                style.header("👋", "С ВОЗВРАЩЕНИЕМ", f"{user['nickname']}!"),
                style.note("Квест дня уже ждёт тебя."),
            ]
        ),
        reply_markup=main_menu(),
    )


@router.message(Onboarding.nickname, F.text, ~F.text.startswith("/"))
async def on_nickname(message: Message, state: FSMContext, bot: Bot) -> None:
    nickname = html.escape(message.text.strip()[:20]) or "Аноним"
    await db.set_nickname(message.from_user.id, nickname)
    await state.clear()
    await open_screen(
        bot,
        message,
        db,
        "\n".join(
            [
                style.header("🤝", "ПРИЯТНО ПОЗНАКОМИТЬСЯ!", nickname),
                "",
                style.note("Сложность бот подбирает сам - по твоим результатам."),
                style.note("Твой первый квест уже ждёт."),
            ]
        ),
        reply_markup=main_menu(),
    )


@router.message(Command("battles"))
async def cmd_battles(message: Message, bot: Bot) -> None:
    """История боёв: с кем играл и с каким счётом."""
    await open_screen(
        bot,
        message,
        db,
        await build_pvp_history_text(message.from_user.id),
        reply_markup=main_menu(),
    )


@router.message(Command("week"))
async def cmd_week(message: Message, bot: Bot) -> None:
    """Еженедельная сводка: итоги за неделю и соперники."""
    await open_screen(
        bot,
        message,
        db,
        await build_week_text(message.from_user.id),
        reply_markup=main_menu(),
    )


@router.message(Command("difficulty"))
async def cmd_difficulty(message: Message, bot: Bot) -> None:
    """Показать текущий адаптивный уровень."""
    from .. import adaptive

    level = await adaptive.current_level(message.from_user.id)
    await open_screen(
        bot,
        message,
        db,
        "\n".join(
            [
                style.header("🎚", "СЛОЖНОСТЬ АВТОМАТИЧЕСКАЯ", adaptive.describe(level)),
                style.note("Бот смотрит, как ты играешь, и сам меняет уровень."),
            ]
        ),
        reply_markup=main_menu(),
    )


@router.callback_query(F.data.startswith("diff:"))
async def on_difficulty(callback: CallbackQuery, state: FSMContext) -> None:
    """Старый выбор сложности - теперь она адаптивная."""
    from .. import adaptive

    level = await adaptive.current_level(callback.from_user.id)
    await safe_edit(
        callback.message,
        "\n".join(
            [
                style.header("🎚", "СЛОЖНОСТЬ АВТОМАТИЧЕСКАЯ", adaptive.describe(level)),
                style.note("Бот сам меняет уровень по твоим результатам."),
            ]
        ),
        main_menu(),
    )
    await callback.answer()


@router.message(Command("help"))
async def cmd_help(message: Message, bot: Bot) -> None:
    await open_screen(bot, message, db, HELP_TEXT, reply_markup=main_menu())


@router.message(Command("tz"))
async def cmd_tz(message: Message, bot: Bot) -> None:
    """Выбрать часовой пояс - от него зависит время выдачи квеста."""
    builder = InlineKeyboardBuilder()
    for title, offset in TZ_CHOICES:
        builder.button(text=f"{title}  UTC+{offset}", callback_data=f"tz:{offset}")
    builder.button(text="Другой — напишу сам", callback_data="tz:custom")
    builder.button(text="🔙 В меню", callback_data="menu:home")
    builder.adjust(2, 1)
    await open_screen(
        bot,
        message,
        db,
        "\n".join(
            [
                style.header("🕐", "ЧАСОВОЙ ПОЯС", "время выдачи ежедневного квеста"),
                style.note("По умолчанию Москва (UTC+3)."),
            ]
        ),
        reply_markup=builder.as_markup(),
    )


async def _finish_tz(state: FSMContext) -> None:
    """Закончить ввод часового пояса.

    Возвращаем игрока туда, откуда он пришёл: если он менял пояс посреди
    текстового квеста, тот квест должен остаться активным.
    """
    data = await state.get_data()
    previous = data.get("tz_prev_state")
    await state.update_data(tz_prev_state=None)
    if previous:
        await state.set_state(previous)
    else:
        await state.clear()


@router.callback_query(F.data.startswith("tz:"))
async def on_tz(callback: CallbackQuery, state: FSMContext) -> None:
    value = callback.data.split(":", 1)[1]
    if value == "custom":
        # запоминаем, где игрок был: смена пояса не должна выбивать
        # его из активного текстового квеста
        await state.update_data(tz_prev_state=await state.get_state())
        await state.set_state(Onboarding.tz)
        cancel = InlineKeyboardBuilder()
        cancel.button(text="🔙 В меню", callback_data="menu:home")
        cancel.adjust(1)
        await safe_edit(
            callback.message,
            "\n".join(
                [
                    style.header("🕐", "СВОЙ ЧАСОВОЙ ПОЯС"),
                    style.note("Напиши смещение в часах от UTC. Например: 3 или -5."),
                ]
            ),
            cancel.as_markup(),
        )
        await callback.answer()
        return

    try:
        offset = int(value)
    except (TypeError, ValueError):
        await callback.answer("Некорректный часовой пояс", show_alert=True)
        return
    await db.set_tz(callback.from_user.id, offset)
    await _finish_tz(state)
    await safe_edit(
        callback.message,
        "\n".join(
            [
                style.header("✅", "ЧАСОВОЙ ПОЯС СОХРАНЁН"),
                style.note(f"Теперь квест приходит в твоё {offset:+d}:00."),
            ]
        ),
        main_menu(),
    )
    await callback.answer()


@router.message(Onboarding.tz, F.text, ~F.text.startswith("/"))
async def on_tz_custom(message: Message, state: FSMContext, bot: Bot) -> None:
    raw = message.text.strip().replace(",", ".")
    try:
        offset = int(float(raw))
    except ValueError:
        # сценарий сбрасываем: иначе игрок навсегда застревает здесь
        # и не может ответить ни на один вопрос
        await state.clear()
        await message.answer(
            style.note("Нужно число. Например: 3 или -5."),
            reply_markup=main_menu(),
        )
        return
    if not -12 <= offset <= 14:
        await state.clear()
        await message.answer(
            style.note("Смещение должно быть от -12 до 14."),
            reply_markup=main_menu(),
        )
        return
    await db.set_tz(message.from_user.id, offset)
    await _finish_tz(state)
    await open_screen(
        bot,
        message,
        db,
        "\n".join(
            [
                style.header("✅", "ЧАСОВОЙ ПОЯС СОХРАНЁН"),
                style.note(f"Теперь квест приходит в твоё {offset:+d}:00."),
            ]
        ),
        reply_markup=main_menu(),
    )


@router.message(Command("invite"))
async def cmd_invite(message: Message, bot: Bot) -> None:
    """Ссылка-приглашение для друзей."""
    me = await bot.me()
    link = f"https://t.me/{me.username}"
    await open_screen(
        bot,
        message,
        db,
        "\n".join(
            [
                style.header("🔗", "ПРИГЛАШЕНИЕ"),
                f"Отправь друзьям ссылку:\n\n<b>{link}</b>",
                "",
                style.note("Каждый играет сам: своя статистика, свой квест в сутки."),
                style.note("А в рейтинге видно всех сразу."),
            ]
        ),
        reply_markup=main_menu(),
    )


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
        ),
        reply_markup=main_menu(),
    )


@router.callback_query(F.data.startswith("menu:"))
async def on_menu(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    action = callback.data.split(":", 1)[1]
    tg_id = callback.from_user.id

    # в чате могли остаться другие экраны (вызов на бой, сводка и т.п.) -
    # убираем их, чтобы меню в чате было одно
    await keep_only(bot, callback.message.chat.id, db, callback.message.message_id)

    if action == "home":
        # Выход в меню должен ещё и сбрасывать незаконченный ввод:
        # иначе следующее сообщение попадёт в старый сценарий.
        await state.clear()
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
    elif action == "next":
        avail = await availability(tg_id)
        if avail.state == STATE_COOLDOWN:
            text = "\n".join(
                [
                    style.header("⏳", "СЛЕДУЮЩИЙ КВЕСТ ЧЕРЕЗ", avail.human_left()),
                    style.note(
                        f"Будет доступен в {avail.human_due()} по твоему часовому поясу."
                    ),
                    style.note(
                        "Следующий квест доступен через 24 часа после прошлого."
                    ),
                ]
            )
        elif avail.state == STATE_ACTIVE:
            text = "\n".join(
                [
                    style.header("🎯", "У ТЕБЯ ЕСТЬ АКТИВНЫЙ КВЕСТ"),
                    style.note("Заверши его, а потом сможешь взять следующий."),
                ]
            )
        else:
            text = "\n".join(
                [
                    style.header("✅", "КВЕСТ ДОСТУПЕН СЕЙЧАС"),
                    style.note("Нажми «Квест дня», чтобы взять его."),
                ]
            )
        await safe_edit(callback.message, text, main_menu())
    elif action == "ask":
        from .ask import ask_home_markup, build_ask_home_text

        await safe_edit(
            callback.message,
            await build_ask_home_text(tg_id),
            ask_home_markup(),
        )
    elif action == "help":
        await safe_edit(callback.message, HELP_TEXT, main_menu())
    elif action == "profile":
        await safe_edit(callback.message, await build_profile_text(tg_id), main_menu())
    elif action == "week":
        await safe_edit(
            callback.message, await build_week_text(tg_id), main_menu()
        )
    elif action == "battles":
        await safe_edit(
            callback.message, await build_pvp_history_text(tg_id), main_menu()
        )
    elif action == "ach":
        from ..achievements import build_achievements_text

        await safe_edit(
            callback.message, await build_achievements_text(tg_id), main_menu()
        )
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
    elif action == "pvp":
        from .pvp import create_flow

        # сообщение с меню написал бот, а вызов создаёт нажавший
        await create_flow(
            callback.message, bot, edit=True, player_id=callback.from_user.id
        )
    elif action == "settings":
        from .settings import _settings_markup

        text, builder = await _settings_markup(callback.from_user.id)
        await safe_edit(callback.message, text, builder.as_markup())
    elif action == "invite":
        me = await bot.me()
        link = f"https://t.me/{me.username}"
        await safe_edit(
            callback.message,
            "\n".join(
                [
                    style.header("🔗", "ПРИГЛАШЕНИЕ"),
                    f"Отправь друзьям ссылку:\n\n<b>{link}</b>",
                    "",
                    style.note("Каждый играет сам: своя статистика, свой квест в сутки."),
                    style.note("А в рейтинге видно всех сразу."),
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

"""Точка входа: python -m bot

Работает и локально, и в GitHub Actions:

* локально — long polling через найденный канал (прямой, прокси или туннель
  через tg-ws-proxy);
* в GitHub Actions — прямой доступ к Telegram, работа в течение
  ``MAX_RUN_MINUTES`` минут, затем следующий прогон запускается сам.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramNetworkError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ErrorEvent

from .backup import restore_from_repo
from .config import BOT_TOKEN, DB_PATH
from .db import db
from .handlers import router as main_router
from .middleware import ErrorCounterMiddleware
from .net import build_session, detect_channel
from .selfcheck import self_check_loop
from . import style

log = logging.getLogger(__name__)


def _setup_console() -> None:
    """Windows-консоль по умолчанию не умеет UTF-8 — включаем."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):  # pragma: no cover
            pass


def _report_network_problem(exc: TelegramNetworkError, channel_description: str) -> None:
    """Понятное сообщение вместо простыни трейсбека."""
    log.error("Не удалось подключиться к api.telegram.org: %s", exc.message)
    log.error(
        "\n"
        "  Канал: %s\n"
        "  Проверить все каналы: python tools/check_channels.py\n"
        "  Другой канал можно задать в .env:\n"
        "      PROXY_URL=socks5://127.0.0.1:7891\n"
        "      TGWS_PORT=1443",
        channel_description,
    )


def _dispatch_next_run() -> None:
    """Запустить следующий прогон workflow (только в GitHub Actions)."""
    if os.getenv("DISPATCH_NEXT", "0") in ("0", "false", "no"):
        return

    token = os.getenv("GITHUB_TOKEN", "").strip()
    repo = os.getenv("GITHUB_REPOSITORY", "").strip()
    workflow = os.getenv("GITHUB_WORKFLOW", "").strip()
    if not (token and repo and workflow):
        return

    # GITHUB_WORKFLOW содержит путь к файлу, а API принимает имя файла
    # или числовой id - пробуем сначала имя, потом ищем id
    workflow_id = os.path.basename(workflow)
    url = (
        f"https://api.github.com/repos/{repo}"
        f"/actions/workflows/{workflow_id}/dispatches"
    )
    payload = json.dumps({"ref": os.getenv("GITHUB_REF_NAME", "main")}).encode()

    def request(target: str) -> int:
        req = urllib.request.Request(target, data=payload, method="POST")
        req.add_header("Authorization", f"Bearer {token}")
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                log.info("Следующий прогон запущен (HTTP %s)", response.status)
                return response.status
        except urllib.error.HTTPError as exc:
            return exc.code
        except Exception as exc:  # noqa: BLE001
            log.warning("Не удалось запустить следующий прогон: %r", exc)
            return 0

    status = request(url)
    if status == 404:
        # ищем числовой id по пути к файлу
        real_id = _workflow_id(repo, workflow, token)
        if real_id:
            status = request(
                f"https://api.github.com/repos/{repo}"
                f"/actions/workflows/{real_id}/dispatches"
            )
    if status not in (200, 201, 204):
        log.warning("Не удалось запустить следующий прогон: HTTP %s", status)


def _workflow_id(repo: str, workflow_path: str, token: str) -> str:
    """Найти числовой id workflow по его пути."""
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/actions/workflows"
    )
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001
        return ""
    for item in data.get("workflows", []):
        if item.get("path", "").endswith(workflow_path.split("/")[-1]):
            return str(item.get("id", ""))
    return ""


async def _run_polling(dp: Dispatcher, bot: Bot) -> None:
    """Лонг-поллинг с необязательным ограничением по времени."""
    minutes = float(os.getenv("MAX_RUN_MINUTES", "0") or 0)
    task = asyncio.create_task(dp.start_polling(bot))
    try:
        if minutes > 0:
            await asyncio.wait_for(asyncio.shield(task), timeout=minutes * 60)
        else:
            await task
    except asyncio.TimeoutError:
        log.info("Лимит времени (%s мин) исчерпан, останавливаюсь", minutes)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    except asyncio.CancelledError:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    )

    if not BOT_TOKEN:
        raise SystemExit(
            "BOT_TOKEN не задан.\n"
            "Локально: впиши токен в .env\n"
            "В GitHub Actions: добавь секрет BOT_TOKEN в репозитории"
        )

    channel, report = await detect_channel(BOT_TOKEN)

    for result in report:
        log.info(
            "  %s %-45s %s",
            "✓" if result.reachable else "✗",
            result.channel.description,
            result.detail,
        )

    if channel is None:
        log.error("Ни один канал до Telegram не работает.")
        log.error(
            "\n"
            "  Что можно сделать:\n"
            "  • проверить каналы: python tools/check_channels.py\n"
            "  • указать прокси в .env: PROXY_URL=socks5://127.0.0.1:7891\n"
            "  • в GitHub Actions прямой доступ работает сам"
        )
        return

    if not any(r.reachable and not r.token_ok for r in report):
        log.info("Рабочий канал: %s", channel.description)
    else:
        log.error(
            "Telegram отклонил токен (401). Проверь значение BOT_TOKEN:\n"
            "  локально - файл .env\n"
            "  GitHub Actions - Settings -> Secrets and variables -> Actions -> BOT_TOKEN"
        )
        return

    session = build_session(channel)

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        session=session,
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(main_router)
    # считаем ошибки в обработчиках - по ним сторож поймёт,
    # что бот жив, но сломан
    dp.message.middleware(ErrorCounterMiddleware())
    dp.callback_query.middleware(ErrorCounterMiddleware())

    # Ошибка в обработчике не должна выглядеть как «бот замолчал»
    dp.errors.register(handle_error)

    log.info(
        "Параметры прогона: MAX_RUN_MINUTES=%s DISPATCH_NEXT=%s DROP_PENDING_UPDATES=%s",
        os.getenv("MAX_RUN_MINUTES"),
        os.getenv("DISPATCH_NEXT"),
        os.getenv("DROP_PENDING_UPDATES"),
    )

    # если кэш Actions потерялся - берём базу из репозитория (зашифрованную)
    try:
        restore_status = await restore_from_repo(Path.cwd(), Path(DB_PATH).resolve())
        log.info("Восстановление базы: %s", restore_status)
    except Exception as exc:  # noqa: BLE001
        log.warning("Не удалось проверить бэкап в репозитории: %r", exc)

    await db.connect()
    log.info("База данных подключена: %s", db.path)
    purged = await db.purge_personal_fields()
    if purged:
        log.info("Очищено личных полей из базы: %s записей", purged)
    try:
        from .services import backfill_item_keys

        fixed = await backfill_item_keys()
        if fixed:
            log.info("Проставлены ключи заданий: %s квестов", fixed)
    except Exception as exc:  # noqa: BLE001
        log.warning("Не удалось проставить ключи заданий: %r", exc)

    try:
        drop_pending = os.getenv("DROP_PENDING_UPDATES", "1") not in ("0", "false", "no")
        try:
            await bot.delete_webhook(drop_pending_updates=drop_pending)
        except TelegramNetworkError as exc:
            _report_network_problem(exc, channel.description)
            return
        try:
            me = await bot.me()
            log.info("Бот запущен: @%s (id %s), жду сообщений…", me.username, me.id)
        except Exception:  # noqa: BLE001
            log.info("Бот запущен, жду сообщений…")

        # выдаём квесты тем, кому положено (и ждём, если срок скоро)
        max_run = float(os.getenv("MAX_RUN_MINUTES", "0") or 0)
        daily_task = asyncio.create_task(_daily_pass(bot, max_run))
        # и проверяем сами себя: бот жив, но обработчики могли сломаться
        check_task = asyncio.create_task(self_check_loop(dp, bot))
        try:
            # именно _run_polling: он останавливает поллинг по таймеру
            await _run_polling(dp, bot)
        finally:
            for task in (daily_task, check_task):
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
    finally:
        log.info("Завершаюсь: закрываю сессию")
        await bot.session.close()
        log.info("Завершаюсь: закрываю базу")
        await db.close()
        log.info("Завершаюсь: делаю бэкап")
        # даже если бот упал - сохраняем базу и поддерживаем цепочку прогонов
        await _backup_database()
        log.info("Завершаюсь: запускаю следующий прогон")
        _dispatch_next_run()
        log.info("Завершился")


async def handle_error(event: ErrorEvent) -> bool:
    """Ошибка в обработчике не должна выглядеть как «бот замолчал».

    Игроку честно говорим, что что-то сломалось. Счётчик ошибок при этом
    уже посчитан middleware - сторож увидит и тревогу.
    """
    log.warning("Ошибка при обработке апдейта: %r", event.exception)
    try:
        if event.update.message is not None:
            await event.update.message.answer(
                "\n".join(
                    [
                        style.header("⚠️", "ЧТО-ТО СЛОМАЛОСЬ"),
                        style.note(
                            "Попробуй ещё раз — если не выйдет, напиши хозяину бота."
                        ),
                    ]
                )
            )
        elif event.update.callback_query is not None:
            await event.update.callback_query.answer(
                "Что-то сломалось, попробуй ещё раз", show_alert=True
            )
    except Exception:  # noqa: BLE001 - сообщение об ошибке не должно её усугубить
        log.debug("Не удалось сообщить игроку об ошибке", exc_info=True)
    return True


async def _backup_database() -> None:
    """Закоммитить базу в репозиторий (зашифрованной) - страховка от потери кэша."""
    from pathlib import Path

    from .backup import backup_database
    from .config import DB_PATH

    try:
        status = await backup_database(Path.cwd(), Path(DB_PATH).resolve())
        log.info("Бэкап базы: %s", status)
    except Exception as exc:  # noqa: BLE001
        log.warning("Бэкап базы не удался: %r", exc)


async def _daily_pass(bot: Bot, max_run_minutes: float) -> None:
    """Раздать ежедневные квесты.

    Если квест положен скоро (в пределах времени работы прогона), бот
    дождётся нужного момента и отправит его ровно в срок.
    """
    from .daily import run_daily_pass

    max_wait = max(0.0, (max_run_minutes - 5) * 60) if max_run_minutes else 0.0
    try:
        issued = await run_daily_pass(bot, max_wait=max_wait)
        if issued:
            log.info("Ежедневных квестов выдано: %s", issued)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        log.warning("Не удалось раздать ежедневные квесты: %r", exc)


if __name__ == "__main__":
    _setup_console()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nБот остановлен.")

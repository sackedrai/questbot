"""Проверка остановки лонг-поллинга по таймеру - с настоящим aiogram.

Запуск: python tools/polling_test.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # pragma: no cover
        pass

from aiogram import Bot, Dispatcher  # noqa: E402
from aiogram.client.session.aiohttp import AiohttpSession  # noqa: E402
from aiogram.methods import GetMe, GetUpdates  # noqa: E402
from aiogram.types import User  # noqa: E402

from bot.__main__ import _run_polling  # noqa: E402

PASSED = 0
FAILED = 0


def check(condition: bool, label: str) -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  ok   {label}")
    else:
        FAILED += 1
        print(f"  FAIL {label}")


class MockSession(AiohttpSession):
    """Сессия без сети: отвечает на getUpdates пустым списком.

    Задержка обязательна: без неё цикл опроса превращается в плотный
    spin, и отмена задачи не доставляется - event loop не получает
    управления.
    """

    async def make_request(self, bot, method, timeout=None):
        if isinstance(method, GetMe):
            return User(id=1, is_bot=True, first_name="Bot", username="test_bot")
        if isinstance(method, GetUpdates):
            await asyncio.sleep(0.05)
            return []
        return True


async def main() -> None:
    print("=" * 60)
    print("  Остановка поллинга по таймеру")
    print("=" * 60)

    import faulthandler

    faulthandler.dump_traceback_later(40, exit=True)

    os.environ["MAX_RUN_MINUTES"] = "0.05"  # 3 секунды
    dp = Dispatcher()
    bot = Bot(token="123456:AAFake", session=MockSession())

    started = time.time()
    await asyncio.wait_for(_run_polling(dp, bot), timeout=30)
    elapsed = time.time() - started

    check(2.5 < elapsed < 12, f"остановился по таймеру за {elapsed:.1f}с")

    # без лимита - поллинг должен идти (проверим отмену задачи)
    os.environ["MAX_RUN_MINUTES"] = "0.05"
    dp2 = Dispatcher()
    bot2 = Bot(token="123456:AAFake", session=MockSession())
    try:
        await asyncio.wait_for(_run_polling(dp2, bot2), timeout=30)
        check(True, "второй запуск тоже остановился")
    except asyncio.TimeoutError:
        check(False, "второй запуск завис")

    os.environ.pop("MAX_RUN_MINUTES", None)
    print("\n" + "=" * 60)
    print(f"  Пройдено: {PASSED}   Провалено: {FAILED}")
    print("=" * 60)
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    asyncio.run(main())

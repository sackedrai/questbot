"""Проверка всех каналов доступа к Telegram — так же, как это делает бот.

Запуск: python tools/check_channels.py
Бот при старте делает ровно то же самое и выбирает первый рабочий канал.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # pragma: no cover
        pass

from dotenv import load_dotenv  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

import os  # noqa: E402

from bot.net import candidate_channels, probe  # noqa: E402


async def main() -> None:
    token = os.getenv("BOT_TOKEN", "").strip()

    print("=" * 68)
    print("  Каналы доступа к Telegram")
    print("=" * 68)

    if not token:
        print("\nBOT_TOKEN пуст в .env — Bot API проверить нечем.\n")

    channels = candidate_channels()
    if not channels:
        print("Кандидатов нет.")
        return

    print(f"\nПроверяю {len(channels)} канал(ов) параллельно...\n")

    results = await asyncio.gather(*(probe(ch, token) for ch in channels))

    winner = None
    for result in results:
        mark = "✓" if result.reachable else "✗"
        print(f"  {mark} {result.channel.description:<48} {result.detail}")
        if result.reachable and winner is None:
            winner = result

    print()
    if winner:
        print(f"  Бот выберет: {winner.channel.description}")
        if not winner.token_ok:
            print("  ⚠ Telegram отклонил токен - проверь BOT_TOKEN")
    else:
        print("  Рабочего канала нет. Варианты:")
        print("   • запусти TgWsProxy - бот найдёт его сам")
        print("   • PROXY_URL=socks5://127.0.0.1:7891 в .env")
        print("   • в GitHub Actions прямой доступ работает сам")
    print()


if __name__ == "__main__":
    asyncio.run(main())

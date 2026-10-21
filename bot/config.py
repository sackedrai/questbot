"""Конфигурация и игровые константы."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "").strip()
DB_PATH: str = os.getenv("DB_PATH", str(BASE_DIR / "data" / "questbot.db"))

# Кто может пользоваться админ-разделом бота (tg_id владельца).
# Пусто - админки нет, никто не сможет ею воспользоваться.
ADMIN_CHAT_ID: str = os.getenv("ADMIN_CHAT_ID", "").strip()

# Прокси для Telegram, если api.telegram.org недоступен напрямую.
# Примеры: socks5://user:pass@host:1080  или  http://host:8080
PROXY_URL: str = os.getenv("PROXY_URL", "").strip()

# Свой адрес Bot API — например, зеркало на Cloudflare Worker.
# Пример: https://my-worker.workers.dev
API_BASE_URL: str = os.getenv("API_BASE_URL", "").strip()

# Локальный туннель tg-ws-proxy (MTProto over WebSocket).
# Порт 1443 — дефолтный для TgWsProxy. Поставь 0, чтобы отключить.
TGWS_HOST: str = os.getenv("TGWS_HOST", "127.0.0.1").strip()
TGWS_PORT: int = int(os.getenv("TGWS_PORT", "0") or 0)

# --- игровая механика ---

# Сколько бесплатных квестов в день
QUEST_PER_DAY = 1
# Сколько рискованных квестов (x2 к очкам) в день
BONUS_QUEST_PER_DAY = 1

# Базовые очки за квест в зависимости от сложности
BASE_POINTS = {"easy": 10, "medium": 20, "hard": 30}

# Бонус за серию дней: +5% за день, максимум +50%
STREAK_BONUS_PER_DAY = 0.05
STREAK_BONUS_MAX_DAYS = 10

# Защита серии: раз в сколько дней игрок может пропустить день,
# не обнулив серию (как «заморозка» в Duolingo)
STREAK_FREE_COOLDOWN_DAYS = 7

# Скорость ответа в «быстром» квесте: (порог x1.5, порог x1.2) в секундах
FAST_BONUS_SECONDS = (5.0, 15.0)

# Штраф за использованную подсказку
HINT_PENALTY = 0.6

# Множитель за рискованный квест
RISKY_MULTIPLIER = 2.0

# Сколько очков снимается за провал рискованного квеста
RISK_PENALTY = 10

# Сколько попыток на угадывание буквы в игре «Угадай слово»
WORD_LIVES = 7

# Сколько ошибок на сортировке по хронологии допустимо
TIMELINE_MAX_MISTAKES = 2

DIFFICULTY_TITLES = {
    "easy": "🟢 Лёгкий",
    "medium": "🟡 Средний",
    "hard": "🔴 Сложный",
}

DIFFICULTY_HINTS = {
    "easy": "Больше фактов и логики, меньше эзотерики",
    "medium": "Придётся подумать, но без гугла",
    "hard": "Для тех, кто читает википедию по ночам",
}

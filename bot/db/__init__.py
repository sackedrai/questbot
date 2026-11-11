"""Слой доступа к данным: SQLite через aiosqlite.

База разложена по миксинам - так её легче читать и дополнять:

* ``base`` - подключение и миграции;
* ``users`` - игроки, серия, очки;
* ``quests`` - квесты и ротатор;
* ``achievements`` - достижения;
* ``admin`` - сводки для админки, воронка, уборка;
* ``messages`` - сообщения чата (для автоочистки);
* ``meta`` - метрики бота;
* ``pvp`` - матчи PvP;
* ``leaderboard`` - таблицы лидеров;
* ``userquestions`` - вопросы игроков и модерация.

Класс ``Database`` собирает их вместе, поэтому снаружи он выглядит
как раньше: ``from .db import db`` работает и даёт готовую базу.
"""

from __future__ import annotations

from ..config import DB_PATH
from .achievements import AchievementsMixin
from .admin import AdminMixin
from .base import DatabaseBase
from .helpers import today_iso, week_start_iso
from .leaderboard import LeaderboardMixin
from .messages import MessagesMixin
from .meta import MetaMixin
from .pvp import PvpMixin
from .quests import QuestsMixin
from .schema import MIGRATIONS, SCHEMA
from .userquestions import UserQuestionsMixin
from .users import UsersMixin

__all__ = [
    "Database",
    "MIGRATIONS",
    "SCHEMA",
    "db",
    "today_iso",
    "week_start_iso",
]


class Database(
    UsersMixin,
    QuestsMixin,
    AchievementsMixin,
    AdminMixin,
    MessagesMixin,
    MetaMixin,
    PvpMixin,
    LeaderboardMixin,
    UserQuestionsMixin,
    DatabaseBase,
):
    """Доступ к данным. Свойства и методы - в миксинах."""


db = Database(DB_PATH)

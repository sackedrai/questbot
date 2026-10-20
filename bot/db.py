"""Слой доступа к данным: SQLite через aiosqlite."""

from __future__ import annotations

import json
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional

import aiosqlite

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    tg_id         INTEGER PRIMARY KEY,
    username      TEXT    DEFAULT '',
    display_name  TEXT    DEFAULT '',
    nickname      TEXT    DEFAULT '',
    difficulty    TEXT    DEFAULT 'medium',
    points        INTEGER DEFAULT 0,
    streak        INTEGER DEFAULT 0,
    best_streak   INTEGER DEFAULT 0,
    quests_done   INTEGER DEFAULT 0,
    correct       INTEGER DEFAULT 0,
    wrong         INTEGER DEFAULT 0,
    last_quest_day TEXT   DEFAULT '',
    created_at    REAL    DEFAULT 0
);

CREATE TABLE IF NOT EXISTS quests (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id       INTEGER NOT NULL,
    day         TEXT    NOT NULL,
    game_type   TEXT    NOT NULL,
    difficulty  TEXT    NOT NULL,
    payload     TEXT    NOT NULL,
    points      INTEGER DEFAULT 0,
    status      TEXT    DEFAULT 'active',
    risky       INTEGER DEFAULT 0,
    started_at  REAL    DEFAULT 0,
    finished_at REAL    DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_quests_user_day ON quests (tg_id, day);
CREATE INDEX IF NOT EXISTS idx_quests_day       ON quests (day);
CREATE INDEX IF NOT EXISTS idx_quests_status    ON quests (status);
"""


def today_iso() -> str:
    return date.today().isoformat()


def week_start_iso() -> str:
    """Понедельник текущей недели."""
    today = date.today()
    return (today - timedelta(days=today.weekday())).isoformat()


class Database:
    """Обёртка над SQLite. Все методы асинхронные."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._db: Optional[aiosqlite.Connection] = None

    # ------------------------------------------------------------------
    # подключение
    # ------------------------------------------------------------------
    async def connect(self) -> None:
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(SCHEMA)
        await self._db.commit()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("База данных не подключена, вызовите connect()")
        return self._db

    # ------------------------------------------------------------------
    # пользователи
    # ------------------------------------------------------------------
    async def get_user(self, tg_id: int) -> Optional[aiosqlite.Row]:
        async with self.db.execute(
            "SELECT * FROM users WHERE tg_id = ?", (tg_id,)
        ) as cur:
            return await cur.fetchone()

    async def create_user(self, tg_id: int, username: str, display_name: str) -> None:
        await self.db.execute(
            "INSERT OR IGNORE INTO users (tg_id, username, display_name, created_at)"
            " VALUES (?, ?, ?, ?)",
            (tg_id, username, display_name, time.time()),
        )
        await self.db.commit()

    async def set_nickname(self, tg_id: int, nickname: str) -> None:
        await self.db.execute(
            "UPDATE users SET nickname = ? WHERE tg_id = ?", (nickname, tg_id)
        )
        await self.db.commit()

    async def set_difficulty(self, tg_id: int, difficulty: str) -> None:
        await self.db.execute(
            "UPDATE users SET difficulty = ? WHERE tg_id = ?", (difficulty, tg_id)
        )
        await self.db.commit()

    async def touch_day(self, tg_id: int, day: str) -> int:
        """Отметить игру за сегодня и вернуть актуальную длину серии.

        Повторный квест в тот же день серию не увеличивает. Если день
        пропущен — серия начинается заново.
        """
        user = await self.get_user(tg_id)
        if user is None:
            raise RuntimeError(f"Пользователь {tg_id} не найден")

        streak = user["streak"]
        last_day = user["last_quest_day"]
        if last_day != day:
            yesterday = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
            streak = streak + 1 if last_day == yesterday else 1
            await self.db.execute(
                "UPDATE users SET streak = ?, best_streak = MAX(best_streak, ?),"
                " last_quest_day = ? WHERE tg_id = ?",
                (streak, streak, day, tg_id),
            )
            await self.db.commit()
        return streak

    async def add_result(self, tg_id: int, points: int, correct: bool) -> aiosqlite.Row:
        """Начислить (или списать) очки и обновить счётчики."""
        await self.db.execute(
            """
            UPDATE users
               SET points      = MAX(0, points + ?),
                   quests_done = quests_done + 1,
                   correct     = correct + ?,
                   wrong       = wrong + ?
             WHERE tg_id = ?
            """,
            (points, 1 if correct else 0, 0 if correct else 1, tg_id),
        )
        await self.db.commit()
        return await self.get_user(tg_id)  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # квесты
    # ------------------------------------------------------------------
    async def create_quest(
        self,
        tg_id: int,
        day: str,
        game_type: str,
        difficulty: str,
        payload: dict[str, Any],
        risky: bool = False,
    ) -> int:
        cur = await self.db.execute(
            """
            INSERT INTO quests (tg_id, day, game_type, difficulty, payload, risky, started_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tg_id,
                day,
                game_type,
                difficulty,
                json.dumps(payload, ensure_ascii=False),
                1 if risky else 0,
                time.time(),
            ),
        )
        await self.db.commit()
        return int(cur.lastrowid)

    async def get_quest(self, quest_id: int) -> Optional[aiosqlite.Row]:
        async with self.db.execute(
            "SELECT * FROM quests WHERE id = ?", (quest_id,)
        ) as cur:
            return await cur.fetchone()

    async def update_quest_payload(self, quest_id: int, payload: dict[str, Any]) -> None:
        await self.db.execute(
            "UPDATE quests SET payload = ? WHERE id = ?",
            (json.dumps(payload, ensure_ascii=False), quest_id),
        )
        await self.db.commit()

    async def get_active_quest(self, tg_id: int) -> Optional[aiosqlite.Row]:
        """Последний незавершённый квест игрока."""
        async with self.db.execute(
            "SELECT * FROM quests WHERE tg_id = ? AND status = 'active'"
            " ORDER BY id DESC LIMIT 1",
            (tg_id,),
        ) as cur:
            return await cur.fetchone()

    async def finish_quest(self, quest_id: int, points: int, status: str) -> None:
        await self.db.execute(
            "UPDATE quests SET points = ?, status = ?, finished_at = ? WHERE id = ?",
            (points, status, time.time(), quest_id),
        )
        await self.db.commit()

    async def count_quests_today(self, tg_id: int, day: str, risky: bool) -> int:
        """Сколько квестов этого типа уже занято сегодня.

        Проваленные квесты не считаются — их можно переиграть.
        """
        async with self.db.execute(
            """
            SELECT COUNT(*) AS c
              FROM quests
             WHERE tg_id = ? AND day = ? AND risky = ? AND status != 'failed'
            """,
            (tg_id, day, 1 if risky else 0),
        ) as cur:
            row = await cur.fetchone()
        return int(row["c"])

    async def daily_summary(self, tg_id: int, day: str) -> aiosqlite.Row:
        async with self.db.execute(
            """
            SELECT COUNT(*)           AS total,
                   COALESCE(SUM(CASE WHEN status = 'done'   THEN points END), 0) AS points,
                   COALESCE(SUM(CASE WHEN status = 'done'   THEN 1 END), 0)      AS done,
                   COALESCE(SUM(CASE WHEN status = 'failed' THEN 1 END), 0)      AS failed
              FROM quests WHERE tg_id = ? AND day = ?
            """,
            (tg_id, day),
        ) as cur:
            return await cur.fetchone()  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # рейтинг
    # ------------------------------------------------------------------
    async def leaderboard(self, scope: str = "all", limit: int = 10) -> list[aiosqlite.Row]:
        if scope == "today":
            where, params = "q.day = ?", (today_iso(),)
        elif scope == "week":
            where, params = "q.day >= ?", (week_start_iso(),)
        else:
            where, params = "1 = 1", ()

        sql = f"""
            SELECT u.tg_id, u.nickname, u.username, u.display_name, u.difficulty,
                   u.points AS total_points,
                   COALESCE(SUM(q.points), 0) AS scope_points
              FROM users u
              LEFT JOIN quests q
                     ON q.tg_id = u.tg_id AND q.status = 'done' AND {where}
             GROUP BY u.tg_id
            HAVING scope_points > 0
            ORDER BY scope_points DESC, u.points DESC, u.quests_done ASC
             LIMIT ?
        """
        async with self.db.execute(sql, (*params, limit)) as cur:
            return list(await cur.fetchall())

    async def user_position(self, tg_id: int, scope: str = "all") -> Optional[int]:
        """Место игрока в рейтинге (1-based) либо None, если его нет."""
        rows = await self.leaderboard(scope=scope, limit=1000)
        for index, row in enumerate(rows, start=1):
            if row["tg_id"] == tg_id:
                return index
        return None


db = Database(DB_PATH)

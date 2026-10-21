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
    finished_at REAL    DEFAULT 0,
    item_key    TEXT    DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_quests_user_day ON quests (tg_id, day);
CREATE INDEX IF NOT EXISTS idx_quests_day       ON quests (day);
CREATE INDEX IF NOT EXISTS idx_quests_status    ON quests (status);

CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     INTEGER NOT NULL,
    message_id  INTEGER NOT NULL,
    kind        TEXT    DEFAULT 'quest',
    created_at  REAL    DEFAULT 0
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS achievements (
    tg_id     INTEGER NOT NULL,
    code      TEXT    NOT NULL,
    earned_at REAL    DEFAULT 0,
    PRIMARY KEY (tg_id, code)
);

CREATE TABLE IF NOT EXISTS pvp_matches (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT    UNIQUE,
    player1     INTEGER NOT NULL,
    player2     INTEGER DEFAULT 0,
    game_type   TEXT    DEFAULT '',
    difficulty  TEXT    DEFAULT '',
    payload     TEXT    DEFAULT '{}',
    status      TEXT    DEFAULT 'waiting',
    points1     INTEGER DEFAULT 0,
    points2     INTEGER DEFAULT 0,
    winner      INTEGER DEFAULT 0,
    created_at  REAL    DEFAULT 0,
    finished_at REAL    DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages (chat_id, id);
CREATE INDEX IF NOT EXISTS idx_pvp_players ON pvp_matches (player1, player2);
"""

# Новые колонки, которые добавляются к уже существующим таблицам.
MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "users": [
        ("tz_offset", "INTEGER DEFAULT 3"),
        ("notify", "INTEGER DEFAULT 1"),
        ("pvp_wins", "INTEGER DEFAULT 0"),
        ("pvp_losses", "INTEGER DEFAULT 0"),
        ("pvp_points", "INTEGER DEFAULT 0"),
        ("streak_free_day", "TEXT DEFAULT ''"),
    ],
    "quests": [
        ("pvp_id", "INTEGER DEFAULT 0"),
        ("item_key", "TEXT DEFAULT ''"),
    ],
}


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
        try:
            await self._db.executescript(SCHEMA)
            await self._migrate()
            await self._db.commit()
        except Exception:
            # Не оставляем висящее соединение: поток aiosqlite держит
            # процесс, и вместо падения бот "зависает" до конца прогона.
            await self._db.close()
            self._db = None
            raise

    async def _migrate(self) -> None:
        """Добавить недостающие колонки в существующие таблицы."""
        for table, columns in MIGRATIONS.items():
            async with self.db.execute(f"PRAGMA table_info({table})") as cur:
                existing = {row["name"] for row in await cur.fetchall()}
            for name, ddl in columns:
                if name not in existing:
                    await self.db.execute(
                        f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"
                    )
        # Индексы по новым колонкам создаём после миграции: в SCHEMA они бы
        # ломали старые базы, где колонки ещё нет.
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_quests_user_key"
            " ON quests (tg_id, item_key)"
        )
        await self.db.commit()

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

    async def create_user(self, tg_id: int) -> None:
        """Завести игрока.

        Username и display_name намеренно не храним: ник игрок задаёт сам
        (он всегда есть), а @username Telegram присылает с каждым
        сообщением. Хранить его в базе незачем, а бэкап базы публичный.
        """
        await self.db.execute(
            "INSERT OR IGNORE INTO users (tg_id, created_at) VALUES (?, ?)",
            (tg_id, time.time()),
        )
        await self.db.commit()

    async def purge_personal_fields(self) -> int:
        """Стереть @username и имя из базы (остаются только id и ник)."""
        cur = await self.db.execute(
            "UPDATE users SET username = '', display_name = ''"
            " WHERE username != '' OR display_name != ''"
        )
        changed = cur.rowcount or 0
        await self.db.commit()
        return changed

    async def set_nickname(self, tg_id: int, nickname: str) -> None:
        await self.db.execute(
            "INSERT INTO users (tg_id, nickname, created_at) VALUES (?, ?, ?)"
            " ON CONFLICT(tg_id) DO UPDATE SET nickname = excluded.nickname",
            (tg_id, nickname, time.time()),
        )
        await self.db.commit()

    async def set_difficulty(self, tg_id: int, difficulty: str) -> None:
        await self.db.execute(
            "INSERT INTO users (tg_id, difficulty, created_at) VALUES (?, ?, ?)"
            " ON CONFLICT(tg_id) DO UPDATE SET difficulty = excluded.difficulty",
            (tg_id, difficulty, time.time()),
        )
        await self.db.commit()

    async def touch_day(self, tg_id: int, day: str) -> int:
        """Отметить игру за сегодня и вернуть актуальную длину серии.

        Повторный квест в тот же день серию не увеличивает. Если день
        пропущен - серия начинается заново, кроме случая, когда игрок
        пропустил ровно один день и у него доступна защита серии.
        """
        user = await self.get_user(tg_id)
        if user is None:
            raise RuntimeError(f"Пользователь {tg_id} не найден")

        streak = user["streak"]
        last_day = user["last_quest_day"]
        if last_day != day:
            yesterday = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
            if last_day == yesterday:
                streak = streak + 1
            else:
                missed_one = last_day == (
                    date.fromisoformat(day) - timedelta(days=2)
                ).isoformat()
                if missed_one and await self._take_streak_free(tg_id, day):
                    # пропущен один день, но защита сработала
                    streak = streak + 1
                else:
                    streak = 1
            await self.db.execute(
                "UPDATE users SET streak = ?, best_streak = MAX(best_streak, ?),"
                " last_quest_day = ? WHERE tg_id = ?",
                (streak, streak, day, tg_id),
            )
            await self.db.commit()
        return streak

    async def _take_streak_free(self, tg_id: int, day: str) -> bool:
        """Потратить защиту серии, если она доступна. Возвращает True, если потратили."""
        from .config import STREAK_FREE_COOLDOWN_DAYS

        user = await self.get_user(tg_id)
        if user is None:
            return False
        last_used = user["streak_free_day"] or ""
        if last_used:
            try:
                used = date.fromisoformat(last_used)
            except ValueError:
                used = None
            if used is not None:
                cooldown = (date.fromisoformat(day) - used).days
                if cooldown < STREAK_FREE_COOLDOWN_DAYS:
                    return False
        await self.db.execute(
            "UPDATE users SET streak_free_day = ? WHERE tg_id = ?", (day, tg_id)
        )
        await self.db.commit()
        return True

    async def streak_free_available(self, tg_id: int, today: Optional[str] = None) -> bool:
        """Доступна ли защита серии (не использована за последние дни)."""
        from .config import STREAK_FREE_COOLDOWN_DAYS

        user = await self.get_user(tg_id)
        if user is None:
            return False
        last_used = user["streak_free_day"] or ""
        if not last_used:
            return True
        try:
            used = date.fromisoformat(last_used)
        except ValueError:
            return True
        day = date.fromisoformat(today) if today else date.today()
        return (day - used).days >= STREAK_FREE_COOLDOWN_DAYS

    async def streak_free_used_today(self, tg_id: int, day: str) -> bool:
        """Использовалась ли сегодня защита серии."""
        user = await self.get_user(tg_id)
        if user is None:
            return False
        return (user["streak_free_day"] or "") == day

    async def add_result(
        self,
        tg_id: int,
        points: int,
        correct: bool,
        count_quest: bool = True,
    ) -> aiosqlite.Row:
        """Начислить (или списать) очки и обновить счётчики.

        Для PvP-квестов очки идут в общий зачёт, но сам квест не
        засчитывается в счётчики - иначе можно было бы набить их
        дублирующими матчами.
        """
        await self.db.execute(
            """
            UPDATE users
               SET points      = MAX(0, points + ?),
                   quests_done = quests_done + ?,
                   correct     = correct + ?,
                   wrong       = wrong + ?
             WHERE tg_id = ?
            """,
            (
                points,
                1 if count_quest else 0,
                1 if (correct and count_quest) else 0,
                0 if (correct or not count_quest) else 1,
                tg_id,
            ),
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
        pvp_id: int = 0,
        item_key: str = "",
    ) -> int:
        cur = await self.db.execute(
            """
            INSERT INTO quests (tg_id, day, game_type, difficulty, payload, risky,
                                pvp_id, started_at, item_key)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tg_id,
                day,
                game_type,
                difficulty,
                json.dumps(payload, ensure_ascii=False),
                1 if risky else 0,
                pvp_id,
                time.time(),
                item_key,
            ),
        )
        await self.db.commit()
        return int(cur.lastrowid)

    async def used_item_keys(self, tg_id: int) -> set[str]:
        """Ключи заданий, которые игрок уже получал.

        Ротатор по этому набору не выдаёт прошлое повторно.
        """
        async with self.db.execute(
            "SELECT DISTINCT item_key FROM quests"
            " WHERE tg_id = ? AND item_key != ''",
            (tg_id,),
        ) as cur:
            rows = await cur.fetchall()
        return {row["item_key"] for row in rows}

    async def count_used_items(self, tg_id: int) -> int:
        """Сколько разных заданий игрок уже прошёл."""
        async with self.db.execute(
            "SELECT COUNT(DISTINCT item_key) AS c FROM quests"
            " WHERE tg_id = ? AND item_key != ''",
            (tg_id,),
        ) as cur:
            row = await cur.fetchone()
        return int(row["c"]) if row else 0

    async def quests_without_key(self) -> list[aiosqlite.Row]:
        """Квесты, выданные до появления ротатора (ключ ещё не проставлен)."""
        async with self.db.execute(
            "SELECT id, game_type, payload FROM quests WHERE item_key = ''"
        ) as cur:
            return list(await cur.fetchall())

    async def set_quest_item_key(self, quest_id: int, item_key: str) -> None:
        await self.db.execute(
            "UPDATE quests SET item_key = ? WHERE id = ?", (item_key, quest_id)
        )
        await self.db.commit()

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

        Проваленные и пропущенные квесты не считаются - их можно переиграть.
        """
        async with self.db.execute(
            """
            SELECT COUNT(*) AS c
              FROM quests
             WHERE tg_id = ? AND day = ? AND risky = ?
               AND status NOT IN ('failed', 'skipped', 'expired')
            """,
            (tg_id, day, 1 if risky else 0),
        ) as cur:
            row = await cur.fetchone()
        return int(row["c"])

    async def all_users(self) -> list[aiosqlite.Row]:
        """Все зарегистрированные игроки."""
        async with self.db.execute("SELECT * FROM users") as cur:
            return list(await cur.fetchall())

    async def set_tz(self, tg_id: int, offset: int) -> None:
        """Часовой пояс игрока (смещение в часах от UTC)."""
        await self.db.execute(
            "UPDATE users SET tz_offset = ? WHERE tg_id = ?", (offset, tg_id)
        )
        await self.db.commit()

    async def last_done_at(self, tg_id: int, risky: bool = False) -> Optional[float]:
        """Время последнего успешно пройденного квеста (unix ts)."""
        async with self.db.execute(
            "SELECT MAX(finished_at) AS t FROM quests"
            " WHERE tg_id = ? AND status = 'done' AND risky = ?",
            (tg_id, 1 if risky else 0),
        ) as cur:
            row = await cur.fetchone()
        return row["t"] if row and row["t"] else None

    async def last_issued_at(self, tg_id: int) -> Optional[float]:
        """Когда игроку последний раз выдавали квест (любой)."""
        async with self.db.execute(
            "SELECT MAX(started_at) AS t FROM quests WHERE tg_id = ?", (tg_id,)
        ) as cur:
            row = await cur.fetchone()
        return row["t"] if row and row["t"] else None

    # ------------------------------------------------------------------
    # массовые выборки (для ежедневного обхода без запроса на игрока)
    # ------------------------------------------------------------------
    async def active_quests_map(self) -> dict[int, aiosqlite.Row]:
        """Активный (незавершённый) квест каждого игрока: tg_id -> строка."""
        async with self.db.execute(
            "SELECT * FROM quests WHERE status = 'active' ORDER BY id DESC"
        ) as cur:
            rows = await cur.fetchall()
        result: dict[int, aiosqlite.Row] = {}
        for row in rows:
            # id DESC + setdefault = самый свежий квест игрока
            result.setdefault(row["tg_id"], row)
        return result

    async def last_done_map(self, risky: bool = False) -> dict[int, float]:
        """Когда каждый игрок последний раз проходил квест: tg_id -> время."""
        async with self.db.execute(
            "SELECT tg_id, MAX(finished_at) AS t FROM quests"
            " WHERE status = 'done' AND risky = ? GROUP BY tg_id",
            (1 if risky else 0,),
        ) as cur:
            rows = await cur.fetchall()
        return {row["tg_id"]: row["t"] for row in rows if row["t"]}

    async def last_issued_map(self) -> dict[int, float]:
        """Когда каждому игроку последний раз выдавали квест: tg_id -> время."""
        async with self.db.execute(
            "SELECT tg_id, MAX(started_at) AS t FROM quests GROUP BY tg_id"
        ) as cur:
            rows = await cur.fetchall()
        return {row["tg_id"]: row["t"] for row in rows if row["t"]}

    async def finish_expired_quests(self, max_age: float) -> int:
        """Закрыть квесты, которые висят дольше max_age секунд.

        Возвращает число закрытых - иначе игрок застревает на старом квесте.
        """
        now = time.time()
        cur = await self.db.execute(
            "UPDATE quests SET status = 'expired', finished_at = ?"
            " WHERE status = 'active' AND started_at > 0 AND started_at < ?",
            (now, now - max_age),
        )
        await self.db.commit()
        return cur.rowcount or 0

    async def best_day_points(self, tg_id: int) -> int:
        """Лучший день игрока по сумме очков."""
        async with self.db.execute(
            "SELECT COALESCE(SUM(points), 0) AS best FROM quests"
            " WHERE tg_id = ? AND status = 'done' GROUP BY day"
            " ORDER BY best DESC LIMIT 1",
            (tg_id,),
        ) as cur:
            row = await cur.fetchone()
        return int(row["best"]) if row else 0

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
    # достижения
    # ------------------------------------------------------------------
    async def earned_achievements(self, tg_id: int) -> set[str]:
        """Коды уже полученных достижений."""
        async with self.db.execute(
            "SELECT code FROM achievements WHERE tg_id = ?", (tg_id,)
        ) as cur:
            rows = await cur.fetchall()
        return {row["code"] for row in rows}

    async def grant_achievement(self, tg_id: int, code: str) -> None:
        await self.db.execute(
            "INSERT OR IGNORE INTO achievements (tg_id, code, earned_at)"
            " VALUES (?, ?, ?)",
            (tg_id, code, time.time()),
        )
        await self.db.commit()

    # ------------------------------------------------------------------
    # админка
    # ------------------------------------------------------------------
    async def stats_overview(self) -> dict[str, Any]:
        """Сводка для админки: игроки, активные сегодня, средняя точность."""
        today = today_iso()
        async with self.db.execute("SELECT COUNT(*) AS c FROM users") as cur:
            total = int((await cur.fetchone())["c"])
        async with self.db.execute(
            "SELECT COUNT(*) AS c FROM users WHERE last_quest_day = ?", (today,)
        ) as cur:
            active = int((await cur.fetchone())["c"])
        async with self.db.execute(
            "SELECT AVG(1.0 * correct / quests_done) AS a FROM users"
            " WHERE quests_done > 0"
        ) as cur:
            row = await cur.fetchone()
        accuracy = row["a"] if row and row["a"] is not None else 0.0
        async with self.db.execute(
            "SELECT COUNT(*) AS c FROM quests WHERE status = 'done'"
        ) as cur:
            done_total = int((await cur.fetchone())["c"])
        return {
            "total": total,
            "active_today": active,
            "accuracy": round(100 * float(accuracy)),
            "quests_done": done_total,
        }

    async def reset_streak(self, tg_id: int) -> bool:
        """Сбросить серию игрока (для починки)."""
        cur = await self.db.execute(
            "UPDATE users SET streak = 0, last_quest_day = '' WHERE tg_id = ?",
            (tg_id,),
        )
        await self.db.commit()
        return bool(cur.rowcount)

    async def add_points_admin(self, tg_id: int, delta: int) -> bool:
        """Начислить или списать очки игроку."""
        cur = await self.db.execute(
            "UPDATE users SET points = MAX(0, points + ?) WHERE tg_id = ?",
            (delta, tg_id),
        )
        await self.db.commit()
        return bool(cur.rowcount)

    async def vacuum_old(self, days: int = 90) -> dict[str, int]:
        """Вычистить старые записи. Возвращает, сколько чего удалено."""
        cutoff = time.time() - days * 86400
        result: dict[str, int] = {}

        cur = await self.db.execute(
            "DELETE FROM quests WHERE status != 'active' AND started_at < ?",
            (cutoff,),
        )
        result["quests"] = cur.rowcount or 0

        cur = await self.db.execute(
            "DELETE FROM pvp_matches WHERE created_at < ?", (cutoff,)
        )
        result["pvp"] = cur.rowcount or 0

        cur = await self.db.execute(
            "DELETE FROM messages WHERE created_at < ?", (cutoff,)
        )
        result["messages"] = cur.rowcount or 0

        await self.db.commit()
        return result

    # ------------------------------------------------------------------
    # сообщения (для очистки чата)
    # ------------------------------------------------------------------
    async def track_message(
        self, chat_id: int, message_id: int, kind: str = "quest"
    ) -> None:
        """Запомнить сообщение, чтобы потом удалить его из чата.

        kind: 'quest'/'auto' - сообщения бота, 'user' - сообщения игрока.
        """
        await self.db.execute(
            "INSERT INTO messages (chat_id, message_id, kind, created_at)"
            " VALUES (?, ?, ?, ?)",
            (chat_id, message_id, kind, time.time()),
        )
        await self.db.commit()

    async def chat_messages(self, chat_id: int, limit: int = 50) -> list[int]:
        """id сообщений бота в чате, от новых к старым."""
        async with self.db.execute(
            "SELECT message_id FROM messages WHERE chat_id = ?"
            " ORDER BY id DESC LIMIT ?",
            (chat_id, limit),
        ) as cur:
            rows = await cur.fetchall()
        return [int(row["message_id"]) for row in rows]

    async def forget_messages(self, chat_id: int, message_ids: list[int]) -> None:
        """Забыть сообщения (после удаления или когда их уже нельзя удалить)."""
        if not message_ids:
            return
        placeholders = ",".join("?" for _ in message_ids)
        await self.db.execute(
            f"DELETE FROM messages WHERE chat_id = ? AND message_id IN ({placeholders})",
            (chat_id, *message_ids),
        )
        await self.db.commit()

    # ------------------------------------------------------------------
    # метрики здоровья
    # ------------------------------------------------------------------
    async def set_meta(self, key: str, value: str) -> None:
        await self.db.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )
        await self.db.commit()

    async def get_meta(self, key: str, default: str = "") -> str:
        async with self.db.execute(
            "SELECT value FROM meta WHERE key = ?", (key,)
        ) as cur:
            row = await cur.fetchone()
        return row["value"] if row else default

    async def count_error(self, window_seconds: float = 3600.0) -> int:
        """Посчитать ошибку в текущем окне (по умолчанию - час).

        Окно сбрасывается, когда прошло больше window_seconds с начала.
        Так счётчик всегда отражает свежие проблемы, а не историю.
        """
        import time as _time

        now = _time.time()
        start = float(await self.get_meta("errors_window_start", "0") or 0)
        count = int(await self.get_meta("errors_count", "0") or 0)

        if not start or (now - start) > window_seconds:
            start = now
            count = 0

        count += 1
        await self.set_meta("errors_window_start", str(start))
        await self.set_meta("errors_count", str(count))
        await self.set_meta("errors_last_at", str(now))
        return count

    # ------------------------------------------------------------------
    # PvP
    # ------------------------------------------------------------------
    async def create_pvp_match(
        self,
        player1: int,
        game_type: str,
        difficulty: str,
        payload: dict[str, Any],
        code: str,
    ) -> int:
        cur = await self.db.execute(
            "INSERT INTO pvp_matches (code, player1, game_type, difficulty,"
            " payload, status, points1, points2, created_at)"
            " VALUES (?, ?, ?, ?, ?, 'waiting', -1, -1, ?)",
            (code, player1, game_type, difficulty,
             json.dumps(payload, ensure_ascii=False), time.time()),
        )
        await self.db.commit()
        return int(cur.lastrowid)

    async def count_open_challenges(self, tg_id: int, max_age: float = 3600.0) -> int:
        """Сколько у игрока свежих непринятых вызовов."""
        async with self.db.execute(
            "SELECT COUNT(*) AS c FROM pvp_matches"
            " WHERE player1 = ? AND status = 'waiting' AND created_at > ?",
            (tg_id, time.time() - max_age),
        ) as cur:
            row = await cur.fetchone()
        return int(row["c"]) if row else 0

    async def expire_stale_challenges(self, max_age: float = 86400.0) -> int:
        """Закрыть вызовы, которые так и не приняли.

        Иначе в базе копится мусор: вызов можно было бы принять и через
        месяц, и таких вызовов накапливаются десятки.
        """
        cur = await self.db.execute(
            "UPDATE pvp_matches SET status = 'expired'"
            " WHERE status = 'waiting' AND created_at < ?",
            (time.time() - max_age,),
        )
        await self.db.commit()
        return cur.rowcount or 0

    async def get_pvp_match(self, match_id: int) -> Optional[aiosqlite.Row]:
        async with self.db.execute(
            "SELECT * FROM pvp_matches WHERE id = ?", (match_id,)
        ) as cur:
            return await cur.fetchone()

    async def get_pvp_by_code(self, code: str) -> Optional[aiosqlite.Row]:
        async with self.db.execute(
            "SELECT * FROM pvp_matches WHERE code = ?", (code,)
        ) as cur:
            return await cur.fetchone()

    async def accept_pvp(self, match_id: int, player2: int) -> None:
        await self.db.execute(
            "UPDATE pvp_matches SET player2 = ?, status = 'active' WHERE id = ?",
            (player2, match_id),
        )
        await self.db.commit()

    async def finish_pvp(
        self, match_id: int, player: int, points: int
    ) -> Optional[aiosqlite.Row]:
        """Записать результат игрока. Возвращает матч, если он завершён."""
        match = await self.get_pvp_match(match_id)
        if match is None:
            return None

        if player == match["player1"]:
            await self.db.execute(
                "UPDATE pvp_matches SET points1 = ? WHERE id = ?", (points, match_id)
            )
        else:
            await self.db.execute(
                "UPDATE pvp_matches SET points2 = ? WHERE id = ?", (points, match_id)
            )
        await self.db.commit()

        match = await self.get_pvp_match(match_id)
        if match is None or match["points1"] < 0 or match["points2"] < 0:
            return None

        p1, p2 = match["points1"], match["points2"]
        winner = 0
        if p1 > p2:
            winner = match["player1"]
        elif p2 > p1:
            winner = match["player2"]

        await self.db.execute(
            "UPDATE pvp_matches SET winner = ?, status = 'finished', finished_at = ?"
            " WHERE id = ?",
            (winner, time.time(), match_id),
        )
        if winner:
            loser = match["player2"] if winner == match["player1"] else match["player1"]
            await self.db.execute(
                "UPDATE users SET pvp_wins = pvp_wins + 1,"
                " pvp_points = pvp_points + ? WHERE tg_id = ?",
                (max(p1, p2), winner),
            )
            await self.db.execute(
                "UPDATE users SET pvp_losses = pvp_losses + 1 WHERE tg_id = ?",
                (loser,),
            )
        else:
            for pid in (match["player1"], match["player2"]):
                await self.db.execute(
                    "UPDATE users SET pvp_points = pvp_points + ? WHERE tg_id = ?",
                    (max(p1, p2), pid),
                )
        await self.db.commit()
        return await self.get_pvp_match(match_id)

    async def pvp_rating(self, limit: int = 10) -> list[aiosqlite.Row]:
        """Рейтинг PvP: победы, поражения, очки."""
        async with self.db.execute(
            "SELECT tg_id, nickname, username, display_name, pvp_wins, pvp_losses,"
            " pvp_points FROM users"
            " WHERE pvp_wins > 0 OR pvp_losses > 0"
            " ORDER BY pvp_wins DESC, pvp_points DESC, pvp_losses ASC LIMIT ?",
            (limit,),
        ) as cur:
            return list(await cur.fetchall())

    # ------------------------------------------------------------------
    # адаптивная сложность
    # ------------------------------------------------------------------
    async def recent_results(self, tg_id: int, limit: int = 6) -> list[aiosqlite.Row]:
        """Последние завершённые квесты игрока."""
        async with self.db.execute(
            "SELECT status, points, difficulty, risky FROM quests"
            " WHERE tg_id = ? AND status IN ('done', 'failed')"
            " ORDER BY id DESC LIMIT ?",
            (tg_id, limit),
        ) as cur:
            return list(await cur.fetchall())

    async def notify_enabled(self, tg_id: int) -> bool:
        user = await self.get_user(tg_id)
        if user is None:
            return True
        return bool(user["notify"])

    async def set_notify(self, tg_id: int, enabled: bool) -> None:
        await self.db.execute(
            "UPDATE users SET notify = ? WHERE tg_id = ?",
            (1 if enabled else 0, tg_id),
        )
        await self.db.commit()

    # ------------------------------------------------------------------
    # рейтинг
    # ------------------------------------------------------------------
    async def leaderboard(self, scope: str = "all", limit: int = 10) -> list[aiosqlite.Row]:
        """Таблица лидеров по разным срезам.

        all / today / week  - очки
        quests / quests_today - количество пройденных квестов
        pvp - победы в PvP
        """
        if scope == "today":
            return await self._points_board(today_iso(), limit)
        if scope == "week":
            return await self._points_board(week_start_iso(), limit)
        if scope == "quests":
            return await self._quests_board(None, limit)
        if scope == "quests_today":
            return await self._quests_board(today_iso(), limit)
        if scope == "pvp":
            return await self._pvp_board(limit)
        return await self._points_board(None, limit, total=True)

    async def _points_board(
        self, day: Optional[str], limit: int, total: bool = False
    ) -> list[aiosqlite.Row]:
        if total:
            # общий зачёт: считаем накопленные очки игрока
            sql = """
                SELECT u.tg_id, u.nickname, u.username, u.display_name,
                       u.points AS scope_points, u.points AS total_points
                  FROM users u
                 WHERE u.points > 0
                ORDER BY u.points DESC, u.quests_done ASC
                 LIMIT ?
            """
            async with self.db.execute(sql, (limit,)) as cur:
                return list(await cur.fetchall())

        where = "1 = 1"
        params: tuple[Any, ...] = ()
        if day is not None:
            where = "q.day = ?"
            params = (day,)
        sql = f"""
            SELECT u.tg_id, u.nickname, u.username, u.display_name,
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

    async def _quests_board(
        self, day: Optional[str], limit: int
    ) -> list[aiosqlite.Row]:
        where = "1 = 1"
        params: tuple[Any, ...] = ()
        if day is not None:
            where = "q.day = ?"
            params = (day,)
        sql = f"""
            SELECT u.tg_id, u.nickname, u.username, u.display_name,
                   COUNT(q.id) AS scope_points,
                   COALESCE(SUM(q.points), 0) AS total_points
              FROM users u
              LEFT JOIN quests q
                     ON q.tg_id = u.tg_id AND q.status = 'done' AND {where}
             GROUP BY u.tg_id
            HAVING scope_points > 0
            ORDER BY scope_points DESC, total_points DESC
             LIMIT ?
        """
        async with self.db.execute(sql, (*params, limit)) as cur:
            return list(await cur.fetchall())

    async def _pvp_board(self, limit: int) -> list[aiosqlite.Row]:
        sql = """
            SELECT u.tg_id, u.nickname, u.username, u.display_name,
                   u.pvp_wins AS scope_points,
                   u.pvp_losses AS pvp_losses,
                   u.pvp_points AS total_points
              FROM users u
             WHERE u.pvp_wins > 0 OR u.pvp_losses > 0
            ORDER BY u.pvp_wins DESC, u.pvp_points DESC, u.pvp_losses ASC
             LIMIT ?
        """
        async with self.db.execute(sql, (limit,)) as cur:
            return list(await cur.fetchall())

    async def user_position(self, tg_id: int, scope: str = "all") -> Optional[int]:
        """Место игрока в рейтинге (1-based) либо None, если его нет."""
        rows = await self.leaderboard(scope=scope, limit=1000)
        for index, row in enumerate(rows, start=1):
            if row["tg_id"] == tg_id:
                return index
        return None


db = Database(DB_PATH)

"""Квесты: выдача, ротатор, итоги."""

from __future__ import annotations

import time
import json
import aiosqlite
from typing import Any
from typing import Optional

class QuestsMixin:
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

    async def get_active_quest(
        self, tg_id: int, pvp: Optional[bool] = None
    ) -> Optional[aiosqlite.Row]:
        """Последний незавершённый квест игрока.

        ``pvp`` - фильтр по типу: True только матч, False только дневной,
        None любой. Нужен, потому что матч PvP и дневной квест могут
        висеть одновременно, и один не должен прятать другой.
        """
        sql = "SELECT * FROM quests WHERE tg_id = ? AND status = 'active'"
        params: tuple[Any, ...] = (tg_id,)
        if pvp is not None:
            sql += " AND (pvp_id > 0) = ?"
            params = (tg_id, 1 if pvp else 0)
        sql += " ORDER BY id DESC LIMIT 1"
        async with self.db.execute(sql, params) as cur:
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

    async def recent_results(self, tg_id: int, limit: int = 6) -> list[aiosqlite.Row]:
        """Последние завершённые квесты игрока."""
        async with self.db.execute(
            "SELECT status, points, difficulty, risky FROM quests"
            " WHERE tg_id = ? AND status IN ('done', 'failed')"
            " ORDER BY id DESC LIMIT ?",
            (tg_id, limit),
        ) as cur:
            return list(await cur.fetchall())

    async def game_type_stats(
        self, tg_id: int, min_games: int = 3
    ) -> dict[str, dict[str, int]]:
        """По каждому типу игры: сколько пройдено и сколько провалено.

        Нужно, чтобы не выдавать игроку игру, в которой он стабильно
        проигрывает: если «Хронология» заканчивается провалом три раза
        подряд, она ему не подходит.

        ``min_games`` - сколько попыток нужно, чтобы судить о типе
        игры. Пока их меньше, вывод делать рано.
        """
        async with self.db.execute(
            "SELECT game_type,"
            " SUM(status = 'done')   AS ok,"
            " SUM(status = 'failed') AS fail"
            " FROM quests WHERE tg_id = ? AND status IN ('done', 'failed')"
            " GROUP BY game_type",
            (tg_id,),
        ) as cur:
            rows = list(await cur.fetchall())

        stats: dict[str, dict[str, int]] = {}
        for row in rows:
            ok = int(row["ok"] or 0)
            fail = int(row["fail"] or 0)
            if ok + fail < min_games:
                continue
            stats[str(row["game_type"])] = {"ok": ok, "fail": fail}
        return stats

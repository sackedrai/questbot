"""Таблицы лидеров."""

from __future__ import annotations

from .helpers import today_iso
from .helpers import week_start_iso
import aiosqlite
from typing import Any
from typing import Optional

class LeaderboardMixin:
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

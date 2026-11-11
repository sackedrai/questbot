"""Матчи PvP: вызовы, принятие, результаты."""

from __future__ import annotations

import time
import json
import aiosqlite
from typing import Any
from typing import Optional

class PvpMixin:
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

    async def pvp_history(
        self, tg_id: int, limit: int = 10
    ) -> list[aiosqlite.Row]:
        """Последние матчи игрока (сыгранные).

        Нужно для экрана «история боёв»: с кем играл и с каким счётом.
        Возвращает матчи, где игрок был первым или вторым.
        """
        async with self.db.execute(
            "SELECT * FROM pvp_matches"
            " WHERE (player1 = ? OR player2 = ?) AND status = 'finished'"
            " ORDER BY id DESC LIMIT ?",
            (tg_id, tg_id, limit),
        ) as cur:
            return list(await cur.fetchall())

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

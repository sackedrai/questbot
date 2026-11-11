"""Достижения игрока."""

from __future__ import annotations

import time

class AchievementsMixin:
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

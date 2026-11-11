"""Сводки для админки: статистика, воронка, уборка."""

from __future__ import annotations

from .helpers import today_iso
from .helpers import week_start_iso
import time
import aiosqlite
from typing import Any

class AdminMixin:
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

    async def week_summary(self, tg_id: int) -> dict[str, int]:
        """Итоги игрока за текущую неделю.

        Нужны для еженедельной сводки: сколько квестов, сколько очков
        и какая точность.
        """
        start = week_start_iso()
        async with self.db.execute(
            "SELECT COUNT(*) AS total,"
            " COALESCE(SUM(CASE WHEN status = 'done'   THEN 1 END), 0) AS done,"
            " COALESCE(SUM(CASE WHEN status = 'failed' THEN 1 END), 0) AS failed,"
            " COALESCE(SUM(CASE WHEN status = 'done'   THEN points END), 0) AS points"
            " FROM quests WHERE tg_id = ? AND day >= ? AND status IN ('done','failed')",
            (tg_id, start),
        ) as cur:
            row = await cur.fetchone()
        total = int(row["total"] or 0)
        done = int(row["done"] or 0)
        accuracy = round(100 * done / total) if total else 0
        return {
            "total": total,
            "done": done,
            "failed": int(row["failed"] or 0),
            "points": int(row["points"] or 0),
            "accuracy": accuracy,
        }

    async def chasing_players(self, tg_id: int, limit: int = 3) -> list[aiosqlite.Row]:
        """Кто впереди игрока по общему счёту - самые близкие.

        Нужно для подсказки «ты отстал»: игроку показывают того, кого
        он может догнать за пару квестов.
        """
        user = await self.get_user(tg_id)
        my_points = int(user["points"]) if user else 0
        async with self.db.execute(
            "SELECT tg_id, nickname, points, quests_done FROM users"
            " WHERE points > ? AND nickname != ''"
            " ORDER BY points ASC, quests_done ASC LIMIT ?",
            (my_points, limit),
        ) as cur:
            return list(await cur.fetchall())

    async def funnel_stats(self) -> dict[str, int]:
        """Воронка игроков: от регистрации до недельной игры.

        Показывает, где игроки отваливаются: зарегистрировались, но не
        играли / играли один день / играют вторую неделю / забили.
        """
        today = today_iso()
        week = week_start_iso()
        async with self.db.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM users) AS registered,
              (SELECT COUNT(*) FROM users WHERE quests_done > 0) AS played,
              (SELECT COUNT(*) FROM users WHERE quests_done >= 2) AS played_twice,
              (SELECT COUNT(*) FROM users WHERE quests_done >= 7) AS played_week,
              (SELECT COUNT(*) FROM users WHERE quests_done > 0
                 AND last_quest_day < ?) AS churned
            """,
            (week,),
        ) as cur:
            row = await cur.fetchone()
        return {
            "registered": int(row["registered"] or 0),
            "played": int(row["played"] or 0),
            "played_twice": int(row["played_twice"] or 0),
            "played_week": int(row["played_week"] or 0),
            "churned": int(row["churned"] or 0),
            "active_today": await self._count_active_today(today),
        }

    async def _count_active_today(self, today: str) -> int:
        async with self.db.execute(
            "SELECT COUNT(*) AS c FROM users WHERE last_quest_day = ?", (today,)
        ) as cur:
            row = await cur.fetchone()
        return int(row["c"] or 0)

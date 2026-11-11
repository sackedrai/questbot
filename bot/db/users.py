"""Игроки: профиль, серия, очки, уведомления."""

from __future__ import annotations

from datetime import date, timedelta
import time
import aiosqlite
from typing import Optional

class UsersMixin:
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

    async def lock_difficulty(self, tg_id: int, difficulty: str = "easy") -> None:
        """Зафиксировать сложность игроку (сброс адаптивной подборки)."""
        await self.db.execute(
            "INSERT INTO users (tg_id, adaptive_locked, locked_difficulty, created_at) "
            "VALUES (?, 1, ?, ?)"
            " ON CONFLICT(tg_id) DO UPDATE SET "
            "adaptive_locked = 1, locked_difficulty = excluded.locked_difficulty",
            (tg_id, difficulty, time.time()),
        )
        await self.db.commit()

    async def unlock_difficulty(self, tg_id: int) -> None:
        """Вернуть автоматический подбор сложности."""
        await self.db.execute(
            "INSERT INTO users (tg_id, adaptive_locked, locked_difficulty, created_at) "
            "VALUES (?, 0, 'easy', ?)"
            " ON CONFLICT(tg_id) DO UPDATE SET "
            "adaptive_locked = 0, locked_difficulty = 'easy'",
            (tg_id, time.time()),
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
        from ..config import STREAK_FREE_COOLDOWN_DAYS

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
        from ..config import STREAK_FREE_COOLDOWN_DAYS

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

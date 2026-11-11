"""Вопросы игроков и модерация."""

from __future__ import annotations

import time
import json
import aiosqlite
from typing import Any
from typing import Optional

class UserQuestionsMixin:
    async def add_user_question(
        self,
        tg_id: int,
        question: str,
        answer: str,
        options: list[str] | None,
        category: str,
        difficulty: str,
    ) -> int:
        """Добавить вопрос игрока на модерацию."""
        cur = await self.db.execute(
            """
            INSERT INTO user_questions
                (tg_id, question, answer, options, category, difficulty,
                 status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
            """,
            (
                tg_id,
                question.strip(),
                answer.strip(),
                json.dumps(options or [], ensure_ascii=False),
                category.strip(),
                difficulty,
                time.time(),
            ),
        )
        await self.db.commit()
        return int(cur.lastrowid)

    async def get_user_questions(
        self, tg_id: int, limit: int = 50
    ) -> list[aiosqlite.Row]:
        """Все вопросы игрока (свои), свежие сверху."""
        async with self.db.execute(
            "SELECT * FROM user_questions WHERE tg_id = ?"
            " ORDER BY created_at DESC LIMIT ?",
            (tg_id, limit),
        ) as cur:
            return list(await cur.fetchall())

    async def get_user_question(
        self, question_id: int
    ) -> Optional[aiosqlite.Row]:
        """Один вопрос по id (для карточки модерации)."""
        async with self.db.execute(
            "SELECT * FROM user_questions WHERE id = ?", (question_id,)
        ) as cur:
            return await cur.fetchone()

    async def get_pending_questions(
        self, limit: int = 50
    ) -> list[aiosqlite.Row]:
        """Вопросы на модерации (для админа), старые сверху."""
        async with self.db.execute(
            "SELECT * FROM user_questions WHERE status = 'pending'"
            " ORDER BY created_at ASC LIMIT ?",
            (limit,),
        ) as cur:
            return list(await cur.fetchall())

    async def approve_question(self, question_id: int, approved_by: int) -> bool:
        """Одобрить вопрос на модерации."""
        cur = await self.db.execute(
            "UPDATE user_questions SET status = 'approved',"
            " approved_at = ?, approved_by = ? WHERE id = ? AND status = 'pending'",
            (time.time(), approved_by, question_id),
        )
        await self.db.commit()
        return bool(cur.rowcount)

    async def reject_question(self, question_id: int, approved_by: int) -> bool:
        """Отклонить вопрос на модерации."""
        cur = await self.db.execute(
            "UPDATE user_questions SET status = 'rejected',"
            " approved_at = ?, approved_by = ? WHERE id = ? AND status = 'pending'",
            (time.time(), approved_by, question_id),
        )
        await self.db.commit()
        return bool(cur.rowcount)

    async def get_approved_questions(
        self, limit: int = 200
    ) -> list[aiosqlite.Row]:
        """Одобренные вопросы игроков для выдачи в игру."""
        async with self.db.execute(
            "SELECT * FROM user_questions WHERE status = 'approved'"
            " ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ) as cur:
            return list(await cur.fetchall())

    async def count_user_questions(
        self, tg_id: int, status: Optional[str] = None
    ) -> int:
        """Сколько вопросов отправил игрок (можно считать по статусу)."""
        sql = "SELECT COUNT(*) AS c FROM user_questions WHERE tg_id = ?"
        params: tuple[Any, ...] = (tg_id,)
        if status:
            sql += " AND status = ?"
            params = (tg_id, status)
        async with self.db.execute(sql, params) as cur:
            row = await cur.fetchone()
        return int(row["c"]) if row else 0

    async def count_approved_questions(self) -> int:
        """Сколько вопросов игроков уже в игре."""
        async with self.db.execute(
            "SELECT COUNT(*) AS c FROM user_questions WHERE status = 'approved'"
        ) as cur:
            row = await cur.fetchone()
        return int(row["c"]) if row else 0

    async def question_stats(self, tg_id: int) -> dict[str, int]:
        """Сводка по вопросам одного игрока одним запросом."""
        async with self.db.execute(
            "SELECT COUNT(*) AS total,"
            " COALESCE(SUM(status = 'pending'), 0) AS pending,"
            " COALESCE(SUM(status = 'approved'), 0) AS approved,"
            " COALESCE(SUM(status = 'rejected'), 0) AS rejected"
            " FROM user_questions WHERE tg_id = ?",
            (tg_id,),
        ) as cur:
            row = await cur.fetchone()
        keys = ("total", "pending", "approved", "rejected")
        return {key: int(row[key] or 0) for key in keys} if row else {
            key: 0 for key in keys
        }

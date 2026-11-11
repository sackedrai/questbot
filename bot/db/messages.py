"""Сообщения чата - нужны для автоочистки."""

from __future__ import annotations

import time

class MessagesMixin:
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

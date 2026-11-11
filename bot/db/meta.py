"""Метрики бота в таблице meta."""

from __future__ import annotations


class MetaMixin:
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

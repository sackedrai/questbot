"""Подключение к базе: открыть, применить миграции, закрыть."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import aiosqlite

from .schema import MIGRATIONS, SCHEMA


class DatabaseBase:
    """Открытие соединения и миграции схемы."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._db: Optional[aiosqlite.Connection] = None

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
            raise RuntimeError(
                "База данных не подключена, вызовите connect()"
            )
        return self._db

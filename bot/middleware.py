"""Middleware: считаем ошибки в обработчиках.

Если обработчик падает - это сигнал, что бот жив, но сломан. Сторож
смотрит на счётчик и сообщает владельцу.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware

from .db import db

log = logging.getLogger(__name__)

# Ошибки в одном окне (час), после которых сторож начинает тревожить
ERROR_THRESHOLD = 5
ERROR_WINDOW = 3600.0


class ErrorCounterMiddleware(BaseMiddleware):
    """Считает исключения из обработчиков."""

    async def __call__(
        self,
        handler: Callable[[Any, Dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: Dict[str, Any],
    ) -> Any:
        try:
            return await handler(event, data)
        except Exception as exc:
            try:
                count = await db.count_error(ERROR_WINDOW)
                log.warning(
                    "Ошибка в обработчике (в окне: %s): %r", count, exc
                )
            except Exception:  # noqa: BLE001 - счётчик не должен ломать бота
                log.exception("Не удалось посчитать ошибку")
            raise

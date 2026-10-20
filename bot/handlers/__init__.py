"""Сборка роутеров.

Порядок важен: игровые хендлеры идут первыми, чтобы текстовый ответ
в активном квесте не перехватывался другими хендлерами.
"""

from __future__ import annotations

from aiogram import Router

from . import common, games, profile, quests, ranking

router = Router()
router.include_router(games.router)
router.include_router(common.router)
router.include_router(quests.router)
router.include_router(profile.router)
router.include_router(ranking.router)

__all__ = ["router"]

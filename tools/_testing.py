"""Общие помощники для тестов.

Лежат здесь, чтобы наборы не дублировались: заглушки, счётчик проверок и
главное - подмена базы во всех модулях сразу.

Почему это важно: модули пакета bot держат собственную ссылку на базу
(`from .db import db`), и раньше каждый тест подставлял её руками, списоком
из полутора модулей. Забыть один - и тест падает с «База данных не
подключена». Теперь список не нужен: `patch_db` находит модули сам.
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import Any, Optional


class Tally:
    """Счётчик проверок с выводом."""

    def __init__(self) -> None:
        self.passed = 0
        self.failed = 0
        self.failures: list[str] = []

    def check(self, condition: bool, label: str) -> None:
        if condition:
            self.passed += 1
            print(f"  ok   {label}")
        else:
            self.failed += 1
            self.failures.append(label)
            print(f"  FAIL {label}")

    def section(self, title: str) -> None:
        print(f"\n{title}")
        print("-" * len(title))

    def summary(self) -> str:
        return f"  Пройдено: {self.passed}   Провалено: {self.failed}"


def patch_db(db: Any) -> list[str]:
    """Подставить базу во все модули пакета bot, которые её держат.

    Модули находятся по факту наличия атрибута `db`, поэтому новые
    подхватываются сами и забыть какой-нибудь невозможно.

    Возвращает список подменённых модулей - удобно для проверки в тесте.
    """
    import bot

    patched: list[str] = []
    for info in pkgutil.walk_packages(bot.__path__, prefix="bot."):
        if info.name == "bot.__main__":
            continue  # с побочными эффектами при импорте
        try:
            module = importlib.import_module(info.name)
        except Exception:  # noqa: BLE001 - модуль может тянуть что-то тяжёлое
            continue
        if hasattr(module, "db"):
            module.db = db
            patched.append(info.name)
    return patched


# ----------------------------------------------------------------------
# заглушки
# ----------------------------------------------------------------------
class FakeUser:
    def __init__(
        self,
        tg_id: int,
        username: str = "tester",
        full_name: str = "Тестер",
    ) -> None:
        self.id = tg_id
        self.username = username
        self.full_name = full_name


class FakeChat:
    def __init__(self, chat_id: int) -> None:
        self.id = chat_id
        self.type = "private"


class FakeBot:
    """Заглушка бота: умеет удалять сообщения и отправлять их."""

    def __init__(self) -> None:
        self.deleted: list[tuple[int, int]] = []
        self.deleted_chunks: list[tuple[int, list[int]]] = []
        self.sent: list[tuple[int, str]] = []

    async def delete_message(self, chat_id: int, message_id: int) -> None:
        self.deleted.append((chat_id, message_id))

    async def delete_messages(self, chat_id: int, message_ids: list[int]) -> None:
        self.deleted_chunks.append((chat_id, list(message_ids)))
        for message_id in message_ids:
            self.deleted.append((chat_id, message_id))

    async def send_message(self, chat_id: int, text: str, **kwargs) -> None:
        self.sent.append((chat_id, text))

    async def me(self):
        """Заглушка бота: его имя и id (для ссылок-приглашений)."""
        from types import SimpleNamespace

        return SimpleNamespace(username="questbot_bot", id=999)


class FakeMessage:
    """Заглушка сообщения: собирает всё, что бот в него отправил."""

    def __init__(
        self,
        text: str = "",
        user: Optional[FakeUser] = None,
        chat_id: int = 0,
        message_id: int = 1,
    ) -> None:
        self.text = text
        self.from_user = user
        self.chat = FakeChat(chat_id or (user.id if user else 0))
        self.message_id = message_id
        self.sent: list[tuple[str, object]] = []
        self.edited: list[tuple[str, object]] = []

    async def answer(self, text: str, reply_markup=None, **kwargs):
        self.sent.append((text, reply_markup))
        return self

    async def edit_text(self, text: str, reply_markup=None, **kwargs):
        self.edited.append((text, reply_markup))
        return self

    @property
    def last_text(self) -> str:
        if self.sent:
            return self.sent[-1][0]
        return self.edited[-1][0] if self.edited else ""


class FakeCallback:
    """Заглушка нажатия кнопки."""

    def __init__(self, data: str, user: FakeUser, message: FakeMessage) -> None:
        self.data = data
        self.from_user = user
        self.message = message
        self.answers: list[Optional[str]] = []

    async def answer(self, text: Optional[str] = None, show_alert: bool = False, **kwargs):
        self.answers.append(text)

"""Бэкап базы в git-репозиторий.

Кэш GitHub Actions - ненадёжное хранилище: записи вытесняются, кэш
привязан к репозиторию и ветке, и его не видно в git. Поэтому база
дополнительно коммитится в репозиторий - обычный git даёт надёжную
историю и возможность отката на любой коммит.

Репозиторий публичный (иначе не хватит бесплатных минут Actions), а
значит копия базы видна всем. Поэтому она **шифруется** ключом из
секретов репозитория (BACKUP_KEY): в репозитории лежит только
шифротекст, а рабочая копия в кэше остаётся обычной.

Как это работает:

* рабочая копия - ``data/questbot.db`` (восстанавливается из кэша);
* бэкап - ``backup/questbot.db.enc`` (шифротекст в git);
* восстановление при потере кэша происходит само: бот на старте видит, что
  рабочей базы нет, и расшифровывает бэкап из репозитория.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

BACKUP_DIR = "backup"
BACKUP_NAME = "questbot.db.enc"
PLAIN_NAME = "questbot.db"

# Как часто коммитить бэкап (часов)
BACKUP_INTERVAL_HOURS = 4.0


class BackupError(RuntimeError):
    """Не удалось сделать бэкап."""


def get_key() -> Optional[bytes]:
    """Ключ шифрования из секретов репозитория."""
    raw = os.getenv("BACKUP_KEY", "").strip()
    if not raw:
        return None
    return raw.encode("utf-8")


def _fernet(key: bytes):
    from cryptography.fernet import Fernet

    return Fernet(key)


def encrypt_file(source: Path, target: Path, key: bytes) -> None:
    """Зашифровать файл."""
    target.parent.mkdir(parents=True, exist_ok=True)
    token = _fernet(key).encrypt(source.read_bytes())
    target.write_bytes(token)


def decrypt_file(source: Path, target: Path, key: bytes) -> None:
    """Расшифровать файл."""
    target.parent.mkdir(parents=True, exist_ok=True)
    plain = _fernet(key).decrypt(source.read_bytes())
    target.write_bytes(plain)


async def _git(*args: str, cwd: Path, timeout: float = 60.0) -> tuple[int, str]:
    """Выполнить git-команду и вернуть (код, вывод).

    stdin закрываем: git не должен ждать ввода учётных данных - на
    раннере это привело бы к зависанию прогона.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=str(cwd),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except FileNotFoundError:
        return 1, "git не найден"

    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return 1, f"git {' '.join(args[:1])} завис - прервал"
    return proc.returncode or 0, out.decode("utf-8", "replace")


async def backup_database(
    repo_dir: Path,
    db_path: Path,
    min_hours: float = BACKUP_INTERVAL_HOURS,
) -> str:
    """Зашифровать базу и закоммитить её в репозиторий.

    Возвращает короткий статус: что именно произошло.
    """
    if not db_path.exists():
        return "базы нет - пропускаю"

    # путь базы должен быть внутри репозитория. Проверка мягкая: на раннере
    # Path.cwd() и Path.resolve() иногда расходятся (симлинки), а шифротекст
    # всё равно кладётся в repo_dir/backup - терять бэкап из-за этого нельзя.
    try:
        db_path.relative_to(repo_dir)
    except ValueError:
        if not str(db_path).startswith(str(repo_dir)):
            return "база вне репозитория - пропускаю"

    key = get_key()
    if key is None:
        return "нет ключа BACKUP_KEY - бэкап пропущен (данные публикуем не буду)"

    backup_dir = repo_dir / BACKUP_DIR
    backup_file = backup_dir / BACKUP_NAME

    # троттлинг: не чаще, чем раз в min_hours
    code, out = await _git(
        "log", "-1", "--format=%ct", "--", f"{BACKUP_DIR}/{BACKUP_NAME}",
        cwd=repo_dir,
    )
    last = int(out.strip()) if out.strip().isdigit() else 0
    if last and (time.time() - last) < min_hours * 3600:
        minutes = int((time.time() - last) // 60)
        return f"бэкап был {minutes} мин назад - пока не коммичу"

    # шифруем
    try:
        encrypt_file(db_path, backup_file, key)
    except Exception as exc:  # noqa: BLE001
        return f"не удалось зашифровать: {exc!r}"

    await _git("add", "--", f"{BACKUP_DIR}/{BACKUP_NAME}", cwd=repo_dir)
    # на раннере автора может не быть - задаём явно
    await _git(
        "config", "user.email", "questbot@users.noreply.github.com", cwd=repo_dir
    )
    await _git("config", "user.name", "QuestBot", cwd=repo_dir)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    code, out = await _git(
        "commit", "-m", f"backup: зашифрованная база игроков на {stamp}", cwd=repo_dir
    )
    if code != 0:
        if "nothing to commit" in out.lower():
            return "изменений для коммита нет"
        return f"коммит не удался: {out.strip()[:160]}"

    code, out = await _git("push", "origin", "HEAD", cwd=repo_dir)
    if code != 0:
        return f"закоммичено, но push не удался: {out.strip()[:160]}"
    return "бэкап запушен в репозиторий"


async def restore_from_repo(
    repo_dir: Path, db_path: Path
) -> str:
    """Расшифровать бэкап из репозитория, если рабочей базы нет."""
    backup_file = repo_dir / BACKUP_DIR / BACKUP_NAME
    if not backup_file.exists():
        return "бэкапа в репозитории нет"
    if db_path.exists() and db_path.stat().st_size > 0:
        return "рабочая база на месте - не трогаю"

    key = get_key()
    if key is None:
        return "нет ключа BACKUP_KEY - восстановить нечем"

    try:
        decrypt_file(backup_file, db_path, key)
    except Exception as exc:  # noqa: BLE001
        return f"не удалось расшифровать: {exc!r}"
    return "база восстановлена из репозитория"

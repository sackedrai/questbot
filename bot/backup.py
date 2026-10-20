"""Бэкап базы в git-репозиторий.

Кэш GitHub Actions ненадёжен: записи вытесняются, кэш привязан к
репозиторию и ветке, и его не видно в git. Поэтому база дополнительно
коммитится в репозиторий - обычный git даёт надёжную историю и
возможность отката на любой коммит.

Как это работает:

* рабочая копия - ``data/questbot.db`` (восстанавливается из кэша);
* бэкап - ``backup/questbot.db`` (лежит в git, коммитится автоматически);
* восстановление при потере кэша происходит само: шаг checkout кладёт
  последнюю закоммиченную копию, шаг в workflow подставляет её, если
  кэш оказался пустым.

Коммит делается не чаще, чем раз в ``min_hours`` часов - иначе история
репозитория распухает бинарными правками.
"""

from __future__ import annotations

import asyncio
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

BACKUP_DIR = "backup"
BACKUP_NAME = "questbot.db"


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


def _file_hash(path: Path) -> str:
    """Хеш файла - чтобы понять, менялась ли база.

    Через git status не проверить: рабочая база лежит в data/, а эта
    папка в .gitignore, и git её не отслеживает.
    """
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _has_players(path: Path) -> bool:
    """Есть ли в базе игроки.

    Нужна защита: если бот поднялся с пустой базой, коммит не должен
    затереть хорошую копию в репозитории.
    """
    import sqlite3

    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return True  # не SQLite - не наша забота
    try:
        row = conn.execute("SELECT COUNT(*) FROM users").fetchone()
        return bool(row and row[0])
    except sqlite3.Error:
        return True
    finally:
        conn.close()


async def backup_database(
    repo_dir: Path,
    db_path: Path,
    min_hours: float = 4.0,
) -> str:
    """Закоммитить базу в репозиторий, если она изменилась.

    Возвращает короткий статус: что именно произошло.
    """
    if not db_path.exists():
        return "базы нет - пропускаю"

    try:
        rel_db = db_path.relative_to(repo_dir)
    except ValueError:
        return "база вне репозитория - пропускаю"

    if not _has_players(db_path):
        return "в базе нет игроков - бэкап не делаю"

    backup_file = repo_dir / BACKUP_DIR / BACKUP_NAME
    if backup_file.exists() and _file_hash(backup_file) == _file_hash(db_path):
        return "база не менялась"

    # троттлинг: не чаще, чем раз в min_hours
    code, out = await _git(
        "log", "-1", "--format=%ct", "--", f"{BACKUP_DIR}/{BACKUP_NAME}",
        cwd=repo_dir,
    )
    last = int(out.strip()) if out.strip().isdigit() else 0
    if last and (time.time() - last) < min_hours * 3600:
        minutes = int((time.time() - last) // 60)
        return f"бэкап был {minutes} мин назад - пока не коммичу"

    # копия в отслеживаемую папку
    backup_dir = repo_dir / BACKUP_DIR
    backup_dir.mkdir(exist_ok=True)
    shutil.copy2(db_path, backup_file)

    await _git("add", "--", f"{BACKUP_DIR}/{BACKUP_NAME}", cwd=repo_dir)
    # на раннере автора может не быть - задаём явно
    await _git("config", "user.email", "questbot@users.noreply.github.com", cwd=repo_dir)
    await _git("config", "user.name", "QuestBot", cwd=repo_dir)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    code, out = await _git(
        "commit", "-m", f"backup: база игроков на {stamp}", cwd=repo_dir
    )
    if code != 0:
        if "nothing to commit" in out.lower():
            return "изменений для коммита нет"
        return f"коммит не удался: {out.strip()[:160]}"

    code, out = await _git("push", "origin", "HEAD", cwd=repo_dir)
    if code != 0:
        return f"закоммичено, но push не удался: {out.strip()[:160]}"
    return "бэкап запушен в репозиторий"


async def restore_from_repo(repo_dir: Path, db_path: Path) -> str:
    """Положить базу из репозитория, если рабочей копии нет."""
    backup = repo_dir / BACKUP_DIR / BACKUP_NAME
    if not backup.exists():
        return "бэкапа в репозитории нет"
    if db_path.exists() and db_path.stat().st_size > 0:
        return "рабочая база на месте - не трогаю"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(backup, db_path)
    return "база восстановлена из репозитория"

"""Определить репозиторий, не зашивая его имя в код.

Имя репозитория — часть личности владельца, поэтому оно нигде не
захардкожено: берётся из окружения (на раннере `GITHUB_REPOSITORY` всегда
задан) или из git-remote текущей папки.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path


def current_repo() -> str:
    """Вернуть репозиторий в формате 'владелец/имя' или пустую строку."""
    env = os.getenv("GITHUB_REPOSITORY", "").strip()
    if env:
        return env

    try:
        out = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            timeout=10,
            cwd=str(Path.cwd()),
        )
    except (OSError, subprocess.SubprocessError):
        return ""

    url = out.stdout.decode("utf-8", "replace").strip()
    if not url:
        return ""
    # https://github.com/owner/name.git  или  git@github.com:owner/name.git
    match = re.search(r"[:/]([^/:]+/[^/]+?)(?:\.git)?$", url)
    return match.group(1) if match else ""


def require_repo() -> str:
    """То же, но с понятной ошибкой вместо пустой строки."""
    repo = current_repo()
    if not repo:
        raise SystemExit(
            "Не удалось определить репозиторий.\n"
            "Задай переменную GITHUB_REPOSITORY=владелец/имя\n"
            "или добавь remote origin: git remote add origin <url>"
        )
    return repo

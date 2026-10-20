"""Полный деплой QuestBot в GitHub через gh CLI.

Делает всё сам:
  1) создаёт репозиторий (по умолчанию публичный - минуты Actions бесплатны)
  2) пушит код
  3) кладёт BOT_TOKEN в секреты репозитория
  4) включает workflow и запускает первый прогон

Запуск: python tools/deploy_github.py [имя-репозитория]
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # pragma: no cover
        pass

from dotenv import load_dotenv  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

def find_gh() -> Path:
    """Найти gh: сначала в PATH, потом в типовых местах."""
    found = shutil.which("gh")
    if found:
        return Path(found)
    candidates = [
        Path.home() / "AppData" / "Local" / "gh-cli" / "bin" / "gh.exe",
        Path.home() / "AppData" / "Local" / "Programs" / "GitHub CLI" / "gh.exe",
        Path("C:/Program Files/GitHub CLI/gh.exe"),
    ]
    for path in candidates:
        if path.exists():
            return path
    raise SystemExit("gh не найден. Установи GitHub CLI: https://cli.github.com")


GH = find_gh()

# Команды, которые belong gh (остальные - git)
GH_COMMANDS = {
    "auth", "api", "repo", "secret", "workflow", "run", "variable",
    "secret", "cache", "browse", "label", "release", "repo",
}


def run(args: list[str], *, capture: bool = False, stdin: str | None = None) -> str:
    """Запустить gh или git - в зависимости от команды."""
    executable = str(GH) if args and args[0] in GH_COMMANDS else "git"
    result = subprocess.run(
        [executable, *args],
        cwd=BASE_DIR,
        capture_output=capture,
        text=True,
        encoding="utf-8",
        errors="replace",
        input=stdin,
    )
    if capture:
        return (result.stdout or "") + (result.stderr or "")
    return result.returncode


def main() -> int:
    repo = sys.argv[1] if len(sys.argv) > 1 else "questbot"
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        print("BOT_TOKEN пуст в .env - нечего класть в секреты.")
        return 1

    print("=" * 60)
    print("  Деплой QuestBot в GitHub")
    print("=" * 60)

    login = run(["auth", "status"], capture=True)
    if "Logged in" not in login:
        print("gh не авторизован:\n", login[:400])
        return 1
    account = run(["api", "user", "--jq", ".login"], capture=True).strip()
    print(f"\n  Аккаунт: {account}")

    # 1. репозиторий
    exists = run(
        ["api", f"repos/{account}/{repo}", "--jq", ".full_name"], capture=True
    ).strip()
    if exists.startswith(account):
        print(f"  репозиторий {exists} уже есть")
    else:
        print(f"  создаю репозиторий {account}/{repo} (публичный)")
        run(["repo", "create", repo, "--public",
             "--source=.", "--remote=origin", "--push",
             "--description", "Ежедневные квесты с рейтингом друзей"])

    # 2. remote + push
    remotes = subprocess.run(
        ["git", "remote"], cwd=BASE_DIR, capture_output=True, text=True
    ).stdout
    if "origin" not in remotes:
        run(["remote", "add", "origin",
             f"https://github.com/{account}/{repo}.git"])
    print("  пушу код")
    push = subprocess.run(
        ["git", "push", "-u", "origin", "main"],
        cwd=BASE_DIR, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    if push.returncode != 0:
        print("  push не прошёл:\n ", (push.stderr or push.stdout)[:500])
        return 1
    print("  код запушен")

    # 3. секрет
    print("  кладу BOT_TOKEN в секреты репозитория")
    proc = subprocess.run(
        [str(GH), "secret", "set", "BOT_TOKEN", "--repo", f"{account}/{repo}"],
        cwd=BASE_DIR,
        input=token,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    if proc.returncode != 0:
        print("  не удалось:", (proc.stderr or "")[:300])
        return 1
    print("  секрет BOT_TOKEN установлен")

    # 4. workflow
    run(["workflow", "enable", "bot.yml", "--repo", f"{account}/{repo}"])
    print("  workflow bot.yml включён")

    print("\n  Открывай:")
    print(f"    https://github.com/{account}/{repo}/actions")
    print("  Первый прогон запустится по кнопке Run workflow или автоматически по крону.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

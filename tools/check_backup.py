"""Проверка, что бэкап базы лежит в репозитории.

Запуск: python tools/check_backup.py
"""

from __future__ import annotations

import json
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

REPO = "sackedrai/questbot"


def find_gh() -> str:
    found = shutil.which("gh")
    if found:
        return found
    for path in (
        Path.home() / "AppData" / "Local" / "gh-cli" / "bin" / "gh.exe",
        Path("C:/Program Files/GitHub CLI/gh.exe"),
    ):
        if path.exists():
            return str(path)
    raise SystemExit("gh не найден")


def main() -> int:
    gh = find_gh()
    result = subprocess.run(
        [gh, "api", f"repos/{REPO}/contents/backup"], capture_output=True
    )
    if result.returncode != 0:
        print("  бэкапа в репозитории нет")
        print("  ", result.stdout.decode("utf-8", "replace")[:200])
        return 1

    items = json.loads(result.stdout.decode("utf-8", "replace"))
    for item in items:
        print(f"  {item['name']}  {item['size']} байт  sha={item['sha'][:8]}")

    names = {item["name"] for item in items}
    problems = []
    if "questbot.db" in names:
        problems.append(
            "в репозитории лежит открытая база (questbot.db) - так быть не должно"
        )
    if "questbot.db.enc" not in names:
        problems.append("нет зашифрованного бэкапа (questbot.db.enc)")

    for problem in problems:
        print(f"  ВНИМАНИЕ: {problem}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

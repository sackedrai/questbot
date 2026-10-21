"""Прогнать все проверки проекта одной командой.

    python tools/check.py            # тесты + линтер
    python tools/check.py --preview  # ещё и превью экранов

Порядок: сначала линтер (быстро ловит опечатки), потом тесты.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable

SUITES = ("selftest", "flowtest", "routing_test", "polling_test")


def run(name: str, args: list[str]) -> int:
    print(f"\n{'=' * 56}\n  {name}\n{'=' * 56}")
    result = subprocess.run(args, cwd=str(ROOT))
    return result.returncode


def main() -> int:
    failed = False

    # 1. линтер
    if run("Линтер (ruff)", [PY, "-m", "ruff", "check", "bot/", "tools/"]) != 0:
        failed = True

    # 2. тесты
    for suite in SUITES:
        code = run(f"Тесты: {suite}", [PY, "-u", f"tools/{suite}.py"])
        if code != 0:
            failed = True

    # 3. превью экранов
    if "--preview" in sys.argv:
        if run("Превью экранов", [PY, "-u", "tools/preview.py"]) != 0:
            failed = True

    print(f"\n{'=' * 56}")
    if failed:
        print("  ЕСТЬ ОШИБКИ")
    else:
        print("  ВСЁ ЗЕЛЁНОЕ")
    print("=" * 56)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

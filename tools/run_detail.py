"""Подробный статус прогонов GitHub Actions (по id).

Запуск: python tools/run_detail.py <run_id> [<run_id> ...]
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

from tools._repo import current_repo  # noqa: E402

REPO = current_repo()


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


GH = find_gh()


def api(path: str) -> dict:
    result = subprocess.run([GH, "api", path], capture_output=True)
    try:
        return json.loads(result.stdout.decode("utf-8", "replace"))
    except ValueError:
        return {}


def main() -> int:
    ids = sys.argv[1:] or []
    if not ids:
        print("укажи id прогона")
        return 1

    for run_id in ids:
        run = api(f"repos/{REPO}/actions/runs/{run_id}")
        print(f"\nrun {run_id}: {run.get('status')}/{run.get('conclusion')} "
              f"создан {run.get('created_at')}")
        jobs = api(f"repos/{REPO}/actions/runs/{run_id}/jobs")
        for job in jobs.get("jobs", []):
            print(f"   job {job['id']} {job['name']}: "
                  f"{job['status']}/{job.get('conclusion')} "
                  f"начат {job.get('started_at')}")
            for step in job.get("steps", []):
                print(f"      {step['number']}. {step['name']:<28} "
                      f"{step['status']}/{step.get('conclusion')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

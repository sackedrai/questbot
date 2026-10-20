"""Статус прогонов GitHub Actions для QuestBot.

Запуск:
    python tools/ci_status.py            # последние прогоны
    python tools/ci_status.py --logs     # + логи последнего завершённого
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


GH = find_gh()


def gh(args: list[str]) -> str:
    result = subprocess.run(
        [GH, *args], capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    return result.stdout or result.stderr


def show_runs() -> list[dict]:
    data = json.loads(gh(["run", "list", "--repo", REPO, "--limit", "5", "--json",
                          "databaseId,status,conclusion,event,createdAt,displayTitle"]))
    print("=" * 70)
    print(f"  Прогоны {REPO}")
    print("=" * 70)
    for run in data:
        mark = {"completed": "✓" if run["conclusion"] == "success" else "✗",
                "in_progress": "»", "queued": "·"}.get(run["status"], "?")
        print(f"  {mark} #{run['databaseId']:<12} {run['status']:<11} "
              f"{str(run.get('conclusion')):<9} {run['event']:<18} {run['createdAt']}")
    return data


def show_steps(run_id: int) -> None:
    data = json.loads(gh(["api", f"repos/{REPO}/actions/runs/{run_id}/jobs"]))
    for job in data.get("jobs", []):
        print(f"\n  job: {job['name']}  [{job['status']}/{job.get('conclusion')}]")
        for step in job.get("steps", []):
            mark = "✓" if step["conclusion"] == "success" else (
                "»" if step["status"] == "in_progress" else "✗")
            print(f"    {mark} {step['number']}. {step['name']:<28} "
                  f"{step['status']}/{step.get('conclusion')}")


def show_logs(run_id: int) -> None:
    print("\n" + "=" * 70)
    print(f"  Логи прогона #{run_id}")
    print("=" * 70)
    print(gh(["run", "view", str(run_id), "--repo", REPO, "--log"]))


def main() -> int:
    runs = show_runs()
    if not runs:
        return 1
    latest = runs[0]["databaseId"]
    print(f"\n  Шаги последнего прогона #{latest}:")
    show_steps(latest)

    if "--logs" in sys.argv:
        show_logs(latest)
    return 0


if __name__ == "__main__":
    sys.exit(main())

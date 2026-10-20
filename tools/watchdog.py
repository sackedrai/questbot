"""Сторож за ботом.

Раз в ~20 минут проверяет, работает ли бот:

* был ли за последние часы успешный прогон бота;
* если нет - сам запускает новый прогон (это и есть автономность);
* если и после перезапуска бот не ожил - пишет владельцу в Telegram.

Писать в Telegram он может сам, минуя процесса бота: нужен только токен
и сеть. Поэтому уведомление дойдёт даже тогда, когда бот сломан.

Запуск (вручную): python tools/watchdog.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # pragma: no cover
        pass

from bot import style  # noqa: E402

GITHUB_API = "https://api.github.com"
TELEGRAM_API = "https://api.telegram.org"

DEFAULT_REPO = "sackedrai/questbot"
BOT_WORKFLOW = "bot.yml"

STATE_DIR = Path(".watchdog")
STATE_FILE = STATE_DIR / "state.json"

# Через сколько часов без успешного прогона считаем, что бот мёртв
STALE_HOURS = 3.0
# Сколько перезапусков подряд допускаем до алерта
MAX_RESTARTS = 3
# Как часто можно слать алерт (секунды)
ALERT_COOLDOWN = 6 * 3600

# Сколько ошибок в обработчиках за час считать аварией
ERROR_THRESHOLD = 5
# Как давно должна проходить самопроверка (секунды)
SELFCHECK_MAX_AGE = 4 * 3600


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


@dataclass
class State:
    """Состояние сторожа между запусками."""

    fails: int = 0
    last_alert: float = 0.0
    last_good_run: str = ""
    last_check: float = 0.0

    @classmethod
    def load(cls, path: Path = STATE_FILE) -> "State":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        return cls(
            fails=int(data.get("fails", 0)),
            last_alert=float(data.get("last_alert", 0)),
            last_good_run=str(data.get("last_good_run", "")),
            last_check=float(data.get("last_check", 0)),
        )

    def save(self, path: Path = STATE_FILE) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "fails": self.fails,
                    "last_alert": self.last_alert,
                    "last_good_run": self.last_good_run,
                    "last_check": self.last_check,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )


@dataclass
class Run:
    """Прогон workflow."""

    id: int
    status: str
    conclusion: str
    created_at: float
    event: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "completed" and self.conclusion == "success"


@dataclass
class Decision:
    """Что сторож решил делать."""

    action: str  # none | restart | alert
    reason: str = ""
    last_good: Optional[Run] = None
    should_alert: bool = False
    details: dict[str, Any] = field(default_factory=dict)


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def read_meta(db_path: Path) -> dict[str, str]:
    """Прочитать метрики здоровья из базы."""
    import sqlite3

    if not db_path.exists():
        return {}
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return {}
    try:
        rows = conn.execute("SELECT key, value FROM meta").fetchall()
        return {key: value for key, value in rows}
    except sqlite3.Error:
        return {}
    finally:
        conn.close()


def check_health(meta: dict[str, str], now: Optional[float] = None) -> list[str]:
    """Проблемы со здоровьем, которые перезапуск не исправит.

    Бот может быть жив (прогоны зелёные), но при этом сломанным:
    обработчики падают или он не отвечает. Вот это здесь и ловится.
    """
    now = now if now is not None else time.time()
    problems: list[str] = []

    count = int(meta.get("errors_count", "0") or 0)
    if count >= ERROR_THRESHOLD:
        problems.append(f"ошибок в обработчиках за последний час: {count}")

    last_selfcheck = float(meta.get("selfcheck_ok_at", "0") or 0)
    if last_selfcheck and (now - last_selfcheck) > SELFCHECK_MAX_AGE:
        hours = int((now - last_selfcheck) // 3600)
        problems.append(f"самопроверка не проходила {hours} ч")

    return problems


def fetch_runs(token: str, repo: str, workflow: str = BOT_WORKFLOW) -> list[Run]:
    """Последние прогоны workflow бота."""
    url = f"{GITHUB_API}/repos/{repo}/actions/workflows/{workflow}/runs?per_page=10"
    request = urllib.request.Request(url, headers=_headers(token))
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8", "replace"))
    runs = []
    for item in data.get("workflow_runs", []):
        started = _parse_time(item.get("run_started_at"))
        created = _parse_time(item.get("created_at"))
        runs.append(
            Run(
                id=int(item["id"]),
                status=item.get("status", ""),
                conclusion=item.get("conclusion") or "",
                created_at=started or created,
                event=item.get("event", ""),
            )
        )
    return runs


def _parse_time(value: Optional[str]) -> float:
    if not value:
        return 0.0
    from datetime import datetime

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def evaluate(
    runs: list[Run],
    state: State,
    now: Optional[float] = None,
    stale_hours: Optional[float] = None,
    max_restarts: Optional[int] = None,
) -> Decision:
    """Решить, что делать: ничего, перезапустить или alert."""
    now = now if now is not None else time.time()
    stale_hours = STALE_HOURS if stale_hours is None else stale_hours
    max_restarts = MAX_RESTARTS if max_restarts is None else max_restarts

    good = [run for run in runs if run.ok and run.created_at]
    last_good = max(good, key=lambda run: run.created_at) if good else None

    # идущий прогон - тоже признак того, что бот жив
    running = [
        run
        for run in runs
        if run.status == "in_progress"
        and run.created_at
        and (now - run.created_at) < stale_hours * 3600
    ]

    if last_good is not None:
        age_hours = (now - last_good.created_at) / 3600
        if age_hours <= stale_hours:
            return Decision(
                action="none",
                reason=f"последний успешный прогон {age_hours:.1f} ч назад",
                last_good=last_good,
            )
        reason = f"последний успешный прогон был {age_hours:.1f} ч назад"
    else:
        reason = "нет ни одного успешного прогона"

    if running:
        return Decision(
            action="none",
            reason="прогон бота сейчас идёт",
            last_good=last_good,
        )

    if state.fails < max_restarts:
        return Decision(action="restart", reason=reason, last_good=last_good)

    return Decision(
        action="alert",
        reason=reason,
        last_good=last_good,
        should_alert=(now - state.last_alert) > ALERT_COOLDOWN,
    )


def dispatch_run(token: str, repo: str, workflow: str = BOT_WORKFLOW) -> bool:
    """Запустить новый прогон workflow бота."""
    url = f"{GITHUB_API}/repos/{repo}/actions/workflows/{workflow}/dispatches"
    payload = json.dumps({"ref": "main"}).encode()
    request = urllib.request.Request(
        url, data=payload, method="POST", headers=_headers(token)
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status in (200, 201, 204)
    except urllib.error.HTTPError:
        return False
    except Exception:
        return False


def send_telegram(token: str, chat_id: str, text: str) -> bool:
    """Отправить сообщение в Telegram через Bot API (минуя процесс бота)."""
    url = f"{TELEGRAM_API}/bot{token}/sendMessage"
    payload = json.dumps(
        {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
    ).encode()
    request = urllib.request.Request(
        url, data=payload, method="POST", headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8", "replace")).get("ok", False)
    except urllib.error.HTTPError as exc:
        print(f"  Telegram отклонил сообщение: HTTP {exc.code}")
        return False
    except Exception as exc:
        print(f"  не удалось отправить в Telegram: {exc}")
        return False


def build_alert(
    decision: Decision, state: State, health: Optional[list[str]] = None
) -> str:
    """Текст уведомления."""
    when = time.strftime("%d.%m %H:%M", time.localtime())
    lines = [
        style.header("🚨", "БОТ НЕ РАБОТАЕТ"),
        "",
        style.note(decision.reason),
        style.note(f"Попыток перезапуска подряд: {state.fails}"),
    ]
    for problem in health or []:
        lines.append(style.note(f"• {problem}"))
    if decision.last_good:
        stamp = time.strftime("%d.%m %H:%M", time.localtime(decision.last_good.created_at))
        lines.append(style.note(f"Последний успешный прогон: {stamp}"))
    lines.append("")
    lines.append(style.note("Проверь логи: Actions → QuestBot → Logs"))
    lines.append(style.note(f"Время уведомления: {when}"))
    return "\n".join(lines)


def main() -> int:
    gh_token = os.getenv("GITHUB_TOKEN", "").strip()
    repo = os.getenv("GITHUB_REPOSITORY", DEFAULT_REPO).strip()
    admin = os.getenv("ADMIN_CHAT_ID", "").strip()
    bot_token = os.getenv("BOT_TOKEN", "").strip()

    if not gh_token:
        print("  нет GITHUB_TOKEN - сторож не может работать")
        return 1
    if not admin:
        print("  нет ADMIN_CHAT_ID - некому сообщать")
        return 1

    state = State.load()
    try:
        runs = fetch_runs(gh_token, repo)
    except Exception as exc:
        print(f"  не удалось получить прогоны: {exc}")
        return 1

    stale_hours = _env_float("WATCHDOG_STALE_HOURS", STALE_HOURS)
    max_restarts = _env_int("WATCHDOG_MAX_RESTARTS", MAX_RESTARTS)
    decision = evaluate(runs, state, stale_hours=stale_hours, max_restarts=max_restarts)
    state.last_check = time.time()

    print(f"  решение: {decision.action} ({decision.reason})")

    # здоровье обработчиков: перезапуск это не чинит, нужно звать человека
    meta = read_meta(Path(os.getenv("WATCHDOG_DB_PATH", "data/questbot.db")))
    health = check_health(meta)
    if health:
        print(f"  проблемы со здоровьем: {'; '.join(health)}")

    if decision.action == "none" and health:
        # бот жив, но сломан - тревожим, перезапуск не поможет
        if time.time() - state.last_alert > ALERT_COOLDOWN:
            if bot_token:
                sent = send_telegram(
                    bot_token, admin, build_alert(decision, state, health)
                )
                print(
                    f"  уведомление в Telegram: {'отправлено' if sent else 'НЕ отправлено'}"
                )
            state.last_alert = time.time()
            state.save()
            return 1
        print("  недавно тревожили - молчу")
        state.save()
        return 1

    if "--test-alert" in sys.argv:
        text = "\n".join(
            [
                style.header("🔔", "ТЕСТ УВЕДОМЛЕНИЯ"),
                "",
                style.note("Если ты видишь это сообщение - канал связи работает."),
                style.note("Сторож пришлёт сюда тревогу, если бот сломается."),
            ]
        )
        sent = send_telegram(bot_token, admin, text) if bot_token else False
        print(f"  тестовое уведомление: {'отправлено' if sent else 'НЕ отправлено'}")
        return 0 if sent else 1

    if decision.action == "none":
        state.fails = 0
        if decision.last_good:
            state.last_good_run = str(decision.last_good.id)
        state.save()
        return 0

    if decision.action == "restart":
        state.fails += 1
        ok = dispatch_run(gh_token, repo)
        print(f"  перезапуск: {'запущен' if ok else 'не удалось запустить'}")
        state.save()
        return 0

    # всё плохо: алертим
    if not decision.should_alert:
        print("  алерт уже был недавно, молчу")
        state.save()
        return 1

    if bot_token:
        sent = send_telegram(bot_token, admin, build_alert(decision, state))
        print(f"  уведомление в Telegram: {'отправлено' if sent else 'НЕ отправлено'}")
    state.last_alert = time.time()
    state.fails = 0
    state.save()
    return 1


if __name__ == "__main__":
    sys.exit(main())

"""Календарные помощники."""

from __future__ import annotations

from datetime import date, timedelta


def today_iso() -> str:
    return date.today().isoformat()


def week_start_iso() -> str:
    """Понедельник текущей недели."""
    today = date.today()
    return (today - timedelta(days=today.weekday())).isoformat()

"""Сетевой слой: как бот ходит в Telegram.

Бот сам находит рабочий канал: перебирает варианты, проверяет каждый
реальным запросом к Bot API и берёт первый доступный.

Приоритет:
1. ``API_BASE_URL`` — свой адрес Bot API (зеркало на Cloudflare Worker)
2. ``PROXY_URL``   — обычный HTTP/SOCKS5 прокси
3. прямое подключение к api.telegram.org
4. ``TGWS_PORT``   — туннель через локальный tg-ws-proxy
5. tg-ws-proxy, найденный автоматически (порт и конфиг)

Для туннеля TLS SNI и заголовок Host остаются api.telegram.org —
меняется только адрес TCP-подключения, поэтому сертификат валиден.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import aiohttp
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.methods import SendMessage
from aiogram.types import Message
from aiohttp import ClientSession, ClientTimeout, TCPConnector

from .config import API_BASE_URL, PROXY_URL, TGWS_HOST, TGWS_PORT
from .db import db

DEFAULT_BASE = "https://api.telegram.org"
PROBE_TIMEOUT = 8.0


class LocalTunnelResolver(aiohttp.abc.AbstractResolver):
    """Отправляет все соединения на локальный порт-туннель.

    Имя хоста в SNI и заголовке Host не меняется — сертификат и маршрутизация
    остаются валидными, меняется только адрес, куда идёт TCP-соединение.
    """

    def __init__(self, host: str, port: int) -> None:
        self._host = host
        self._port = port

    async def resolve(self, host, port=0, family=socket.AF_INET):
        return [
            {
                "hostname": self._host,
                "host": self._host,
                "port": self._port,
                "family": family,
                "proto": 0,
                "flags": socket.AI_NUMERICHOST,
            }
        ]

    async def close(self) -> None:
        pass


@dataclass
class Channel:
    """Канал подключения к Bot API."""

    mode: str  # direct | proxy | tunnel | custom
    description: str
    base: str = DEFAULT_BASE
    proxy: Optional[str] = None
    resolver: Optional[LocalTunnelResolver] = None

    @property
    def url(self) -> str:
        return f"{self.base}/bot{{token}}/{{method}}"


@dataclass
class ProbeResult:
    """Итог проверки канала."""

    channel: Channel
    reachable: bool
    token_ok: bool
    detail: str


class TrackingSession(AiohttpSession):
    """Сессия, которая запоминает все сообщения бота.

    Так чистка чата работает для любых сообщений - не только тех, где
    хендлер сам вызвал track_message.
    """

    async def make_request(self, bot, method, timeout=None):
        response = await super().make_request(bot, method, timeout=timeout)
        if isinstance(method, SendMessage) and isinstance(response, Message):
            try:
                await db.track_message(response.chat.id, response.message_id, "auto")
            except Exception:  # noqa: BLE001 - трекинг не должен ломать бота
                pass
        return response


def _tgws_config_paths() -> list[Path]:
    """Где TgWsProxy хранит свой конфиг."""
    paths: list[Path] = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        paths.append(Path(appdata) / "TgWsProxy" / "config.json")
    paths.append(Path.home() / "Library" / "Application Support" / "TgWsProxy" / "config.json")
    paths.append(Path.home() / ".config" / "TgWsProxy" / "config.json")
    return paths


def discover_tgws() -> Optional[tuple[str, int]]:
    """Найти запущенный tg-ws-proxy: взять host/port из его конфига."""
    for path in _tgws_config_paths():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        port = data.get("port")
        host = data.get("host") or "127.0.0.1"
        if port:
            return str(host), int(port)
    return None


def _proxy_params(proxy: str) -> tuple[Any, Optional[str]]:
    """aiohttp: для socks5 нужен отдельный коннектор, для http — параметр."""
    if proxy.startswith("socks"):
        from aiohttp_socks import ProxyConnector

        return ProxyConnector.from_url(proxy), None
    return None, proxy


async def probe(channel: Channel, token: str, timeout: float = PROBE_TIMEOUT) -> ProbeResult:
    """Проверить канал настоящим запросом к Bot API."""
    url = channel.url.format(token=token, method="getMe")
    connector = None
    request_proxy = None

    if channel.resolver is not None:
        connector = TCPConnector(resolver=channel.resolver)
    if channel.proxy:
        connector, request_proxy = _proxy_params(channel.proxy)

    try:
        async with ClientSession(connector=connector) as client:
            async with client.get(
                url, proxy=request_proxy, timeout=ClientTimeout(total=timeout)
            ) as response:
                body = await response.text()
                compact = body.replace(" ", "")
                if '"ok":true' in compact:
                    return ProbeResult(channel, True, True, "доступен, токен принят")
                if response.status == 401:
                    return ProbeResult(channel, True, False, "доступен, но токен отклонён (401)")
                return ProbeResult(channel, True, False, f"доступен, ответ HTTP {response.status}")
    except Exception as exc:
        return ProbeResult(channel, False, False, f"{type(exc).__name__}: {exc}")


def build_session(channel: Channel) -> AiohttpSession:
    """Собрать сессию aiogram под выбранный канал."""
    if channel.mode == "custom":
        api = TelegramAPIServer.from_base(channel.base.rstrip("/"))
        return TrackingSession(api=api)
    if channel.mode == "proxy":
        return TrackingSession(proxy=channel.proxy)
    if channel.mode == "tunnel":
        session = TrackingSession()
        session._connector_init["resolver"] = channel.resolver
        return session
    return TrackingSession()


def candidate_channels() -> list[Channel]:
    """Список каналов в порядке приоритета."""
    channels: list[Channel] = []

    if API_BASE_URL:
        channels.append(
            Channel(
                mode="custom",
                description=f"свой адрес Bot API ({API_BASE_URL})",
                base=API_BASE_URL.rstrip("/"),
            )
        )

    if PROXY_URL:
        channels.append(
            Channel(
                mode="proxy",
                description=f"прокси ({PROXY_URL.split('@')[-1]})",
                proxy=PROXY_URL,
            )
        )

    channels.append(Channel(mode="direct", description="прямое подключение"))

    if TGWS_PORT:
        channels.append(
            Channel(
                mode="tunnel",
                description=f"туннель tg-ws-proxy ({TGWS_HOST}:{TGWS_PORT})",
                resolver=LocalTunnelResolver(TGWS_HOST, TGWS_PORT),
            )
        )
    else:
        found = discover_tgws()
        if found:
            host, port = found
            channels.append(
                Channel(
                    mode="tunnel",
                    description=f"туннель tg-ws-proxy ({host}:{port}, найден автоматически)",
                    resolver=LocalTunnelResolver(host, port),
                )
            )

    return channels


async def detect_channel(
    token: str, channels: Optional[list[Channel]] = None
) -> tuple[Optional[Channel], list[ProbeResult]]:
    """Найти первый рабочий канал.

    Все кандидаты проверяются параллельно, результат выбирается по приоритету.
    """
    channels = channels or candidate_channels()
    if not channels:
        return None, []

    results = await asyncio.gather(*(probe(ch, token) for ch in channels))

    for result in results:
        if result.reachable:
            return result.channel, results
    return None, results

"""Shared test doubles. Tests never touch the network: sockets are blocked outright."""

from __future__ import annotations

import json
import socket
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from sentinel_quant.data.client import MarketDataClient, RetryPolicy, build_public_exchange

FIXTURE = Path(__file__).parent / "fixtures/binance_spot.json"
HOUR_MS = 3_600_000
T0 = 1_700_000_000_000 // HOUR_MS * HOUR_MS  # an arbitrary hour boundary


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("network access attempted in a test")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.fixture
def recorded() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return data


def replay_exchange(recorded: dict[str, Any]) -> Any:
    """The production ccxt client, with HTTP replaced by recorded mainnet responses."""
    exchange = build_public_exchange("binance")
    exchange.enableRateLimit = False
    exchange.requested_urls = []

    def fetch(url: str, method: str = "GET", headers: Any = None, body: Any = None) -> Any:
        exchange.requested_urls.append(url)
        if url not in recorded["responses"]:
            raise AssertionError(f"no recording for {url}")
        return recorded["responses"][url]

    exchange.fetch = fetch
    return exchange


def bar(open_time_ms: int, price: float = 100.0, volume: float = 5.0) -> list[Any]:
    return [open_time_ms, price, price + 1, price - 1, price + 0.5, volume]


class FakeExchange:
    """Scripted exchange: serves ``bars`` plus a forming bar, like the real klines API."""

    id = "binance"
    timeframes: dict[str, str] = {"1h": "1h"}  # noqa: RUF012

    def __init__(self, now_ms: int, bars: list[list[Any]] | None = None) -> None:
        self.now_ms = now_ms
        self.bars = bars if bars is not None else []
        self.errors: list[Exception] = []
        self.calls: list[tuple[str, int]] = []
        self.last_response_headers: dict[str, str] = {}
        self.fail_symbols: dict[str, Exception] = {}

    def load_markets(self) -> dict[str, Any]:
        return {"BTC/USDT": {"spot": True}, "ETH/USDT": {"spot": True}}

    def fetch_time(self) -> int:
        return self.now_ms

    def fetch_ohlcv(self, symbol: str, timeframe: str, since: int, limit: int) -> list[list[Any]]:
        self.calls.append((symbol, since))
        if self.errors:
            raise self.errors.pop(0)
        if symbol in self.fail_symbols:
            raise self.fail_symbols[symbol]
        forming = self.now_ms // HOUR_MS * HOUR_MS
        rows = [*self.bars, bar(forming, price=999.0)]
        return [r for r in rows if r[0] >= since and r[0] <= forming][:limit]


def hourly(start_ms: int, count: int) -> list[list[Any]]:
    return [bar(start_ms + i * HOUR_MS, price=100.0 + i) for i in range(count)]


def make_client(exchange: Any, sleeps: list[float] | None = None) -> MarketDataClient:
    log = sleeps if sleeps is not None else []
    return MarketDataClient(exchange, RetryPolicy(3, 1.0, 8.0), sleep=log.append)


@pytest.fixture
def sleeps() -> Iterator[list[float]]:
    yield []

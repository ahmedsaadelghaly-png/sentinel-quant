"""Public market data client (ccxt, spot, mainnet, no credentials).

This client is read-only by construction: it never receives API keys and exposes
no order methods. ``exchange.testnet`` does not apply here (see ``DataConfig``).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, TypeVar

import ccxt

from sentinel_quant.config.schema import AppConfig
from sentinel_quant.ops.logging import get_logger

T = TypeVar("T")
OhlcvRow = Sequence[Any]  # [open_time_ms, open, high, low, close, volume]

_REQUEST_TIMEOUT_MS = 30_000
# DDoSProtection is what ccxt raises for Binance HTTP 418 (IP ban).
_THROTTLED = (ccxt.RateLimitExceeded, ccxt.DDoSProtection)
_RETRYABLE = (ccxt.NetworkError, *_THROTTLED)


class MarketDataError(RuntimeError):
    """A market data request failed permanently, or retries ran out."""


@dataclass(frozen=True)
class RetryPolicy:
    max_retries: int = 5
    backoff_base_seconds: float = 1.0
    backoff_max_seconds: float = 60.0

    def backoff(self, attempt: int) -> float:
        """Delay before retry number ``attempt`` (1-based)."""
        return min(self.backoff_base_seconds * 2.0 ** (attempt - 1), self.backoff_max_seconds)


def build_public_exchange(name: str) -> Any:
    """Create a key-less spot ccxt client. Sandbox mode is deliberately never enabled."""
    exchange_cls = getattr(ccxt, name, None)
    if exchange_cls is None or name not in ccxt.exchanges:
        raise MarketDataError(f"unknown exchange: {name!r}")
    return exchange_cls(
        {
            "enableRateLimit": True,
            "timeout": _REQUEST_TIMEOUT_MS,
            "options": {"defaultType": "spot", "fetchMarkets": {"types": ["spot"]}},
        }
    )


def _retry_after_seconds(headers: Mapping[str, Any] | None) -> float | None:
    for name, value in (headers or {}).items():
        if str(name).lower() == "retry-after":
            try:
                return max(float(value), 0.0)
            except (TypeError, ValueError):
                return None
    return None


class MarketDataClient:
    def __init__(
        self,
        exchange: Any,
        retry: RetryPolicy | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._exchange = exchange
        self._retry = retry or RetryPolicy()
        self._sleep = sleep
        self._log = get_logger()

    @classmethod
    def from_config(cls, cfg: AppConfig) -> MarketDataClient:
        return cls(
            build_public_exchange(cfg.exchange.name),
            RetryPolicy(
                max_retries=cfg.data.max_retries,
                backoff_base_seconds=cfg.data.backoff_base_seconds,
                backoff_max_seconds=cfg.data.backoff_max_seconds,
            ),
        )

    @property
    def exchange_name(self) -> str:
        return str(self._exchange.id)

    @property
    def library_version(self) -> str:
        return str(ccxt.__version__)

    def validate(self, symbols: Sequence[str], timeframe: str) -> None:
        """Fail early if a symbol is unknown or not spot, or the timeframe is unavailable."""
        markets: Mapping[str, Any] = self._call("load_markets", self._exchange.load_markets)
        if timeframe not in self._exchange.timeframes:
            raise MarketDataError(f"{self.exchange_name} does not offer timeframe {timeframe}")
        for symbol in symbols:
            market = markets.get(symbol)
            if market is None:
                raise MarketDataError(f"unknown symbol on {self.exchange_name}: {symbol}")
            if not market.get("spot"):
                raise MarketDataError(f"not a spot market: {symbol}")

    def server_time_ms(self) -> int:
        return int(self._call("fetch_time", self._exchange.fetch_time))

    def fetch_ohlcv(self, symbol: str, timeframe: str, since_ms: int, limit: int) -> list[OhlcvRow]:
        rows: list[OhlcvRow] = self._call(
            "fetch_ohlcv",
            lambda: self._exchange.fetch_ohlcv(symbol, timeframe, since=since_ms, limit=limit),
        )
        return rows

    def _call(self, operation: str, fn: Callable[[], T]) -> T:
        attempt = 0
        while True:
            try:
                return fn()
            except _RETRYABLE as exc:
                attempt += 1
                if attempt > self._retry.max_retries:
                    raise MarketDataError(
                        f"{operation} failed after {self._retry.max_retries} retries: {exc}"
                    ) from exc
                delay = self._delay(operation, attempt, exc)
                self._log.warning(
                    "market_data_retry",
                    operation=operation,
                    attempt=attempt,
                    delay_seconds=delay,
                    error=type(exc).__name__,
                )
                self._sleep(delay)
            except ccxt.BaseError as exc:
                raise MarketDataError(f"{operation} failed: {exc}") from exc

    def _delay(self, operation: str, attempt: int, exc: Exception) -> float:
        delay = self._retry.backoff(attempt)
        if not isinstance(exc, _THROTTLED):
            return delay
        headers = getattr(self._exchange, "last_response_headers", None)
        retry_after = _retry_after_seconds(headers)
        if retry_after is None:
            return delay
        if retry_after > self._retry.backoff_max_seconds:
            # Requests sent during a ban extend it, so give up rather than hammer.
            raise MarketDataError(
                f"{operation}: exchange requires a {retry_after:.0f}s wait, "
                f"above the {self._retry.backoff_max_seconds:.0f}s limit"
            ) from exc
        return max(delay, retry_after)

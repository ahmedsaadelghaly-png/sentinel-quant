"""Live candle polling that only ever emits closed bars."""

from __future__ import annotations

import threading
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass

from sentinel_quant.data.client import MarketDataClient, MarketDataError, OhlcvRow
from sentinel_quant.data.timeframes import closed_cutoff_ms, timeframe_ms
from sentinel_quant.ops.logging import get_logger


@dataclass(frozen=True)
class Candle:
    symbol: str
    timeframe: str
    open_time_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float


def to_candle(symbol: str, timeframe: str, row: OhlcvRow) -> Candle | None:
    """Convert a raw row, or return None if it is unusable as a trading input."""
    values = row[1:6]
    if any(v is None for v in values):
        return None
    open_, high, low, close, volume = (float(v) for v in values)
    if min(open_, high, low, close) <= 0 or volume < 0 or high < low:
        return None
    return Candle(symbol, timeframe, int(row[0]), open_, high, low, close, volume)


class ClosedCandlePoller:
    """Polls REST klines and emits each closed bar once, in order, per symbol.

    Closure is decided from exchange time, never from the local clock or from a bar
    merely being returned. The bar still forming is always in the response and is
    always dropped. After downtime, polling resumes from the last emitted bar, so
    missed bars are caught up rather than skipped.

    ``start_after`` maps symbol to the open time of the last bar already processed.
    A symbol without an entry starts at the most recent closed bar.
    """

    def __init__(
        self,
        client: MarketDataClient,
        symbols: Sequence[str],
        timeframe: str,
        *,
        grace_ms: int,
        page_limit: int,
        retry_seconds: float,
        start_after: Mapping[str, int] | None = None,
    ) -> None:
        self._client = client
        self._symbols = tuple(symbols)
        self._timeframe = timeframe
        self._tf_ms = timeframe_ms(timeframe)
        self._grace_ms = grace_ms
        self._page_limit = page_limit
        self._retry_seconds = retry_seconds
        self._last: dict[str, int] = dict(start_after or {})
        self._log = get_logger()
        self._wait_seconds = retry_seconds

    @property
    def wait_seconds(self) -> float:
        """How long to wait before the next poll is worthwhile."""
        return self._wait_seconds

    def poll_once(self) -> list[Candle]:
        """Return newly closed bars. One failing symbol never costs another its bars."""
        now_ms = self._client.server_time_ms()
        cutoff = closed_cutoff_ms(now_ms, self._tf_ms, self._grace_ms)
        candles: list[Candle] = []
        for symbol in self._symbols:
            try:
                candles.extend(self._poll_symbol(symbol, cutoff))
            except MarketDataError as exc:
                self._log.warning("live_poll_failed", symbol=symbol, error=str(exc))
        newest_closed = cutoff - self._tf_ms
        behind = any(self._last.get(s, newest_closed - 1) < newest_closed for s in self._symbols)
        next_visible_ms = cutoff + self._tf_ms + self._grace_ms
        self._wait_seconds = (
            self._retry_seconds if behind else max((next_visible_ms - now_ms) / 1000, 0.0)
        )
        return candles

    def stream(self, stop: threading.Event) -> Iterator[Candle]:
        """Yield closed bars until ``stop`` is set, surviving exchange outages."""
        while not stop.is_set():
            try:
                yield from self.poll_once()
            except MarketDataError as exc:
                self._log.warning("live_poll_failed", error=str(exc))
                self._wait_seconds = self._retry_seconds
            stop.wait(self._wait_seconds)

    def _poll_symbol(self, symbol: str, cutoff: int) -> list[Candle]:
        last = self._last.get(symbol)
        since = cutoff - self._tf_ms if last is None else last + self._tf_ms
        if since >= cutoff:
            return []
        page = self._client.fetch_ohlcv(symbol, self._timeframe, since, self._page_limit)
        closed = {int(row[0]): row for row in page if since <= int(row[0]) < cutoff}
        candles: list[Candle] = []
        for open_time in sorted(closed):
            if last is not None and open_time > last + self._tf_ms:
                self._log.warning(
                    "live_gap",
                    symbol=symbol,
                    missing_bars=(open_time - last) // self._tf_ms - 1,
                )
            candle = to_candle(symbol, self._timeframe, closed[open_time])
            if candle is None:
                self._log.warning("live_bad_bar", symbol=symbol, open_time_ms=open_time)
            else:
                candles.append(candle)
            last = open_time
        if last is not None:
            self._last[symbol] = last
        return candles

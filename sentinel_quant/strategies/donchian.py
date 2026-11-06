"""Donchian channel breakout, long only.

A placeholder to exercise the automated loop (MVP-5). It has not passed any validation
gate and carries no claim of profitability.
"""

from __future__ import annotations

from collections import deque

from sentinel_quant.config.schema import StrategyConfig
from sentinel_quant.data.live import Candle
from sentinel_quant.features.indicators import average_true_range, prior_high, prior_low
from sentinel_quant.strategies.base import Action, Signal, StrategyMetadata

METADATA = StrategyMetadata(
    id="donchian_breakout",
    catalog_entity="A-005",
    markets=("SPOT_CRYPTO",),
    sharia_status="UNREVIEWED",
    evidence="NOT_ASSESSED",
    description="Long on a close above the prior N-bar high; exit below the prior M-bar low.",
)


class DonchianBreakout:
    metadata = METADATA

    def __init__(self, cfg: StrategyConfig) -> None:
        self._cfg = cfg
        self._size = max(cfg.entry_lookback, cfg.exit_lookback, cfg.atr_period + 1) + 1
        self._bars: dict[str, deque[Candle]] = {}

    @property
    def warmup_bars(self) -> int:
        return self._size

    def on_bar(self, bar: Candle, holding: bool) -> Signal | None:
        history = self._bars.setdefault(bar.symbol, deque(maxlen=self._size))
        history.append(bar)
        if len(history) < self._size:
            return None
        cfg = self._cfg
        highs = [b.high for b in history]
        lows = [b.low for b in history]
        closes = [b.close for b in history]
        if holding:
            floor = prior_low(lows, cfg.exit_lookback)[-1]
            if floor is not None and bar.close < floor:
                reason = f"close {bar.close} below {cfg.exit_lookback}-bar low {floor}"
                return Signal(bar.symbol, Action.EXIT, bar.open_time_ms, reason)
            return None
        ceiling = prior_high(highs, cfg.entry_lookback)[-1]
        atr = average_true_range(highs, lows, closes, cfg.atr_period)[-1]
        if ceiling is None or atr is None or bar.close <= ceiling:
            return None
        stop = bar.close - cfg.atr_stop_multiple * atr
        if stop <= 0:
            return None
        reason = f"close {bar.close} above {cfg.entry_lookback}-bar high {ceiling}"
        return Signal(bar.symbol, Action.ENTER, bar.open_time_ms, reason, stop)

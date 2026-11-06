"""Indicators as pure functions of past and current values.

The value at index ``i`` depends only on inputs up to and including ``i``, so it is
known when bar ``i`` closes. Warm-up positions are None. Truncation tests enforce this.
"""

from __future__ import annotations

from collections.abc import Sequence
from statistics import fmean


def prior_high(values: Sequence[float], window: int) -> list[float | None]:
    """Highest of the ``window`` values before each index, excluding the current one."""
    return [max(values[i - window : i]) if i >= window else None for i in range(len(values))]


def prior_low(values: Sequence[float], window: int) -> list[float | None]:
    """Lowest of the ``window`` values before each index, excluding the current one."""
    return [min(values[i - window : i]) if i >= window else None for i in range(len(values))]


def true_range(
    high: Sequence[float], low: Sequence[float], close: Sequence[float]
) -> list[float | None]:
    ranges: list[float | None] = [None] if len(high) else []
    for i in range(1, len(high)):
        previous = close[i - 1]
        ranges.append(max(high[i] - low[i], abs(high[i] - previous), abs(low[i] - previous)))
    return ranges


def average_true_range(
    high: Sequence[float], low: Sequence[float], close: Sequence[float], period: int
) -> list[float | None]:
    """Simple mean of the last ``period`` true ranges."""
    ranges = true_range(high, low, close)
    out: list[float | None] = []
    for i in range(len(ranges)):
        window = [r for r in ranges[max(i - period + 1, 0) : i + 1] if r is not None]
        out.append(fmean(window) if len(window) == period else None)
    return out

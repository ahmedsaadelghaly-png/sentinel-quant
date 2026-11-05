"""Timeframes and the single definition of "closed bar" used across the data layer."""

from __future__ import annotations

_MINUTE_MS = 60_000
_HOUR_MS = 60 * _MINUTE_MS

# Only timeframes whose bars align to the Unix epoch, so alignment can be checked
# with a modulo. 1w opens on Monday and 1M has variable length, so both are excluded.
TIMEFRAME_MS: dict[str, int] = {
    "1m": _MINUTE_MS,
    "3m": 3 * _MINUTE_MS,
    "5m": 5 * _MINUTE_MS,
    "15m": 15 * _MINUTE_MS,
    "30m": 30 * _MINUTE_MS,
    "1h": _HOUR_MS,
    "2h": 2 * _HOUR_MS,
    "4h": 4 * _HOUR_MS,
    "6h": 6 * _HOUR_MS,
    "8h": 8 * _HOUR_MS,
    "12h": 12 * _HOUR_MS,
    "1d": 24 * _HOUR_MS,
}


def timeframe_ms(timeframe: str) -> int:
    try:
        return TIMEFRAME_MS[timeframe]
    except KeyError:
        raise ValueError(f"unsupported timeframe: {timeframe!r}") from None


def closed_cutoff_ms(now_ms: int, tf_ms: int, grace_ms: int) -> int:
    """Exclusive upper bound on closed bar open times.

    A bar opening at ``t`` is closed only when ``t < cutoff``, which guarantees
    ``t + tf <= now - grace``. ``now_ms`` must be exchange time, so a fast local
    clock cannot turn a forming bar into a "closed" one.
    """
    return (now_ms - grace_ms) // tf_ms * tf_ms

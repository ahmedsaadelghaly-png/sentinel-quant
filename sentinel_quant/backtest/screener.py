"""Fast vectorized screener for simple target-position strategies.

For ranking many variants quickly. It models next-open fills, costs and zero-volume bars,
but not stops, risk limits or cash checks, so the event-driven engine stays the reference.
Golden tests require both to agree where their models overlap.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray

from sentinel_quant.backtest.models import BacktestError, CostModel
from sentinel_quant.data.live import Candle


def screen(
    bars: Sequence[Candle],
    target: NDArray[np.bool_],
    quantity: float,
    costs: CostModel,
    initial_cash: float,
) -> NDArray[np.float64]:
    """Equity at each bar's close. ``target[i]`` is the position wanted after bar ``i`` closes."""
    if len(bars) != len(target):
        raise BacktestError("target must have one value per bar")
    opens = np.array([b.open for b in bars], dtype=np.float64)
    closes = np.array([b.close for b in bars], dtype=np.float64)
    tradable = np.array([b.volume > 0 for b in bars])

    # A wish from bar i-1 takes effect at bar i's open, or at the next bar that traded.
    wanted = np.concatenate(([False], target[:-1]))
    index = np.where(tradable, np.arange(len(bars)), 0)
    held = wanted[np.maximum.accumulate(index)] & (np.maximum.accumulate(index) > 0)

    change = np.diff(held.astype(np.int8), prepend=np.int8(0))
    buy_price = opens * (1 + costs.slippage_bps / 10_000)
    sell_price = opens * (1 - costs.slippage_bps / 10_000)
    fee = costs.fee_bps / 10_000
    cash_flow = np.where(
        change > 0,
        -quantity * buy_price * (1 + fee),
        np.where(change < 0, quantity * sell_price * (1 - fee), 0.0),
    )
    equity: NDArray[np.float64] = initial_cash + np.cumsum(cash_flow) + held * quantity * closes
    return equity

"""Headline performance metrics, net and gross of costs.

Deflated Sharpe, PBO and bootstrap intervals arrive with full M3. A number from this
module is not evidence of an edge on its own.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import pairwise
from statistics import fmean, stdev

from sentinel_quant.backtest.models import BacktestResult
from sentinel_quant.data.timeframes import timeframe_ms

_YEAR_MS = 365 * 24 * 3_600_000  # crypto trades every day


@dataclass(frozen=True)
class PerformanceSummary:
    net_pnl: float
    gross_pnl: float  # net plus fees and slippage paid
    fees_paid: float
    slippage_paid: float
    net_return_pct: float
    max_drawdown_pct: float
    sharpe: float | None  # annualised, zero risk-free rate; None if undefined
    trades: int
    win_rate_pct: float | None
    profit_factor: float | None  # None when there are no losing trades
    turnover: float  # traded notional / initial cash


def max_drawdown_pct(equity: list[float]) -> float:
    peak = -math.inf
    worst = 0.0
    for value in equity:
        peak = max(peak, value)
        worst = max(worst, (peak - value) / peak)
    return 100 * worst


def sharpe_ratio(equity: list[float], periods_per_year: float) -> float | None:
    if len(equity) < 3:
        return None
    returns = [b / a - 1 for a, b in pairwise(equity)]
    deviation = stdev(returns)
    if deviation == 0:
        return None
    return fmean(returns) / deviation * math.sqrt(periods_per_year)


def summarize(result: BacktestResult) -> PerformanceSummary:
    equity = [result.initial_cash, *(point.equity for point in result.equity_curve)]
    net = equity[-1] - result.initial_cash
    pnls = [trade.net_pnl for trade in result.trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    return PerformanceSummary(
        net_pnl=net,
        gross_pnl=net + result.fees_paid + result.slippage_paid,
        fees_paid=result.fees_paid,
        slippage_paid=result.slippage_paid,
        net_return_pct=100 * net / result.initial_cash,
        max_drawdown_pct=max_drawdown_pct(equity),
        sharpe=sharpe_ratio(equity, _YEAR_MS / timeframe_ms(result.timeframe)),
        trades=len(pnls),
        win_rate_pct=100 * len(wins) / len(pnls) if pnls else None,
        profit_factor=sum(wins) / -sum(losses) if losses else None,
        turnover=sum(f.quantity * f.price for f in result.fills) / result.initial_cash,
    )

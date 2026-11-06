import math

import pytest
from test_backtest_engine import COSTS, buy, candle, run, sell

from sentinel_quant.evaluation.metrics import max_drawdown_pct, sharpe_ratio, summarize


def test_max_drawdown_is_measured_from_the_running_peak() -> None:
    assert max_drawdown_pct([100, 120, 90, 110, 80, 130]) == pytest.approx(100 * 40 / 120)
    assert max_drawdown_pct([100, 110, 120]) == 0


def test_sharpe_matches_a_hand_calculation() -> None:
    # Returns +10%, -10%, +10%: mean 1/30, sample deviation sqrt(4/300).
    equity = [100.0, 110.0, 99.0, 108.9]
    expected = (1 / 30) / math.sqrt(4 / 300) * math.sqrt(252)
    assert sharpe_ratio(equity, 252) == pytest.approx(expected)


def test_sharpe_is_undefined_not_infinite() -> None:
    assert sharpe_ratio([100.0, 100.0, 100.0], 252) is None
    assert sharpe_ratio([100.0, 101.0], 252) is None


def test_trade_statistics() -> None:
    bars = [
        candle(0),
        candle(1, 100),
        candle(2, 120),
        candle(3, 100),
        candle(4, 90),
        candle(5, 90),
    ]
    script = {0: [buy(1.0)], 1: [sell(1.0)], 2: [buy(1.0)], 3: [sell(1.0)]}
    summary = summarize(run(bars, script))
    assert summary.trades == 2
    assert summary.win_rate_pct == 50
    assert summary.profit_factor == pytest.approx(2.0)
    assert summary.turnover == pytest.approx((100 + 120 + 100 + 90) / 10_000)


def test_no_losses_means_profit_factor_is_undefined() -> None:
    bars = [candle(0), candle(1, 100), candle(2, 120), candle(3, 120)]
    summary = summarize(run(bars, {0: [buy()], 1: [sell()]}))
    assert summary.profit_factor is None
    assert summary.win_rate_pct == 100


def test_summary_annualises_hourly_bars_over_a_365_day_year() -> None:
    bars = [candle(i, 100 + (i % 3)) for i in range(10)]
    result = run(bars, {0: [buy()]}, COSTS)
    equity = [result.initial_cash, *(p.equity for p in result.equity_curve)]
    assert summarize(result).sharpe == pytest.approx(sharpe_ratio(equity, 365 * 24))

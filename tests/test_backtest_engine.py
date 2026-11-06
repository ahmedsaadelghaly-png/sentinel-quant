from collections.abc import Callable, Sequence
from typing import Any

import pytest
from conftest import HOUR_MS, T0

from sentinel_quant.backtest.engine import run_backtest
from sentinel_quant.backtest.models import BacktestError, BacktestResult, CostModel, FillReason
from sentinel_quant.data.live import Candle
from sentinel_quant.execution.orders import (
    OrderError,
    OrderRequest,
    OrderType,
    PortfolioSnapshot,
    Side,
)
from sentinel_quant.risk.gate import RiskDecision

FREE = CostModel(0.0, 0.0)
COSTS = CostModel(10.0, 5.0)
SYMBOL = "BTC/USDT"


class ApproveAll:
    """Test double only: the package deliberately ships no approve-all gate."""

    flatten_required = False

    def observe(self, portfolio: PortfolioSnapshot) -> None:
        pass

    def on_trade_closed(self, net_pnl: float) -> None:
        pass

    def check(self, order: OrderRequest, portfolio: PortfolioSnapshot) -> RiskDecision:
        return RiskDecision(True)


class Scripted:
    """Submits the given orders after the bar with that index closes."""

    def __init__(self, script: dict[int, list[OrderRequest]]) -> None:
        self.script = script
        self.seen = 0

    def on_bar(self, bar: Candle, portfolio: PortfolioSnapshot) -> Sequence[OrderRequest]:
        orders = self.script.get(self.seen, [])
        self.seen += 1
        return orders


def candle(
    index: int,
    open_: float = 100.0,
    high: float | None = None,
    low: float | None = None,
    close: float | None = None,
    volume: float = 10.0,
    symbol: str = SYMBOL,
) -> Candle:
    close = open_ if close is None else close
    return Candle(
        symbol,
        "1h",
        T0 + index * HOUR_MS,
        open_,
        max(open_, close) if high is None else high,
        min(open_, close) if low is None else low,
        close,
        volume,
    )


def buy(quantity: float = 1.0, stop: float | None = None) -> OrderRequest:
    return OrderRequest(SYMBOL, Side.BUY, quantity, stop_price=stop)


def sell(quantity: float = 1.0) -> OrderRequest:
    return OrderRequest(SYMBOL, Side.SELL, quantity)


def run(
    bars: list[Candle],
    script: dict[int, list[OrderRequest]],
    costs: CostModel = FREE,
    cash: float = 10_000.0,
) -> BacktestResult:
    return run_backtest({SYMBOL: bars}, Scripted(script), ApproveAll(), costs, cash)


def test_order_fills_at_next_bar_open_never_on_its_signal_bar() -> None:
    bars = [candle(0, 100, close=110), candle(1, 120, close=130)]
    result = run(bars, {0: [buy()]})
    (fill,) = result.fills
    assert fill.time_ms == T0 + HOUR_MS
    assert fill.submitted_ms == T0
    assert fill.price == 120


def test_order_on_last_bar_stays_unfilled() -> None:
    result = run([candle(0)], {0: [buy()]})
    assert result.fills == ()
    assert result.unfilled == (buy(),)


def test_slippage_is_adverse_on_both_sides() -> None:
    bars = [candle(0), candle(1, 100), candle(2, 200), candle(3, 200)]
    result = run(bars, {0: [buy()], 1: [sell()]}, CostModel(0.0, 10.0))
    assert result.fills[0].price == pytest.approx(100.1)
    assert result.fills[1].price == pytest.approx(199.8)


def test_zero_volume_bar_never_fills_the_order_waits() -> None:
    bars = [candle(0), candle(1, 100, volume=0.0), candle(2, 150)]
    result = run(bars, {0: [buy()]})
    assert result.fills[0].time_ms == T0 + 2 * HOUR_MS
    assert result.fills[0].price == 150


def test_order_across_a_data_gap_fills_at_first_price_after_it() -> None:
    bars = [candle(0, 100), candle(5, 140)]
    (fill,) = run(bars, {0: [buy()]}).fills
    assert fill.time_ms == T0 + 5 * HOUR_MS
    assert fill.price == 140


def test_stop_fills_at_stop_price_with_slippage() -> None:
    bars = [candle(0), candle(1, 100), candle(2, 100, low=89, close=95)]
    result = run(bars, {0: [buy(stop=90.0)]}, CostModel(0.0, 10.0))
    stop_fill = result.fills[1]
    assert stop_fill.reason is FillReason.STOP
    assert stop_fill.reference_price == 90
    assert stop_fill.price == pytest.approx(89.91)


def test_stop_jumped_by_a_gap_fills_at_the_open_not_the_stop() -> None:
    bars = [candle(0), candle(1, 100), candle(6, 70, high=75, low=65, close=72)]
    result = run(bars, {0: [buy(stop=90.0)]})
    stop_fill = result.fills[1]
    assert stop_fill.reason is FillReason.STOP_GAP
    assert stop_fill.price == 70


def test_protective_stop_is_live_on_the_entry_bar() -> None:
    bars = [candle(0), candle(1, 100, low=85, close=95)]
    result = run(bars, {0: [buy(stop=90.0)]})
    assert [f.side for f in result.fills] == [Side.BUY, Side.SELL]
    assert result.open_positions == {}


def test_stop_is_not_filled_on_a_zero_volume_bar() -> None:
    bars = [
        candle(0),
        candle(1, 100),
        candle(2, 85, volume=0.0),
        candle(3, 80, close=82),
    ]
    result = run(bars, {0: [buy(stop=90.0)]})
    assert result.fills[1].time_ms == T0 + 3 * HOUR_MS
    assert result.fills[1].price == 80


def test_flat_position_cancels_its_stop() -> None:
    bars = [candle(0), candle(1), candle(2), candle(3, 100, low=50, close=60)]
    result = run(bars, {0: [buy(stop=90.0)], 1: [sell()]})
    assert len(result.fills) == 2
    assert result.rejections == ()


def test_stop_only_sells_what_is_left() -> None:
    bars = [candle(0), candle(1), candle(2), candle(3, 100, low=50, close=60)]
    result = run(bars, {0: [buy(2.0, stop=90.0)], 1: [sell(0.5)]})
    assert result.fills[-1].quantity == 1.5
    assert result.open_positions == {}


def test_standalone_stop_arms_only_after_its_signal_bar() -> None:
    stop = OrderRequest(SYMBOL, Side.SELL, 1.0, OrderType.STOP, 90.0)
    bars = [candle(0), candle(1), candle(2, 100, low=95, close=96), candle(3, 89)]
    result = run(bars, {0: [buy()], 2: [stop]})
    assert result.fills[-1].time_ms == T0 + 3 * HOUR_MS


def test_buy_beyond_cash_is_rejected_not_shrunk() -> None:
    result = run([candle(0), candle(1, 100)], {0: [buy(11.0)]}, cash=1000.0)
    assert result.fills == ()
    assert result.rejections[0].reason == "insufficient_cash"
    assert result.final_equity == 1000.0


def test_fees_count_towards_affordability() -> None:
    result = run([candle(0), candle(1, 100)], {0: [buy(10.0)]}, COSTS, cash=1000.0)
    assert result.rejections[0].reason == "insufficient_cash"


def test_stop_is_not_armed_when_the_entry_was_rejected() -> None:
    bars = [candle(0), candle(1, 100), candle(2, 100, low=50, close=60)]
    result = run(bars, {0: [buy(99.0, stop=90.0)]}, cash=100.0)
    assert result.fills == ()


def test_shorting_is_impossible() -> None:
    result = run([candle(0), candle(1)], {0: [sell()]})
    assert result.fills == ()
    assert result.rejections[0].reason == "insufficient_position"


def test_selling_more_than_held_is_rejected_whole() -> None:
    bars = [candle(0), candle(1), candle(2), candle(3)]
    result = run(bars, {0: [buy(1.0)], 1: [sell(2.0)]})
    assert [f.side for f in result.fills] == [Side.BUY]
    assert result.rejections[0].reason == "insufficient_position"
    assert result.open_positions == {SYMBOL: 1.0}


def test_adding_to_a_position_averages_its_cost() -> None:
    bars = [candle(0), candle(1, 100), candle(2, 200), candle(3, 200), candle(4, 200)]
    result = run(bars, {0: [buy()], 1: [buy()], 2: [sell(2.0)]})
    (trade,) = result.trades
    assert trade.cost == 300
    assert trade.proceeds == 400


def test_risk_gate_veto_stops_the_order_and_sees_every_order() -> None:
    class Veto(ApproveAll):
        def __init__(self) -> None:
            self.seen: list[OrderRequest] = []

        def check(self, order: OrderRequest, portfolio: PortfolioSnapshot) -> RiskDecision:
            self.seen.append(order)
            return RiskDecision(order.side is Side.SELL, "daily loss limit")

    gate = Veto()
    stop = OrderRequest(SYMBOL, Side.SELL, 1.0, OrderType.STOP, 90.0)
    script = {0: [buy(), sell(), stop]}
    bars = [candle(0), candle(1)]
    result = run_backtest({SYMBOL: bars}, Scripted(script), gate, FREE, 1000.0)
    assert gate.seen == script[0]
    assert result.rejections[0].reason == "risk: daily loss limit"
    assert all(f.side is not Side.BUY for f in result.fills)


def test_backtest_cannot_run_without_a_risk_gate() -> None:
    call: Callable[..., Any] = run_backtest
    with pytest.raises(TypeError):
        call({SYMBOL: [candle(0)]}, Scripted({}), costs=FREE, initial_cash=1.0)


def test_strategy_cannot_mutate_the_portfolio() -> None:
    class Meddler:
        def on_bar(self, bar: Candle, portfolio: PortfolioSnapshot) -> Sequence[OrderRequest]:
            portfolio.positions[SYMBOL] = 5.0  # type: ignore[index]
            return []

    with pytest.raises(TypeError):
        run_backtest({SYMBOL: [candle(0)]}, Meddler(), ApproveAll(), FREE, 1.0)


def test_order_for_another_symbol_never_fills_on_the_same_timestamp() -> None:
    other = "ETH/USDT"

    class CrossSymbol:
        def on_bar(self, bar: Candle, portfolio: PortfolioSnapshot) -> Sequence[OrderRequest]:
            first = bar.open_time_ms == T0 and bar.symbol == SYMBOL
            return [OrderRequest(other, Side.BUY, 1.0)] if first else []

    bars = {
        SYMBOL: [candle(0), candle(1)],
        other: [candle(0, 50, symbol=other), candle(1, 60, symbol=other)],
    }
    result = run_backtest(bars, CrossSymbol(), ApproveAll(), FREE, 1000.0)
    assert result.fills[0].time_ms == T0 + HOUR_MS
    assert result.fills[0].price == 60


def test_equity_uses_last_known_mark_while_a_symbol_has_no_bar() -> None:
    other = "ETH/USDT"
    bars = {
        SYMBOL: [candle(0), candle(1, 100), candle(2, 100)],
        other: [candle(0, 50, symbol=other), candle(2, 50, symbol=other)],
    }
    script = {0: [buy()]}
    result = run_backtest(bars, Scripted(script), ApproveAll(), FREE, 1000.0)
    assert [p.equity for p in result.equity_curve] == [1000.0, 1000.0, 1000.0]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"quantity": 0.0},
        {"quantity": -1.0},
        {"quantity": float("nan")},
        {"quantity": 1.0, "stop_price": -1.0},
        {"quantity": 1.0, "order_type": OrderType.STOP},
    ],
)
def test_malformed_orders_are_refused(kwargs: dict[str, Any]) -> None:
    with pytest.raises(OrderError):
        OrderRequest(SYMBOL, Side.SELL, **kwargs)


def test_market_sell_cannot_carry_a_stop() -> None:
    with pytest.raises(OrderError):
        OrderRequest(SYMBOL, Side.SELL, 1.0, stop_price=90.0)


def test_buy_stop_is_refused() -> None:
    with pytest.raises(OrderError):
        OrderRequest(SYMBOL, Side.BUY, 1.0, OrderType.STOP, 90.0)


@pytest.mark.parametrize(
    "bars",
    [
        [],
        [candle(1), candle(0)],
        [candle(0), candle(0)],
        [candle(0, symbol="ETH/USDT")],
    ],
    ids=["empty", "descending", "duplicate", "wrong-symbol"],
)
def test_unusable_bars_are_refused(bars: list[Candle]) -> None:
    with pytest.raises(BacktestError):
        run(bars, {})


def test_mixed_timeframes_are_refused() -> None:
    odd = Candle("ETH/USDT", "4h", T0, 1.0, 1.0, 1.0, 1.0, 1.0)
    with pytest.raises(BacktestError, match="mixed"):
        run_backtest(
            {SYMBOL: [candle(0)], "ETH/USDT": [odd]}, Scripted({}), ApproveAll(), FREE, 1.0
        )


def test_negative_costs_and_cash_are_refused() -> None:
    with pytest.raises(BacktestError):
        CostModel(-1.0, 0.0)
    with pytest.raises(BacktestError):
        run([candle(0)], {}, cash=0.0)

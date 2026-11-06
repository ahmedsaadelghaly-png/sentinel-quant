"""Event-driven reference backtester.

Each timestamp runs in a fixed order, and that order is the look-ahead guard:

1. Orders from earlier bars fill against this bar.
2. Prices are marked at this bar's close and equity is recorded.
3. Only then does the strategy see the bar, so its orders can only fill later.

Every order passes the risk gate. The gate has no default on purpose: a backtest
cannot run without declaring one. A protective stop is part of the entry the gate
approved, so it is not checked again when it arms.

Not modelled yet (see ADR 0003): partial fills, volume limits, lot sizes, limit orders.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from sentinel_quant.backtest.models import (
    BacktestError,
    BacktestResult,
    BarStrategy,
    CostModel,
    EquityPoint,
    Fill,
    FillReason,
    Rejection,
    Trade,
)
from sentinel_quant.data.live import Candle
from sentinel_quant.data.timeframes import timeframe_ms
from sentinel_quant.execution.orders import OrderRequest, OrderType, PortfolioSnapshot, Side
from sentinel_quant.risk.gate import RiskGate

_DUST = 1e-12  # quantity left by float rounding after selling a whole position


@dataclass
class _Position:
    quantity: float
    cost: float  # total paid for the current quantity, fees included
    entry_ms: int


@dataclass(frozen=True)
class _Pending:
    order: OrderRequest
    submitted_ms: int


def _merge_bars(
    candles: Mapping[str, Sequence[Candle]],
) -> tuple[str, dict[int, list[Candle]]]:
    """Group bars by open time, refusing input a backtest cannot trust."""
    if not candles or not any(candles.values()):
        raise BacktestError("no candles to backtest")
    timeframes = {bar.timeframe for bars in candles.values() for bar in bars}
    if len(timeframes) != 1:
        raise BacktestError(f"mixed timeframes: {sorted(timeframes)}")
    by_time: dict[int, list[Candle]] = {}
    for symbol in sorted(candles):
        previous = None
        for bar in candles[symbol]:
            if bar.symbol != symbol:
                raise BacktestError(f"{bar.symbol} bar under {symbol}")
            if previous is not None and bar.open_time_ms <= previous:
                raise BacktestError(f"{symbol} bars are not strictly ascending")
            previous = bar.open_time_ms
            by_time.setdefault(bar.open_time_ms, []).append(bar)
    return timeframes.pop(), by_time


class _Simulation:
    def __init__(
        self, strategy: BarStrategy, risk: RiskGate, costs: CostModel, cash: float, tf_ms: int
    ) -> None:
        self._strategy = strategy
        self._risk = risk
        self._costs = costs
        self._tf_ms = tf_ms
        self.cash = cash
        self.positions: dict[str, _Position] = {}
        self.marks: dict[str, float] = {}
        self.market_orders: list[_Pending] = []
        self.stops: list[_Pending] = []
        self.fills: list[Fill] = []
        self.trades: list[Trade] = []
        self.rejections: list[Rejection] = []
        self.equity_curve: list[EquityPoint] = []
        self.fees_paid = 0.0
        self.slippage_paid = 0.0

    def step(self, time_ms: int, bars: Sequence[Candle]) -> None:
        for bar in bars:
            self._fill_against(bar)
        for bar in bars:
            self.marks[bar.symbol] = bar.close
        self.equity_curve.append(EquityPoint(time_ms + self._tf_ms, self._equity(), self.cash))
        self._risk.observe(self._snapshot(time_ms))
        if self._risk.flatten_required:
            self._flatten(time_ms)
        for bar in bars:
            for order in self._strategy.on_bar(bar, self._snapshot(time_ms)):
                self._submit(order, time_ms)

    def _flatten(self, time_ms: int) -> None:
        selling = {p.order.symbol for p in self.market_orders if p.order.side is Side.SELL}
        for symbol, position in self.positions.items():
            if symbol not in selling:
                self._submit(OrderRequest(symbol, Side.SELL, position.quantity), time_ms)

    def _equity(self) -> float:
        held = sum(p.quantity * self.marks[s] for s, p in self.positions.items())
        return self.cash + held

    def _snapshot(self, time_ms: int) -> PortfolioSnapshot:
        """A fresh view, so each order is judged with the orders approved before it."""
        return PortfolioSnapshot(
            time_ms=time_ms,
            as_of_ms=time_ms + self._tf_ms,
            cash=self.cash,
            equity=self._equity(),
            positions=MappingProxyType({s: p.quantity for s, p in self.positions.items()}),
            marks=MappingProxyType(dict(self.marks)),
            stops=tuple(p.order for p in self.stops),
            pending=tuple(p.order for p in self.market_orders),
        )

    def _submit(self, order: OrderRequest, time_ms: int) -> None:
        decision = self._risk.check(order, self._snapshot(time_ms))
        if not decision.approved:
            self.rejections.append(Rejection(time_ms, order, f"risk: {decision.reason}"))
            return
        pending = _Pending(order, time_ms)
        if order.order_type is OrderType.STOP:
            self.stops.append(pending)
        else:
            self.market_orders.append(pending)

    def _fill_against(self, bar: Candle) -> None:
        if bar.volume == 0:
            return  # nothing traded, so nothing could have filled: orders wait
        for pending in [p for p in self.market_orders if p.order.symbol == bar.symbol]:
            self.market_orders.remove(pending)
            self._execute(pending, bar, bar.open, FillReason.MARKET)
        for pending in [p for p in self.stops if p.order.symbol == bar.symbol]:
            stop = pending.order.stop_price
            if pending not in self.stops or stop is None:
                continue  # already cancelled by an earlier stop flattening the position
            if bar.open <= stop:
                self.stops.remove(pending)
                self._execute(pending, bar, bar.open, FillReason.STOP_GAP)
            elif bar.low <= stop:
                self.stops.remove(pending)
                self._execute(pending, bar, stop, FillReason.STOP)

    def _execute(
        self, pending: _Pending, bar: Candle, reference: float, reason: FillReason
    ) -> None:
        order = pending.order
        if order.side is Side.BUY:
            self._buy(pending, bar, reference, reason)
        else:
            self._sell(pending, bar, reference, reason)

    def _record(
        self, pending: _Pending, bar: Candle, quantity: float, reference: float, reason: FillReason
    ) -> tuple[float, float]:
        side = pending.order.side
        price = self._costs.fill_price(side, reference)
        fee = self._costs.fee(quantity * price)
        self.fees_paid += fee
        self.slippage_paid += quantity * abs(price - reference)
        self.fills.append(
            Fill(
                time_ms=bar.open_time_ms,
                submitted_ms=pending.submitted_ms,
                symbol=bar.symbol,
                side=side,
                quantity=quantity,
                reference_price=reference,
                price=price,
                fee=fee,
                reason=reason,
            )
        )
        return price, fee

    def _buy(self, pending: _Pending, bar: Candle, reference: float, reason: FillReason) -> None:
        order = pending.order
        price = self._costs.fill_price(Side.BUY, reference)
        total = order.quantity * price + self._costs.fee(order.quantity * price)
        if total > self.cash:
            self.rejections.append(Rejection(bar.open_time_ms, order, "insufficient_cash"))
            return
        self._record(pending, bar, order.quantity, reference, reason)
        self.cash -= total
        position = self.positions.get(order.symbol)
        if position is None:
            self.positions[order.symbol] = _Position(order.quantity, total, bar.open_time_ms)
        else:
            position.quantity += order.quantity
            position.cost += total
        if order.stop_price is not None:
            stop = OrderRequest(
                order.symbol, Side.SELL, order.quantity, OrderType.STOP, order.stop_price
            )
            self.stops.append(_Pending(stop, pending.submitted_ms))

    def _sell(self, pending: _Pending, bar: Candle, reference: float, reason: FillReason) -> None:
        order = pending.order
        position = self.positions.get(order.symbol)
        held = position.quantity if position else 0.0
        is_stop = order.order_type is OrderType.STOP
        # A stop protects what is held, even if part was sold since it was placed.
        quantity = min(order.quantity, held) if is_stop else order.quantity
        if position is None or quantity <= 0 or quantity > held:
            self.rejections.append(Rejection(bar.open_time_ms, order, "insufficient_position"))
            return
        price, fee = self._record(pending, bar, quantity, reference, reason)
        proceeds = quantity * price - fee
        self.cash += proceeds
        cost = position.cost * quantity / position.quantity
        trade = Trade(order.symbol, position.entry_ms, bar.open_time_ms, quantity, cost, proceeds)
        self.trades.append(trade)
        self._risk.on_trade_closed(trade.net_pnl)
        position.quantity -= quantity
        position.cost -= cost
        if position.quantity <= _DUST:
            del self.positions[order.symbol]
            self.stops = [p for p in self.stops if p.order.symbol != order.symbol]


def run_backtest(
    candles: Mapping[str, Sequence[Candle]],
    strategy: BarStrategy,
    risk: RiskGate,
    costs: CostModel,
    initial_cash: float,
    dataset_ids: Sequence[str] = (),
) -> BacktestResult:
    """Replay closed bars through a strategy. Deterministic for identical inputs.

    A position still open at the end is marked at the last close, with no exit cost.
    """
    if initial_cash <= 0:
        raise BacktestError("initial_cash must be positive")
    timeframe, by_time = _merge_bars(candles)
    simulation = _Simulation(strategy, risk, costs, initial_cash, timeframe_ms(timeframe))
    for time_ms in sorted(by_time):
        simulation.step(time_ms, by_time[time_ms])
    return BacktestResult(
        timeframe=timeframe,
        dataset_ids=tuple(dataset_ids),
        costs=costs,
        initial_cash=initial_cash,
        equity_curve=tuple(simulation.equity_curve),
        fills=tuple(simulation.fills),
        trades=tuple(simulation.trades),
        rejections=tuple(simulation.rejections),
        unfilled=tuple(p.order for p in simulation.market_orders),
        open_positions={s: p.quantity for s, p in simulation.positions.items()},
        fees_paid=simulation.fees_paid,
        slippage_paid=simulation.slippage_paid,
    )

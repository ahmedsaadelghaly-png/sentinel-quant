"""Internal simulator with the fill rules of the backtester.

The rules exist twice, here and in ``backtest.engine``. A parity test requires both to
produce identical fills, so they cannot drift apart unnoticed.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from sentinel_quant.backtest.models import CostModel
from sentinel_quant.data.live import Candle
from sentinel_quant.execution.adapter import Balances, FillReport, RejectReport
from sentinel_quant.execution.orders import OrderRequest, OrderType, Side

_DUST = 1e-12


class _SavedOrder(BaseModel):
    client_id: str
    symbol: str
    side: Side
    quantity: float
    order_type: OrderType
    stop_price: float | None
    signal_ms: int


class SimState(BaseModel):
    cash: float
    positions: dict[str, float]
    market: list[_SavedOrder]
    stops: list[_SavedOrder]
    seen: list[str]


@dataclass(frozen=True)
class _Open:
    client_id: str
    order: OrderRequest
    signal_ms: int


def _save(item: _Open) -> _SavedOrder:
    o = item.order
    return _SavedOrder(
        client_id=item.client_id,
        symbol=o.symbol,
        side=o.side,
        quantity=o.quantity,
        order_type=o.order_type,
        stop_price=o.stop_price,
        signal_ms=item.signal_ms,
    )


def _load(saved: _SavedOrder) -> _Open:
    order = OrderRequest(
        saved.symbol, saved.side, saved.quantity, saved.order_type, saved.stop_price
    )
    return _Open(saved.client_id, order, saved.signal_ms)


class SimAdapter:
    def __init__(self, costs: CostModel, cash: float, state: SimState | None = None) -> None:
        self._costs = costs
        self._cash = state.cash if state else cash
        self._positions: dict[str, float] = dict(state.positions) if state else {}
        self._market = [_load(o) for o in state.market] if state else []
        self._stops = [_load(o) for o in state.stops] if state else []
        self._seen: set[str] = set(state.seen) if state else set()
        self._fills: list[FillReport] = []
        self._rejects: list[RejectReport] = []

    def to_state(self) -> SimState:
        return SimState(
            cash=self._cash,
            positions=self._positions,
            market=[_save(o) for o in self._market],
            stops=[_save(o) for o in self._stops],
            seen=sorted(self._seen),
        )

    def place(self, client_id: str, order: OrderRequest, signal_ms: int) -> None:
        if client_id in self._seen:
            return
        self._seen.add(client_id)
        book = self._stops if order.order_type is OrderType.STOP else self._market
        book.append(_Open(client_id, order, signal_ms))

    def on_bar(self, bar: Candle) -> None:
        if bar.volume == 0:
            return
        # Strictly later bars only. After a crash a bar is replayed with its own order
        # already re-sent, and that order must not fill on the bar that produced it.
        due = [
            o
            for o in self._market
            if o.order.symbol == bar.symbol and o.signal_ms < bar.open_time_ms
        ]
        for item in due:
            self._market.remove(item)
            self._execute(item, bar, bar.open, "market")
        armed = [
            o
            for o in self._stops
            if o.order.symbol == bar.symbol and o.signal_ms < bar.open_time_ms
        ]
        for item in armed:
            stop = item.order.stop_price
            if item not in self._stops or stop is None:
                continue
            if bar.open <= stop:
                self._stops.remove(item)
                self._execute(item, bar, bar.open, "stop_gap")
            elif bar.low <= stop:
                self._stops.remove(item)
                self._execute(item, bar, stop, "stop")

    def poll(self) -> tuple[list[FillReport], list[RejectReport]]:
        fills, rejects = self._fills, self._rejects
        self._fills, self._rejects = [], []
        return fills, rejects

    def balances(self) -> Balances:
        return Balances(self._cash, dict(self._positions))

    def _execute(self, item: _Open, bar: Candle, reference: float, reason: str) -> None:
        order = item.order
        held = self._positions.get(order.symbol, 0.0)
        is_stop = order.order_type is OrderType.STOP
        quantity = min(order.quantity, held) if is_stop else order.quantity
        price = self._costs.fill_price(order.side, reference)
        fee = self._costs.fee(quantity * price)
        if order.side is Side.BUY:
            if quantity * price + fee > self._cash:
                self._rejects.append(RejectReport(item.client_id, "insufficient_cash"))
                return
            self._cash -= quantity * price + fee
            self._positions[order.symbol] = held + quantity
            if order.stop_price is not None:
                stop = OrderRequest(
                    order.symbol, Side.SELL, quantity, OrderType.STOP, order.stop_price
                )
                self._stops.append(_Open(f"{item.client_id}-s", stop, item.signal_ms))
        else:
            if quantity <= 0 or quantity > held:
                self._rejects.append(RejectReport(item.client_id, "insufficient_position"))
                return
            self._cash += quantity * price - fee
            remaining = held - quantity
            if remaining <= _DUST:
                self._positions.pop(order.symbol, None)
                self._stops = [o for o in self._stops if o.order.symbol != order.symbol]
            else:
                self._positions[order.symbol] = remaining
        self._fills.append(
            FillReport(
                fill_id=f"{item.client_id}:{bar.open_time_ms}",
                client_id=item.client_id,
                symbol=order.symbol,
                side=order.side,
                quantity=quantity,
                price=price,
                fee=fee,
                time_ms=bar.open_time_ms,
                reason=reason,
            )
        )

"""Strategy contract. Strategies decide direction and stop, never size."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from sentinel_quant.data.live import Candle
from sentinel_quant.execution.orders import OrderRequest, PortfolioSnapshot, Side
from sentinel_quant.risk.engine import RiskEngine


class Action(StrEnum):
    ENTER = "enter"
    EXIT = "exit"


@dataclass(frozen=True)
class StrategyMetadata:
    id: str
    catalog_entity: str  # id in docs/research/trading_strategies/
    markets: tuple[str, ...]
    sharia_status: str  # never a ruling: UNREVIEWED until a scholar has reviewed it
    evidence: str
    description: str


@dataclass(frozen=True)
class Signal:
    symbol: str
    action: Action
    time_ms: int
    reason: str  # shown in the decision log and the daily report
    stop_price: float | None = None


class SignalStrategy(Protocol):
    metadata: StrategyMetadata

    def on_bar(self, bar: Candle, holding: bool) -> Signal | None: ...


class SizedStrategy:
    """Turns signals into orders, with size coming only from the risk engine."""

    def __init__(self, strategy: SignalStrategy, risk: RiskEngine) -> None:
        self._strategy = strategy
        self._risk = risk
        self.signals: list[Signal] = []

    def on_bar(self, bar: Candle, portfolio: PortfolioSnapshot) -> Sequence[OrderRequest]:
        pending = [o for o in portfolio.pending if o.symbol == bar.symbol]
        held = portfolio.positions.get(bar.symbol, 0.0)
        entering = any(o.side is Side.BUY for o in pending)
        signal = self._strategy.on_bar(bar, held > 0 or entering)
        if signal is None:
            return []
        self.signals.append(signal)
        if signal.action is Action.EXIT:
            exiting = any(o.side is Side.SELL for o in pending)
            return [] if exiting or held <= 0 else [OrderRequest(bar.symbol, Side.SELL, held)]
        if signal.stop_price is None:
            return []
        quantity = self._risk.size(bar.close, signal.stop_price, portfolio)
        if quantity <= 0:
            return []
        return [OrderRequest(bar.symbol, Side.BUY, quantity, stop_price=signal.stop_price)]

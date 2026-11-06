"""Orders, fills and results of the event-driven backtester (long-only spot)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from sentinel_quant.config.schema import BacktestConfig
from sentinel_quant.data.live import Candle
from sentinel_quant.execution.orders import OrderRequest, PortfolioSnapshot, Side


class BacktestError(ValueError):
    """The inputs to a backtest are unusable."""


class FillReason(StrEnum):
    MARKET = "market"
    STOP = "stop"  # traded through the stop price during the bar
    STOP_GAP = "stop_gap"  # the bar opened beyond the stop, so it fills at the open


@dataclass(frozen=True)
class CostModel:
    """Per-side costs in basis points of traded notional."""

    fee_bps: float
    slippage_bps: float

    def __post_init__(self) -> None:
        if self.fee_bps < 0 or self.slippage_bps < 0:
            raise BacktestError("costs cannot be negative")

    @classmethod
    def from_config(cls, cfg: BacktestConfig) -> CostModel:
        return cls(cfg.taker_fee_bps, cfg.slippage_bps)

    def stressed(self, factor: float) -> CostModel:
        """Scaled costs, for the x2 cost stress test (gate G5)."""
        return CostModel(self.fee_bps * factor, self.slippage_bps * factor)

    def fill_price(self, side: Side, reference: float) -> float:
        rate = self.slippage_bps / 10_000
        return reference * (1 + rate) if side is Side.BUY else reference * (1 - rate)

    def fee(self, notional: float) -> float:
        return notional * self.fee_bps / 10_000


class BarStrategy(Protocol):
    """Receives each bar after it closes. Orders fill on a later bar."""

    def on_bar(self, bar: Candle, portfolio: PortfolioSnapshot) -> Sequence[OrderRequest]: ...


@dataclass(frozen=True)
class Fill:
    time_ms: int
    submitted_ms: int
    symbol: str
    side: Side
    quantity: float
    reference_price: float  # before slippage
    price: float
    fee: float
    reason: FillReason


@dataclass(frozen=True)
class Rejection:
    time_ms: int
    order: OrderRequest
    reason: str


@dataclass(frozen=True)
class Trade:
    """A sale matched against the average cost of the position, fees included."""

    symbol: str
    entry_ms: int
    exit_ms: int
    quantity: float
    cost: float
    proceeds: float

    @property
    def net_pnl(self) -> float:
        return self.proceeds - self.cost


@dataclass(frozen=True)
class EquityPoint:
    time_ms: int  # bar close time
    equity: float
    cash: float


@dataclass(frozen=True)
class BacktestResult:
    timeframe: str
    dataset_ids: tuple[str, ...]
    costs: CostModel
    initial_cash: float
    equity_curve: tuple[EquityPoint, ...]
    fills: tuple[Fill, ...]
    trades: tuple[Trade, ...]
    rejections: tuple[Rejection, ...]
    unfilled: tuple[OrderRequest, ...]
    open_positions: Mapping[str, float]
    fees_paid: float
    slippage_paid: float

    @property
    def final_equity(self) -> float:
        return self.equity_curve[-1].equity if self.equity_curve else self.initial_cash

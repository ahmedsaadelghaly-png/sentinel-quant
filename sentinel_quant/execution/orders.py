"""Order and portfolio types shared by backtest, risk and execution."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum


class OrderError(ValueError):
    """An order is malformed."""


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    MARKET = "market"
    STOP = "stop"  # sell stop only: spot has no shorting


@dataclass(frozen=True)
class OrderRequest:
    """A strategy's intent.

    ``stop_price`` on a market buy is a protective stop, armed when the buy fills.
    On a STOP sell it is the trigger.
    """

    symbol: str
    side: Side
    quantity: float
    order_type: OrderType = OrderType.MARKET
    stop_price: float | None = None

    def __post_init__(self) -> None:
        if not math.isfinite(self.quantity) or self.quantity <= 0:
            raise OrderError(f"quantity must be positive: {self.quantity}")
        if self.stop_price is not None and (
            not math.isfinite(self.stop_price) or self.stop_price <= 0
        ):
            raise OrderError(f"stop_price must be positive: {self.stop_price}")
        if self.order_type is OrderType.STOP and (
            self.side is not Side.SELL or self.stop_price is None
        ):
            raise OrderError("a stop order must be a sell with a stop_price")
        if self.order_type is OrderType.MARKET and self.side is Side.SELL and self.stop_price:
            raise OrderError("a market sell cannot carry a stop_price")


@dataclass(frozen=True)
class PortfolioSnapshot:
    """Read-only view handed to strategies and the risk engine."""

    time_ms: int  # open time of the bar being processed
    as_of_ms: int  # the moment the decision is made: that bar's close
    cash: float
    equity: float
    positions: Mapping[str, float]
    marks: Mapping[str, float]
    stops: tuple[OrderRequest, ...] = field(default=())  # resting protective stops
    pending: tuple[OrderRequest, ...] = field(default=())  # approved, not yet filled

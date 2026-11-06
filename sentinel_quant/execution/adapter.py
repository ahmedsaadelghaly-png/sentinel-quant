"""Common execution interface (MASTER_PLAN §3.2). Sim and testnet only: no live adapter."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from sentinel_quant.data.live import Candle
from sentinel_quant.execution.orders import OrderRequest, Side


class ExecutionError(RuntimeError):
    """The venue could not be reached or refused to confirm an operation."""


@dataclass(frozen=True)
class FillReport:
    fill_id: str  # stable, so applying a report twice is harmless
    client_id: str
    symbol: str
    side: Side
    quantity: float
    price: float
    fee: float  # in quote currency
    time_ms: int
    reason: str


@dataclass(frozen=True)
class RejectReport:
    client_id: str
    reason: str


@dataclass(frozen=True)
class Balances:
    cash: float | None  # None when the venue's cash is not comparable to the ledger's
    positions: Mapping[str, float]


class ExecutionAdapter(Protocol):
    def place(self, client_id: str, order: OrderRequest, signal_ms: int) -> None:
        """Send an order decided on the bar opening at ``signal_ms``.

        Repeating a ``client_id`` must not create a second order.
        """

    def on_bar(self, bar: Candle) -> None:
        """Offer a closed bar to the venue. Only the simulator needs it."""

    def poll(self) -> tuple[list[FillReport], list[RejectReport]]:
        """Fills and rejections since the last poll. Duplicates are allowed."""

    def balances(self) -> Balances: ...

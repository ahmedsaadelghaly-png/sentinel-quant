"""The contract every order path must go through."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sentinel_quant.execution.orders import OrderRequest, PortfolioSnapshot


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    reason: str = ""


class RiskGate(Protocol):
    """Pre-trade veto, implemented by ``RiskEngine``."""

    @property
    def flatten_required(self) -> bool:
        """True when open positions must be closed now."""

    def observe(self, portfolio: PortfolioSnapshot) -> None:
        """Called once per closed bar, before any order is considered."""

    def check(self, order: OrderRequest, portfolio: PortfolioSnapshot) -> RiskDecision: ...

    def on_trade_closed(self, net_pnl: float) -> None:
        """Called when a sale realises a profit or a loss."""

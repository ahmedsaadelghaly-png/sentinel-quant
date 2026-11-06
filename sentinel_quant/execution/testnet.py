"""Exchange testnet adapter (ccxt sandbox).

Refuses to exist unless it is really talking to a testnet: there is no way to point this
class at a live exchange. Testnet prices differ from the mainnet candles that drive
signals, so a protective stop keeps its distance from the actual fill price.
"""

from __future__ import annotations

import contextlib
from typing import Any

import ccxt

from sentinel_quant.config.schema import AppConfig, TradingMode
from sentinel_quant.config.secrets import Secrets
from sentinel_quant.data.live import Candle
from sentinel_quant.execution.adapter import (
    Balances,
    ExecutionError,
    FillReport,
    RejectReport,
)
from sentinel_quant.execution.orders import OrderRequest, Side
from sentinel_quant.ops.logging import get_logger


def build_testnet_exchange(cfg: AppConfig, secrets: Secrets) -> Any:
    if cfg.mode is not TradingMode.PAPER or not cfg.exchange.testnet:
        raise ExecutionError("the testnet adapter needs mode=paper and exchange.testnet=true")
    if secrets.exchange_api_key is None or secrets.exchange_api_secret is None:
        raise ExecutionError("paper mode needs SQ_EXCHANGE_API_KEY and SQ_EXCHANGE_API_SECRET")
    exchange = getattr(ccxt, cfg.exchange.name)(
        {
            "apiKey": secrets.exchange_api_key.get_secret_value(),
            "secret": secrets.exchange_api_secret.get_secret_value(),
            "enableRateLimit": True,
            "options": {"defaultType": "spot", "fetchMarkets": {"types": ["spot"]}},
        }
    )
    exchange.set_sandbox_mode(True)
    return exchange


class TestnetAdapter:
    __test__ = False  # not a pytest class, despite the name

    def __init__(
        self,
        exchange: Any,
        symbols: tuple[str, ...],
        marks: dict[str, float],
        state: dict[str, Any] | None = None,
    ) -> None:
        if "testnet" not in str(exchange.urls["api"]).lower():
            raise ExecutionError("refusing to trade: exchange is not a testnet")
        self._exchange = exchange
        self._symbols = symbols
        self._marks = marks  # live view of the loop's latest mainnet closes
        # Persisted: a new baseline after a restart would hide or invent positions.
        self._start: dict[str, float] = state["start"] if state else self._base_balances()
        self._since_ms = int(state["since_ms"]) if state else int(exchange.milliseconds())
        self._own_orders: dict[str, str] = {}  # exchange order id -> client id
        self._rejects: list[RejectReport] = []
        self._log = get_logger()

    def bind_marks(self, marks: dict[str, float]) -> None:
        self._marks = marks

    def to_state(self) -> dict[str, Any]:
        return {"start": self._start, "since_ms": self._since_ms}

    def _base_balances(self) -> dict[str, float]:
        totals = self._exchange.fetch_balance()["total"]
        return {s: float(totals.get(s.split("/")[0], 0.0) or 0.0) for s in self._symbols}

    def on_bar(self, bar: Candle) -> None:
        pass  # the exchange matches orders itself

    def place(self, client_id: str, order: OrderRequest, signal_ms: int) -> None:
        if self._already_sent(client_id, order.symbol):
            return
        try:
            if order.side is Side.BUY:
                self._buy(client_id, order)
            else:
                self._sell(client_id, order)
        except ccxt.InvalidOrder as exc:
            self._rejects.append(RejectReport(client_id, str(exc)))
        except ccxt.InsufficientFunds as exc:
            self._rejects.append(RejectReport(client_id, str(exc)))
        except ccxt.BaseError as exc:
            raise ExecutionError(str(exc)) from exc

    def _already_sent(self, client_id: str, symbol: str) -> bool:
        try:
            found = self._exchange.fetch_order(None, symbol, {"origClientOrderId": client_id})
        except ccxt.OrderNotFound:
            return False
        except ccxt.BaseError as exc:
            # Not knowing whether it exists is a reason not to send it again.
            raise ExecutionError(f"cannot confirm order state: {exc}") from exc
        self._own_orders[str(found["id"])] = client_id
        return True

    def _market(self, client_id: str, order: OrderRequest, quantity: float) -> Any:
        amount = float(self._exchange.amount_to_precision(order.symbol, quantity))
        placed = self._exchange.create_order(
            order.symbol,
            "market",
            order.side.value,
            amount,
            None,
            {"newClientOrderId": client_id},
        )
        self._own_orders[str(placed["id"])] = client_id
        return placed

    def _buy(self, client_id: str, order: OrderRequest) -> None:
        placed = self._market(client_id, order, order.quantity)
        if order.stop_price is None:
            return
        fill_price = float(placed.get("average") or placed.get("price") or 0.0)
        mark = self._marks.get(order.symbol, 0.0)
        if fill_price <= 0 or mark <= 0:
            self._emergency_exit(client_id, order, "no fill price to place the stop")
            return
        stop = fill_price - (mark - order.stop_price)
        try:
            self._place_stop(client_id, order, placed, stop)
        except ccxt.BaseError as exc:
            self._emergency_exit(client_id, order, str(exc))

    def _place_stop(self, client_id: str, order: OrderRequest, placed: Any, stop: float) -> None:
        amount = float(placed.get("filled") or order.quantity)
        price = float(self._exchange.price_to_precision(order.symbol, stop))
        limit = float(self._exchange.price_to_precision(order.symbol, stop * 0.99))
        resting = self._exchange.create_order(
            order.symbol,
            "STOP_LOSS_LIMIT",
            "sell",
            float(self._exchange.amount_to_precision(order.symbol, amount)),
            limit,
            {"stopPrice": price, "newClientOrderId": f"{client_id}s"},
        )
        self._own_orders[str(resting["id"])] = f"{client_id}s"

    def _emergency_exit(self, client_id: str, order: OrderRequest, why: str) -> None:
        """A position with no stop is not allowed to exist: close it immediately."""
        self._log.error("stop_failed_closing_position", symbol=order.symbol, error=why)
        exit_order = OrderRequest(order.symbol, Side.SELL, order.quantity)
        self._market(f"{client_id}x", exit_order, order.quantity)

    def _sell(self, client_id: str, order: OrderRequest) -> None:
        # Resting stops lock the balance, so they must go before a market exit.
        with contextlib.suppress(ccxt.OrderNotFound):  # Binance's answer if nothing was open
            self._exchange.cancel_all_orders(order.symbol)
        self._market(client_id, order, order.quantity)

    def poll(self) -> tuple[list[FillReport], list[RejectReport]]:
        fills: list[FillReport] = []
        for symbol in self._symbols:
            try:
                trades = self._exchange.fetch_my_trades(symbol, since=self._since_ms)
            except ccxt.BaseError as exc:
                raise ExecutionError(f"cannot read fills: {exc}") from exc
            for trade in trades:
                if self._is_ours(trade):
                    fills.append(self._report(trade))
                    self._since_ms = max(self._since_ms, int(trade["timestamp"]))
        rejects, self._rejects = self._rejects, []
        return fills, rejects

    def _is_ours(self, trade: Any) -> bool:
        """Known order, or one this bot placed before a restart (its id says so)."""
        order_id = str(trade["order"])
        if order_id in self._own_orders:
            return True
        try:
            order = self._exchange.fetch_order(order_id, trade["symbol"])
        except ccxt.BaseError as exc:
            raise ExecutionError(f"cannot identify a fill: {exc}") from exc
        client_id = str(order.get("clientOrderId") or "")
        if not client_id.startswith("sq"):
            return False
        self._own_orders[order_id] = client_id
        return True

    def _report(self, trade: Any) -> FillReport:
        price = float(trade["price"])
        fee = trade.get("fee") or {}
        fee_cost = float(fee.get("cost") or 0.0)
        symbol = str(trade["symbol"])
        if fee.get("currency") == symbol.split("/")[0]:
            fee_cost *= price  # charged in the base asset: convert to quote
        return FillReport(
            fill_id=str(trade["id"]),
            client_id=self._own_orders[str(trade["order"])],
            symbol=symbol,
            side=Side(trade["side"]),
            quantity=float(trade["amount"]),
            price=price,
            fee=fee_cost,
            time_ms=int(trade["timestamp"]),
            reason="exchange",
        )

    def balances(self) -> Balances:
        """Base asset changes since start. Testnet accounts hold unrelated funds."""
        try:
            current = self._base_balances()
        except ccxt.BaseError as exc:
            raise ExecutionError(f"cannot read balances: {exc}") from exc
        changes = {s: current[s] - self._start[s] for s in self._symbols}
        return Balances(None, {s: q for s, q in changes.items() if abs(q) > 1e-9})

"""The automated loop: closed bar -> signal -> risk check -> order -> fill -> ledger.

Each timestamp follows the same order as the backtester. Every order, including a forced
flatten, passes the risk engine. After a crash, deterministic client ids and the ledger
make replaying a bar safe.
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Callable, Sequence
from itertools import groupby
from pathlib import Path
from types import MappingProxyType
from typing import Protocol

from sentinel_quant.config.schema import DailyControls
from sentinel_quant.data.client import MarketDataError
from sentinel_quant.data.live import Candle, ClosedCandlePoller
from sentinel_quant.data.timeframes import timeframe_ms
from sentinel_quant.execution.adapter import ExecutionAdapter, ExecutionError
from sentinel_quant.execution.orders import OrderRequest, PortfolioSnapshot, Side
from sentinel_quant.ledger.store import Ledger
from sentinel_quant.ops.logging import get_logger
from sentinel_quant.risk.engine import RiskEngine
from sentinel_quant.risk.kill_switch import KillSwitch
from sentinel_quant.strategies.base import SizedStrategy

_RECONCILE_TOLERANCE = 1e-6
_MAX_BAR_AGE_BARS = 2  # older than this, a signal is history and must not be traded
_ALERT_AFTER_FAILURES = 3
_MAX_SLEEP_SECONDS = 30.0  # bounds how long a tightened limit or a stop can wait


class Notifier(Protocol):
    def send(self, level: str, message: str) -> None: ...


class TradingLoop:
    def __init__(
        self,
        *,
        mode: str,
        timeframe: str,
        strategy: SizedStrategy,
        risk: RiskEngine,
        adapter: ExecutionAdapter,
        ledger: Ledger,
        kill_switch: KillSwitch,
        notifier: Notifier,
        save_adapter: Callable[[], object] | None = None,
        on_cycle: Callable[[int], None] | None = None,
    ) -> None:
        self._mode = mode
        self._tf_ms = timeframe_ms(timeframe)
        self._strategy = strategy
        self._risk = risk
        self._adapter = adapter
        self._ledger = ledger
        self._kill_switch = kill_switch
        self._notifier = notifier
        self._save_adapter = save_adapter
        self._on_cycle = on_cycle
        self._marks: dict[str, float] = dict(ledger.get_state("marks") or {})
        self._last_bars: dict[str, int] = dict(ledger.get_state("last_bars") or {})
        self._log = get_logger()

    @property
    def last_bars(self) -> dict[str, int]:
        return dict(self._last_bars)

    @property
    def marks(self) -> dict[str, float]:
        """Latest closes. Shared on purpose: the testnet adapter reads it live."""
        return self._marks

    def apply_limits(self, limits: DailyControls, now_ms: int) -> None:
        """Bring a restored risk state in line with the config, by the stricter-now rule."""
        if limits != self._risk.limits:
            self._risk.update_limits(limits, self._snapshot(now_ms - self._tf_ms))

    def recover(self, now_ms: int) -> None:
        """Run once at start. Books are compared on the next bar, before any new order."""
        for client_id, order, signal_ms in self._ledger.open_orders():
            self._send(client_id, order, signal_ms)  # safe: repeated ids are not re-sent
        self._sync(now_ms - self._tf_ms)

    def process(self, bars: Sequence[Candle], now_ms: int) -> None:
        time_ms = bars[0].open_time_ms
        as_of = time_ms + self._tf_ms
        halt_before = self._risk.state.halt
        for bar in bars:
            self._adapter.on_bar(bar)
        self._sync(time_ms)
        self.reconcile(as_of)
        for bar in bars:
            self._marks[bar.symbol] = bar.close
        snapshot = self._snapshot(time_ms)
        self._ledger.record_equity(as_of, snapshot.equity)
        self._risk.observe(snapshot)
        if self._risk.state.halt is not halt_before and self._risk.state.halt is not None:
            detail = self._risk.state.halt.value
            self._ledger.decide(as_of, "*", "limit_hit", detail)
            self._notifier.send("warning", f"daily limit hit: {detail}")
        tradable = now_ms - as_of <= _MAX_BAR_AGE_BARS * self._tf_ms
        if self._risk.flatten_required:
            self._flatten(time_ms)
        for bar in bars:
            orders = self._strategy.on_bar(bar, self._snapshot(time_ms))
            for signal in self._strategy.signals:
                detail = f"{signal.action.value}: {signal.reason}"
                self._ledger.decide(as_of, signal.symbol, "signal", detail)
            self._strategy.signals.clear()
            for index, order in enumerate(orders):
                if tradable:
                    self._submit(order, time_ms, index)
                else:
                    detail = f"not traded, bar too old: {order.side.value}"
                    self._ledger.decide(as_of, bar.symbol, "skipped", detail)
            self._last_bars[bar.symbol] = bar.open_time_ms
        self._checkpoint()

    def _flatten(self, time_ms: int) -> None:
        pending = {o.symbol for o in self._ledger.pending() if o.side is Side.SELL}
        for symbol, quantity in self._ledger.positions().items():
            if symbol not in pending:
                self._submit(OrderRequest(symbol, Side.SELL, quantity), time_ms, 99)

    def _snapshot(self, time_ms: int) -> PortfolioSnapshot:
        positions = self._ledger.positions()
        held = sum(q * self._marks[s] for s, q in positions.items())
        return PortfolioSnapshot(
            time_ms=time_ms,
            as_of_ms=time_ms + self._tf_ms,
            cash=self._ledger.cash,
            equity=self._ledger.cash + held,
            positions=MappingProxyType(positions),
            marks=MappingProxyType(dict(self._marks)),
            stops=self._ledger.stops(),
            pending=self._ledger.pending(),
        )

    def _client_id(self, order: OrderRequest, time_ms: int, index: int) -> str:
        key = f"{self._mode}|{order.symbol}|{order.side}|{time_ms}|{index}"
        return "sq" + hashlib.sha256(key.encode()).hexdigest()[:24]

    def _submit(self, order: OrderRequest, time_ms: int, index: int) -> None:
        as_of = time_ms + self._tf_ms
        client_id = self._client_id(order, time_ms, index)
        if self._ledger.has_order(client_id):
            return  # replay after a crash: this order was already decided
        decision = self._risk.check(order, self._snapshot(time_ms))
        if not decision.approved:
            detail = f"{order.side.value} refused: {decision.reason}"
            self._ledger.decide(as_of, order.symbol, "rejected", detail)
            return
        self._ledger.record_intent(client_id, order, time_ms)
        self._ledger.set_state({"risk": self._risk.state.model_dump(mode="json")})
        detail = f"{order.side.value} {order.quantity:.8f}"
        if order.stop_price is not None:
            detail += f", stop {order.stop_price:.2f}"
        self._ledger.decide(as_of, order.symbol, "approved", detail)
        self._send(client_id, order, time_ms)

    def _send(self, client_id: str, order: OrderRequest, signal_ms: int) -> None:
        try:
            self._adapter.place(client_id, order, signal_ms)
        except ExecutionError as exc:
            # Stays 'new', so recovery resends it under the same id.
            as_of = signal_ms + self._tf_ms
            self._ledger.decide(as_of, order.symbol, "send_failed", str(exc))
            self._notifier.send("error", f"order not confirmed: {order.symbol}: {exc}")
            return
        self._ledger.set_status(client_id, "open")

    def _sync(self, time_ms: int) -> None:
        fills, rejects = self._adapter.poll()
        for fill in fills:
            if self._ledger.apply_fill(fill, self._on_booked):
                self._ledger.decide(
                    fill.time_ms + self._tf_ms,
                    fill.symbol,
                    "fill",
                    f"{fill.side.value} {fill.quantity:.8f} at {fill.price} ({fill.reason})",
                )
        for reject in rejects:
            self._ledger.set_status(reject.client_id, "rejected", reject.reason)
            self._ledger.decide(time_ms + self._tf_ms, "*", "venue_rejected", reject.reason)

    def _apply_requested_limits(self, now_ms: int) -> None:
        """Pick up a change from the control panel, by the stricter-now rule."""
        requested = self._ledger.get_state("requested_limits")
        if requested is None:
            return
        self.apply_limits(DailyControls.model_validate(requested), now_ms)
        self._ledger.set_state(
            {"requested_limits": None, "risk": self._risk.state.model_dump(mode="json")}
        )

    def _on_booked(self, net_pnl: float | None) -> dict[str, object]:
        if net_pnl is None:
            return {}
        self._risk.on_trade_closed(net_pnl)
        return {"risk": self._risk.state.model_dump(mode="json")}

    def reconcile(self, as_of: int) -> bool:
        """Compare ledger and venue. A difference stops all trading until a person looks."""
        try:
            venue = self._adapter.balances()
        except ExecutionError as exc:
            self._log.warning("reconciliation_skipped", error=str(exc))
            return False
        problems: list[str] = []
        ours = self._ledger.positions()
        for symbol in set(ours) | set(venue.positions):
            a, b = ours.get(symbol, 0.0), venue.positions.get(symbol, 0.0)
            if abs(a - b) > _RECONCILE_TOLERANCE:
                problems.append(f"{symbol}: ledger {a}, venue {b}")
        if venue.cash is not None and abs(venue.cash - self._ledger.cash) > _RECONCILE_TOLERANCE:
            problems.append(f"cash: ledger {self._ledger.cash}, venue {venue.cash}")
        if not problems:
            return True
        detail = "; ".join(sorted(problems))
        self._ledger.decide(as_of, "*", "reconciliation_failed", detail)
        self._kill_switch.engage(f"reconciliation: {detail}")
        self._notifier.send("critical", f"reconciliation failed, kill switch on: {detail}")
        return False

    def _checkpoint(self) -> None:
        values: dict[str, object] = {
            "risk": self._risk.state.model_dump(mode="json"),
            "last_bars": self._last_bars,
            "marks": self._marks,
        }
        if self._save_adapter is not None:
            values["adapter"] = self._save_adapter()
        self._ledger.set_state(values)

    def run(
        self, poller: ClosedCandlePoller, now: Callable[[], int], stop: threading.Event
    ) -> None:
        """Service loop: survives outages and exits when ``stop`` is set.

        A bar that could not be processed stays in the backlog. The poller has already
        moved past it, so dropping it would silently skip a bar.
        """
        failures = 0
        backlog: list[list[Candle]] = []
        while not stop.is_set():
            try:
                current = now()
                self._ledger.set_state({"heartbeat_ms": current})
                ordered = sorted(poller.poll_once(), key=lambda c: (c.open_time_ms, c.symbol))
                backlog.extend(list(g) for _, g in groupby(ordered, key=lambda c: c.open_time_ms))
                while backlog:
                    self.process(backlog[0], current)
                    backlog.pop(0)
                self._apply_requested_limits(current)
                failures = 0
                if self._on_cycle is not None:
                    self._on_cycle(current)
            except (MarketDataError, ExecutionError) as exc:
                failures += 1
                self._log.warning("service_degraded", failures=failures, error=str(exc))
                if failures == _ALERT_AFTER_FAILURES:
                    self._notifier.send("error", f"exchange connection problem: {exc}")
            stop.wait(min(poller.wait_seconds, _MAX_SLEEP_SECONDS))


def stop_file_watcher(path: Path, stop: threading.Event) -> None:
    """Set ``stop`` when the operator's stop file appears (used by the control panel)."""
    while not stop.wait(1.0):
        if path.exists():
            path.unlink(missing_ok=True)
            stop.set()

"""Daily risk controller (MASTER_PLAN §1.2).

Rules that shape this module:

- Entries are judged on projected worst-case loss: equity, minus what every open and
  pending position loses at its stop, minus this order's own stop loss. A position
  with no stop counts as losing its full value.
- A market gap can jump a stop and lose more than the projection, so the daily limit
  is a limit on planned risk. ``flatten_required`` covers realised breaches.
- The profit lock only ever stops trading. Nothing here sizes up or trades more.
- Exits are always allowed, except by the kill switch: it blocks everything.
- State is serialisable, because a restart must not reset the day's limits.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, ValidationError

from sentinel_quant.config.schema import DailyControls
from sentinel_quant.execution.orders import OrderRequest, OrderType, PortfolioSnapshot, Side
from sentinel_quant.ops.logging import get_logger
from sentinel_quant.risk.gate import RiskDecision
from sentinel_quant.risk.kill_switch import KillSwitch

_DAY_MS = 86_400_000
_TOLERANCE = 1e-9  # sized orders land exactly on a limit: rounding must not reject them


class Halt(StrEnum):
    """Why new entries stopped for the rest of the day."""

    DAILY_LOSS = "daily_loss_limit"
    CONSECUTIVE_LOSSES = "max_consecutive_losses"
    PROFIT_LOCK = "daily_profit_lock"


class RiskState(BaseModel):
    """Everything that must survive a restart."""

    model_config = ConfigDict(extra="forbid")

    day: int | None = None
    day_start_equity: float = 0.0
    entries_today: int = 0
    consecutive_losses: int = 0
    halt: Halt | None = None
    limits: DailyControls
    next_limits: DailyControls | None = None


@dataclass(frozen=True)
class RiskEvent:
    time_ms: int
    code: str
    detail: str


def _ms_of_day(value: time) -> int:
    return (value.hour * 3600 + value.minute * 60 + value.second) * 1000


class RiskEngine:
    def __init__(
        self,
        limits: DailyControls,
        kill_switch: KillSwitch,
        state: RiskState | None = None,
    ) -> None:
        self.state = state or RiskState(limits=limits)
        self._kill_switch = kill_switch
        self.events: list[RiskEvent] = []
        self._last_ms = 0
        self._log = get_logger()

    @property
    def limits(self) -> DailyControls:
        return self.state.limits

    @property
    def flatten_required(self) -> bool:
        """The hard daily stop was hit: open positions must be closed."""
        return self.state.halt is Halt.DAILY_LOSS

    def observe(self, portfolio: PortfolioSnapshot) -> None:
        self._roll_day(portfolio)
        self._last_ms = portfolio.as_of_ms
        limits, state = self.limits, self.state
        if state.day_start_equity <= 0 or state.halt is Halt.DAILY_LOSS:
            return
        change_pct = 100 * (portfolio.equity / state.day_start_equity - 1)
        # Checked even during a softer halt: only this one forces positions closed.
        if change_pct <= -limits.max_daily_loss_pct:
            self._halt(Halt.DAILY_LOSS, f"day change {change_pct:.3f}%")
            return
        lock = limits.daily_profit_lock_pct
        if state.halt is None and lock is not None and change_pct >= lock:
            self._halt(Halt.PROFIT_LOCK, f"day change {change_pct:.3f}%")

    def on_trade_closed(self, net_pnl: float) -> None:
        state = self.state
        state.consecutive_losses = state.consecutive_losses + 1 if net_pnl < 0 else 0
        if state.halt is None and state.consecutive_losses >= self.limits.max_consecutive_losses:
            self._halt(Halt.CONSECUTIVE_LOSSES, f"{state.consecutive_losses} in a row")

    def check(self, order: OrderRequest, portfolio: PortfolioSnapshot) -> RiskDecision:
        if self._kill_switch.engaged():
            return self._reject(portfolio, "kill_switch")
        self.observe(portfolio)
        if order.side is Side.SELL:
            return RiskDecision(True)  # reducing risk is always allowed
        reason = self._entry_veto(order, portfolio)
        if reason:
            return self._reject(portfolio, reason)
        self.state.entries_today += 1
        return RiskDecision(True)

    def size(self, entry_price: float, stop_price: float, portfolio: PortfolioSnapshot) -> float:
        """Largest quantity that risks ``risk_per_trade_pct`` and fits the exposure cap.

        Depends only on equity and stop distance, never on progress towards a target.
        """
        distance = entry_price - stop_price
        if distance <= 0 or entry_price <= 0 or portfolio.equity <= 0:
            return 0.0
        by_risk = portfolio.equity * self.limits.risk_per_trade_pct / 100 / distance
        room = portfolio.equity * self.limits.max_total_exposure_pct / 100 - _exposure(portfolio)
        return max(min(by_risk, room / entry_price, portfolio.cash / entry_price), 0.0)

    def update_limits(self, new: DailyControls, portfolio: PortfolioSnapshot) -> None:
        """Stricter values apply now. Anything looser waits for the next daily reset."""
        current = self.limits
        start = max(current.trading_window_utc[0], new.trading_window_utc[0])
        end = min(current.trading_window_utc[1], new.trading_window_utc[1])
        self.state.next_limits = new
        try:
            self.state.limits = DailyControls(
                risk_per_trade_pct=min(current.risk_per_trade_pct, new.risk_per_trade_pct),
                max_daily_loss_pct=min(current.max_daily_loss_pct, new.max_daily_loss_pct),
                max_daily_trades=min(current.max_daily_trades, new.max_daily_trades),
                max_open_positions=min(current.max_open_positions, new.max_open_positions),
                max_total_exposure_pct=min(
                    current.max_total_exposure_pct, new.max_total_exposure_pct
                ),
                max_consecutive_losses=min(
                    current.max_consecutive_losses, new.max_consecutive_losses
                ),
                daily_profit_lock_pct=_stricter_lock(
                    current.daily_profit_lock_pct, new.daily_profit_lock_pct
                ),
                trading_window_utc=(start, end),
                reset_time_utc=current.reset_time_utc,
            )
        except ValidationError:
            # The old and new windows do not overlap: nothing to apply until the reset.
            self._event(portfolio.as_of_ms, "limits_deferred", "windows do not overlap")
            return
        self._event(portfolio.as_of_ms, "limits_updated", "stricter values applied")
        self.observe(portfolio)

    def _roll_day(self, portfolio: PortfolioSnapshot) -> None:
        state = self.state
        offset = _ms_of_day(self.limits.reset_time_utc)
        day = (portfolio.as_of_ms - offset) // _DAY_MS
        if state.day == day:
            return
        if state.next_limits is not None:
            state.limits = state.next_limits
            state.next_limits = None
        state.day = day
        state.day_start_equity = portfolio.equity
        state.entries_today = 0
        state.consecutive_losses = 0
        state.halt = None
        self._event(portfolio.as_of_ms, "day_reset", f"equity {portfolio.equity:.2f}")

    def _entry_veto(self, order: OrderRequest, portfolio: PortfolioSnapshot) -> str | None:
        limits, state = self.limits, self.state
        if state.halt is not None:
            return state.halt.value
        if not self._in_window(portfolio.as_of_ms):
            return "outside_trading_window"
        if state.entries_today >= limits.max_daily_trades:
            return "max_daily_trades"
        mark = portfolio.marks.get(order.symbol)
        if mark is None:
            return "no_price"
        if order.stop_price is None:
            return "no_stop"
        if order.stop_price >= mark:
            return "stop_not_below_price"

        symbols = set(portfolio.positions) | {
            o.symbol for o in portfolio.pending if o.side is Side.BUY
        }
        if order.symbol not in symbols and len(symbols) >= limits.max_open_positions:
            return "max_open_positions"

        equity = portfolio.equity
        order_risk = order.quantity * (mark - order.stop_price)
        if order_risk > equity * limits.risk_per_trade_pct / 100 * (1 + _TOLERANCE):
            return "risk_per_trade"
        exposure = _exposure(portfolio) + order.quantity * mark
        if exposure > equity * limits.max_total_exposure_pct / 100 * (1 + _TOLERANCE):
            return "max_total_exposure"
        worst_case = equity - _open_risk(portfolio) - order_risk
        allowed = state.day_start_equity * (1 - limits.max_daily_loss_pct / 100)
        if worst_case < allowed * (1 - _TOLERANCE):
            return "projected_daily_loss"
        return None

    def _in_window(self, as_of_ms: int) -> bool:
        now = datetime.fromtimestamp(as_of_ms / 1000, tz=UTC).time()
        start, end = self.limits.trading_window_utc
        return start <= now <= end

    def _halt(self, halt: Halt, detail: str) -> None:
        self.state.halt = halt
        self._event(self._last_ms, f"halt_{halt.value}", detail)

    def _reject(self, portfolio: PortfolioSnapshot, reason: str) -> RiskDecision:
        self._event(portfolio.as_of_ms, "order_rejected", reason)
        return RiskDecision(False, reason)

    def _event(self, time_ms: int, code: str, detail: str) -> None:
        self.events.append(RiskEvent(time_ms, code, detail))
        self._log.info("risk_event", code=code, detail=detail, time_ms=time_ms)


def _stricter_lock(current: float | None, new: float | None) -> float | None:
    """A lower lock stops sooner. Removing the lock is the looser direction."""
    if current is None:
        return new
    return current if new is None else min(current, new)


def _exposure(portfolio: PortfolioSnapshot) -> float:
    held = sum(q * portfolio.marks[s] for s, q in portfolio.positions.items())
    pending = sum(
        o.quantity * portfolio.marks.get(o.symbol, 0.0)
        for o in portfolio.pending
        if o.side is Side.BUY
    )
    return held + pending


def _open_risk(portfolio: PortfolioSnapshot) -> float:
    """What open and pending positions lose if every stop fills exactly at its price."""
    risk = 0.0
    for symbol, quantity in portfolio.positions.items():
        mark = portfolio.marks[symbol]
        uncovered = quantity
        for stop in sorted(
            (o for o in portfolio.stops if o.symbol == symbol),
            key=lambda o: -(o.stop_price or 0.0),
        ):
            covered = min(stop.quantity, uncovered)
            risk += covered * max(mark - (stop.stop_price or 0.0), 0.0)
            uncovered -= covered
        risk += uncovered * mark  # no stop: the whole value is at risk
    for order in portfolio.pending:
        if order.side is Side.BUY and order.order_type is OrderType.MARKET:
            mark = portfolio.marks.get(order.symbol, 0.0)
            risk += order.quantity * max(mark - (order.stop_price or 0.0), 0.0)
    return risk

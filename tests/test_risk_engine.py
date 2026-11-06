import ast
import random
from collections.abc import Sequence
from datetime import UTC, datetime, time
from pathlib import Path
from typing import Any

import pytest
from conftest import HOUR_MS
from test_backtest_engine import COSTS, SYMBOL

from sentinel_quant.backtest.engine import run_backtest
from sentinel_quant.backtest.models import CostModel, FillReason
from sentinel_quant.config import DailyControls
from sentinel_quant.data.live import Candle
from sentinel_quant.execution.orders import OrderRequest, OrderType, PortfolioSnapshot, Side
from sentinel_quant.risk.engine import Halt, RiskEngine, RiskState
from sentinel_quant.risk.kill_switch import KillSwitch

ROOT = Path(__file__).resolve().parents[1]
NOON = int(datetime(2024, 1, 10, 12, tzinfo=UTC).timestamp() * 1000)
DAY_MS = 24 * HOUR_MS
LIMITS = DailyControls()


@pytest.fixture
def switch(tmp_path: Path) -> KillSwitch:
    return KillSwitch(tmp_path / "KILL")


def snap(equity: float = 10_000.0, as_of: int = NOON, **kwargs: Any) -> PortfolioSnapshot:
    base: dict[str, Any] = {
        "time_ms": as_of - HOUR_MS,
        "as_of_ms": as_of,
        "cash": equity,
        "equity": equity,
        "positions": {},
        "marks": {SYMBOL: 100.0, "ETH/USDT": 100.0, "SOL/USDT": 100.0, "XRP/USDT": 100.0},
    }
    return PortfolioSnapshot(**{**base, **kwargs})


def entry(quantity: float = 5.0, stop: float | None = 99.0, symbol: str = SYMBOL) -> OrderRequest:
    return OrderRequest(symbol, Side.BUY, quantity, stop_price=stop)


def engine(switch: KillSwitch, **limits: Any) -> RiskEngine:
    risk = RiskEngine(DailyControls(**limits), switch)
    risk.observe(snap())
    return risk


def reason(risk: RiskEngine, order: OrderRequest, portfolio: PortfolioSnapshot) -> str:
    return risk.check(order, portfolio).reason


def test_valid_entry_is_approved(switch: KillSwitch) -> None:
    assert engine(switch).check(entry(), snap()).approved


def test_kill_switch_blocks_everything_including_exits(switch: KillSwitch) -> None:
    risk = engine(switch)
    switch.engage("test")
    assert reason(risk, entry(), snap()) == "kill_switch"
    assert reason(risk, OrderRequest(SYMBOL, Side.SELL, 1.0), snap()) == "kill_switch"
    switch.release()
    assert risk.check(entry(), snap()).approved


def test_kill_switch_survives_a_new_process(tmp_path: Path) -> None:
    KillSwitch(tmp_path / "KILL").engage("operator")
    assert KillSwitch(tmp_path / "KILL").engaged()


def test_unreadable_kill_switch_fails_closed(
    switch: KillSwitch, monkeypatch: pytest.MonkeyPatch
) -> None:
    def denied(*_args: Any, **_kwargs: Any) -> None:
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "stat", denied)
    assert switch.engaged()


def test_kill_switch_path_does_not_depend_on_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    switch = KillSwitch("runs/KILL")
    (tmp_path / "other").mkdir()
    monkeypatch.chdir(tmp_path / "other")
    switch.engage("x")
    assert (tmp_path / "runs/KILL").exists()


def test_entry_without_a_stop_is_refused(switch: KillSwitch) -> None:
    assert reason(engine(switch), entry(stop=None), snap()) == "no_stop"


def test_stop_at_or_above_price_is_refused(switch: KillSwitch) -> None:
    assert reason(engine(switch), entry(stop=100.0), snap()) == "stop_not_below_price"


def test_unknown_price_is_refused(switch: KillSwitch) -> None:
    assert reason(engine(switch), entry(symbol="NEW/USDT"), snap()) == "no_price"


def test_risk_per_trade_boundary(switch: KillSwitch) -> None:
    # 0.5% of 10,000 = 50. A stop 1 away allows 50 units, if exposure permits.
    risk = engine(switch, max_total_exposure_pct=100.0)
    assert risk.check(entry(50.0), snap()).approved
    assert reason(engine(switch), entry(50.01), snap()) == "risk_per_trade"


def test_exposure_cap_counts_positions_and_pending(switch: KillSwitch) -> None:
    held = snap(positions={"ETH/USDT": 30.0}, stops=(_stop("ETH/USDT", 30.0, 99.0),))
    assert reason(engine(switch), entry(25.0, 99.0), held) == "max_total_exposure"
    pending = snap(pending=(entry(30.0, 99.0, "ETH/USDT"),))
    assert reason(engine(switch), entry(25.0, 99.0), pending) == "max_total_exposure"
    assert engine(switch).check(entry(20.0, 99.0), held).approved


def _stop(symbol: str, quantity: float, price: float) -> OrderRequest:
    return OrderRequest(symbol, Side.SELL, quantity, OrderType.STOP, price)


def test_max_open_positions_counts_pending_entries(switch: KillSwitch) -> None:
    risk = engine(switch, max_open_positions=2)
    held = snap(
        positions={"ETH/USDT": 1.0},
        stops=(_stop("ETH/USDT", 1.0, 99.0),),
        pending=(entry(1.0, 99.0, "SOL/USDT"),),
    )
    assert reason(risk, entry(1.0), held) == "max_open_positions"
    assert risk.check(entry(1.0, symbol="ETH/USDT"), held).approved


def test_max_daily_trades_counts_entries_only(switch: KillSwitch) -> None:
    risk = engine(switch, max_daily_trades=2)
    assert risk.check(entry(1.0), snap()).approved
    assert risk.check(OrderRequest(SYMBOL, Side.SELL, 1.0), snap()).approved
    assert risk.check(entry(1.0), snap()).approved
    assert reason(risk, entry(1.0), snap()) == "max_daily_trades"


def test_projected_loss_includes_open_stops_before_any_loss_happens(switch: KillSwitch) -> None:
    # Limit: 2% of 10,000 = 200. Open stops already risk 180, so only 20 remains.
    risk = engine(switch, max_total_exposure_pct=100.0)
    open_book = snap(
        positions={"ETH/USDT": 45.0},
        stops=(_stop("ETH/USDT", 45.0, 96.0),),
    )
    assert risk.check(entry(20.0, 99.0), open_book).approved
    assert reason(risk, entry(21.0, 99.0), open_book) == "projected_daily_loss"


def test_position_without_a_stop_counts_as_total_loss(switch: KillSwitch) -> None:
    naked = snap(positions={"ETH/USDT": 1.0})
    assert engine(switch).check(entry(1.0), naked).approved is True
    big = snap(positions={"ETH/USDT": 3.0})
    assert reason(engine(switch), entry(1.0), big) == "projected_daily_loss"


def test_partial_stop_leaves_the_rest_at_full_risk(switch: KillSwitch) -> None:
    book = snap(positions={"ETH/USDT": 4.0}, stops=(_stop("ETH/USDT", 1.0, 99.0),))
    assert reason(engine(switch), entry(1.0), book) == "projected_daily_loss"


def test_pending_entry_counts_towards_projected_loss(switch: KillSwitch) -> None:
    book = snap(pending=(entry(45.0, 96.0, "ETH/USDT"),))
    risk = engine(switch, max_total_exposure_pct=100.0)
    assert reason(risk, entry(21.0, 99.0), book) == "projected_daily_loss"


def test_daily_loss_breach_halts_and_requires_flatten(switch: KillSwitch) -> None:
    risk = engine(switch)
    risk.observe(snap(equity=9_800.0))
    assert risk.state.halt is Halt.DAILY_LOSS
    assert risk.flatten_required
    assert reason(risk, entry(1.0), snap(equity=9_900.0)) == "daily_loss_limit"
    assert risk.check(OrderRequest(SYMBOL, Side.SELL, 1.0), snap(equity=9_800.0)).approved


def test_recovery_does_not_lift_a_halt(switch: KillSwitch) -> None:
    risk = engine(switch)
    risk.observe(snap(equity=9_700.0))
    risk.observe(snap(equity=10_500.0))
    assert risk.state.halt is Halt.DAILY_LOSS


def test_loss_breach_overrides_softer_halts(switch: KillSwitch) -> None:
    risk = engine(switch)
    risk.observe(snap(equity=10_300.0))
    assert risk.state.halt is Halt.PROFIT_LOCK
    assert not risk.flatten_required
    risk.observe(snap(equity=9_700.0))
    assert risk.state.halt is Halt.DAILY_LOSS
    assert risk.flatten_required


def test_profit_lock_stops_entries_and_never_sizes_up(switch: KillSwitch) -> None:
    risk = engine(switch)
    before = risk.size(100.0, 99.0, snap(equity=10_299.0))
    risk.observe(snap(equity=10_300.0))
    assert reason(risk, entry(1.0), snap(equity=10_300.0)) == "daily_profit_lock"
    assert not risk.flatten_required
    assert risk.check(OrderRequest(SYMBOL, Side.SELL, 1.0), snap(equity=10_300.0)).approved
    assert before <= 10_299.0 * 0.005 / 1.0


def test_profit_lock_can_be_disabled(switch: KillSwitch) -> None:
    risk = engine(switch, daily_profit_lock_pct=None)
    risk.observe(snap(equity=12_000.0))
    assert risk.state.halt is None


def test_size_does_not_depend_on_distance_to_target(switch: KillSwitch) -> None:
    """Rule 7: being behind or ahead today cannot change the size."""
    risk = RiskEngine(DailyControls(max_total_exposure_pct=100.0), switch)
    risk.observe(snap())
    fresh = risk.size(100.0, 99.0, snap(equity=10_000.0))
    risk.state.day_start_equity = 9_500.0  # now 5% "ahead" with the same equity
    risk.state.halt = None
    assert risk.size(100.0, 99.0, snap(equity=10_000.0)) == fresh
    risk.state.day_start_equity = 10_100.0  # now 1% "behind"
    assert risk.size(100.0, 99.0, snap(equity=10_000.0)) == fresh


@pytest.mark.parametrize(
    ("stop", "book", "expected"),
    [
        (98.0, {}, 25.0),  # by risk: 50 at risk / 2 per unit
        (99.9, {}, 50.0),  # by exposure: 50% of 10,000 at 100
        (98.0, {"cash": 100.0}, 1.0),  # by cash
        (99.9, {"positions": {"ETH/USDT": 30.0}}, 20.0),  # exposure already used
        (100.0, {}, 0.0),  # no stop distance
        (101.0, {}, 0.0),
        (99.9, {"positions": {"ETH/USDT": 60.0}}, 0.0),  # already over the cap
    ],
)
def test_size_is_the_tightest_of_risk_exposure_and_cash(
    switch: KillSwitch, stop: float, book: dict[str, Any], expected: float
) -> None:
    assert engine(switch).size(100.0, stop, snap(**book)) == pytest.approx(expected)


def test_a_sized_order_is_always_approved(switch: KillSwitch) -> None:
    risk = engine(switch)
    quantity = risk.size(100.0, 98.0, snap())
    assert risk.check(entry(quantity, 98.0), snap()).approved


def test_consecutive_losses_pause_the_day(switch: KillSwitch) -> None:
    risk = engine(switch, max_consecutive_losses=2, max_daily_loss_pct=9.0)
    risk.on_trade_closed(-1.0)
    risk.on_trade_closed(+1.0)
    risk.on_trade_closed(-1.0)
    assert risk.state.halt is None
    risk.on_trade_closed(-1.0)
    assert reason(risk, entry(1.0), snap()) == "max_consecutive_losses"
    assert not risk.flatten_required


def test_breakeven_trade_resets_the_loss_streak(switch: KillSwitch) -> None:
    risk = engine(switch, max_consecutive_losses=2)
    risk.on_trade_closed(-1.0)
    risk.on_trade_closed(0.0)
    assert risk.state.consecutive_losses == 0


def test_trading_window(switch: KillSwitch) -> None:
    risk = engine(switch, trading_window_utc=(time(8), time(16)))
    assert risk.check(entry(1.0), snap(as_of=NOON)).approved
    assert risk.check(entry(1.0), snap(as_of=NOON + 4 * HOUR_MS)).approved
    late = snap(as_of=NOON + 4 * HOUR_MS + 60_000)
    assert reason(risk, entry(1.0), late) == "outside_trading_window"
    assert risk.check(OrderRequest(SYMBOL, Side.SELL, 1.0), late).approved


def test_day_reset_clears_counters_and_rebases_equity(switch: KillSwitch) -> None:
    risk = engine(switch, max_daily_trades=1)
    risk.check(entry(1.0), snap())
    risk.observe(snap(equity=9_700.0))
    assert risk.state.halt is Halt.DAILY_LOSS
    tomorrow = snap(equity=9_700.0, as_of=NOON + DAY_MS)
    assert risk.check(entry(1.0), tomorrow).approved
    assert risk.state.day_start_equity == 9_700.0
    assert risk.state.halt is None


def test_reset_time_defines_the_day(switch: KillSwitch) -> None:
    risk = RiskEngine(DailyControls(reset_time_utc=time(6)), switch)
    risk.observe(snap(as_of=NOON))
    first = risk.state.day
    risk.observe(snap(as_of=NOON + 17 * HOUR_MS))  # 05:00 next day: same trading day
    assert risk.state.day == first
    risk.observe(snap(as_of=NOON + 18 * HOUR_MS))
    assert risk.state.day != first


def test_stricter_limit_applies_immediately(switch: KillSwitch) -> None:
    risk = engine(switch)
    risk.update_limits(DailyControls(max_daily_trades=1, risk_per_trade_pct=0.1), snap())
    assert risk.limits.max_daily_trades == 1
    assert reason(risk, entry(11.0), snap()) == "risk_per_trade"


def test_looser_limit_waits_for_next_day(switch: KillSwitch) -> None:
    risk = engine(switch)
    risk.update_limits(DailyControls(max_daily_loss_pct=5.0, risk_per_trade_pct=1.0), snap())
    assert risk.limits.max_daily_loss_pct == 2.0
    assert risk.limits.risk_per_trade_pct == 0.5
    risk.observe(snap(as_of=NOON + DAY_MS))
    assert risk.limits.max_daily_loss_pct == 5.0
    assert risk.limits.risk_per_trade_pct == 1.0


def test_removing_the_profit_lock_waits_for_next_day(switch: KillSwitch) -> None:
    risk = engine(switch)
    risk.update_limits(DailyControls(daily_profit_lock_pct=None), snap())
    assert risk.limits.daily_profit_lock_pct == 3.0
    risk.observe(snap(as_of=NOON + DAY_MS))
    assert risk.limits.daily_profit_lock_pct is None


def test_disjoint_window_change_is_deferred_whole(switch: KillSwitch) -> None:
    risk = engine(switch, trading_window_utc=(time(8), time(10)))
    risk.update_limits(DailyControls(trading_window_utc=(time(12), time(14))), snap())
    assert risk.limits.trading_window_utc == (time(8), time(10))
    risk.observe(snap(as_of=NOON + DAY_MS))
    assert risk.limits.trading_window_utc == (time(12), time(14))


def test_restart_cannot_reset_the_day(switch: KillSwitch) -> None:
    risk = engine(switch, max_daily_trades=1)
    risk.check(entry(1.0), snap())
    risk.observe(snap(equity=9_700.0))
    saved = risk.state.model_dump_json()

    restarted = RiskEngine(LIMITS, switch, RiskState.model_validate_json(saved))
    restarted.observe(snap(equity=9_750.0))
    assert restarted.state.halt is Halt.DAILY_LOSS
    assert restarted.state.entries_today == 1
    assert restarted.limits.max_daily_trades == 1
    assert restarted.state.day_start_equity == 10_000.0


def test_every_rejection_and_halt_is_recorded(switch: KillSwitch) -> None:
    risk = engine(switch)
    risk.check(entry(stop=None), snap())
    risk.observe(snap(equity=9_700.0))
    codes = [e.code for e in risk.events]
    assert "order_rejected" in codes
    assert "halt_daily_loss_limit" in codes
    assert all(e.time_ms > 0 for e in risk.events)


def bars_from(path: list[float], symbol: str = SYMBOL) -> list[Candle]:
    start = NOON
    return [
        Candle(symbol, "1h", start + i * HOUR_MS, p, p * 1.001, p * 0.999, p, 10.0)
        for i, p in enumerate(path)
    ]


def test_backtest_flattens_everything_after_a_daily_loss_breach(switch: KillSwitch) -> None:
    """ETH gaps through its stop for a 4% day. BTC is fine but must be closed anyway."""

    class BuyBoth:
        def on_bar(self, bar: Candle, portfolio: PortfolioSnapshot) -> Sequence[OrderRequest]:
            if bar.open_time_ms != NOON:
                return []
            return [OrderRequest(bar.symbol, Side.BUY, 40.0, stop_price=99.0)]

    bars = {
        SYMBOL: bars_from([100.0] * 6),
        "ETH/USDT": bars_from([100.0, 100.0, 90.0, 90.0, 90.0, 90.0], "ETH/USDT"),
    }
    risk = RiskEngine(DailyControls(max_total_exposure_pct=100.0), switch)
    result = run_backtest(bars, BuyBoth(), risk, CostModel(0.0, 0.0), 10_000.0)

    assert risk.state.halt is Halt.DAILY_LOSS
    assert result.open_positions == {}
    eth_exit, btc_exit = (f for f in result.fills if f.side is Side.SELL)
    assert (eth_exit.symbol, eth_exit.reason) == ("ETH/USDT", FillReason.STOP_GAP)
    assert (btc_exit.symbol, btc_exit.reason) == (SYMBOL, FillReason.MARKET)
    assert btc_exit.time_ms == NOON + 3 * HOUR_MS
    assert btc_exit.price == 100


def test_backtest_reports_closed_trades_to_the_risk_engine(switch: KillSwitch) -> None:
    class Churn:
        def on_bar(self, bar: Candle, portfolio: PortfolioSnapshot) -> Sequence[OrderRequest]:
            if portfolio.positions.get(SYMBOL):
                return [OrderRequest(SYMBOL, Side.SELL, portfolio.positions[SYMBOL])]
            return [OrderRequest(SYMBOL, Side.BUY, 1.0, stop_price=bar.close * 0.9)]

    risk = RiskEngine(DailyControls(max_consecutive_losses=2), switch)
    result = run_backtest({SYMBOL: bars_from([100.0] * 8)}, Churn(), risk, COSTS, 10_000.0)
    assert risk.state.halt is Halt.CONSECUTIVE_LOSSES
    assert len(result.trades) == 2
    assert {r.reason for r in result.rejections} == {"risk: max_consecutive_losses"}


def test_backtest_kill_switch_stops_every_order(switch: KillSwitch) -> None:
    class Trader:
        def on_bar(self, bar: Candle, portfolio: PortfolioSnapshot) -> Sequence[OrderRequest]:
            return [OrderRequest(SYMBOL, Side.BUY, 1.0, stop_price=bar.close * 0.99)]

    switch.engage("test")
    risk = RiskEngine(LIMITS, switch)
    result = run_backtest({SYMBOL: bars_from([100.0] * 10)}, Trader(), risk, COSTS, 10_000.0)
    assert result.fills == ()
    assert {r.reason for r in result.rejections} == {"risk: kill_switch"}


class Reckless:
    """Tries to break every limit: random size, many symbols, frequent entries."""

    def __init__(self, seed: int) -> None:
        self.rng = random.Random(seed)  # noqa: S311

    def on_bar(self, bar: Candle, portfolio: PortfolioSnapshot) -> Sequence[OrderRequest]:
        orders: list[OrderRequest] = []
        for _ in range(self.rng.randint(0, 3)):
            stop = bar.close * self.rng.uniform(0.9, 0.999)
            quantity = self.rng.uniform(0.01, 40.0)
            orders.append(OrderRequest(bar.symbol, Side.BUY, quantity, stop_price=stop))
        held = portfolio.positions.get(bar.symbol, 0.0)
        if held and self.rng.random() < 0.3:
            orders.append(OrderRequest(bar.symbol, Side.SELL, held))
        return orders


class Auditor(RiskEngine):
    """Records the book at each approved entry, to check limits from the outside."""

    def __init__(self, limits: DailyControls, switch: KillSwitch) -> None:
        super().__init__(limits, switch)
        self.entries_by_day: dict[int, int] = {}
        self.approved: list[tuple[OrderRequest, PortfolioSnapshot]] = []

    def check(self, order: OrderRequest, portfolio: PortfolioSnapshot) -> Any:
        decision = super().check(order, portfolio)
        if decision.approved and order.side is Side.BUY:
            day = self.state.day
            assert day is not None
            self.entries_by_day[day] = self.entries_by_day.get(day, 0) + 1
            self.approved.append((order, portfolio))
        return decision


@pytest.mark.parametrize("seed", range(8))
def test_no_limit_is_ever_breached_by_a_reckless_strategy(seed: int, switch: KillSwitch) -> None:
    rng = random.Random(seed)  # noqa: S311
    symbols = [SYMBOL, "ETH/USDT", "SOL/USDT", "XRP/USDT"]
    bars: dict[str, list[Candle]] = {}
    for symbol in symbols:
        price = 100.0
        path = []
        for _ in range(1_500):
            price *= 1 + rng.gauss(0, 0.01)
            path.append(price)
        bars[symbol] = bars_from(path, symbol)

    limits = DailyControls(max_open_positions=2, max_daily_trades=5)
    risk = Auditor(limits, switch)
    result = run_backtest(bars, Reckless(seed), risk, COSTS, 10_000.0)

    assert risk.approved, "the scenario must exercise approvals"
    assert result.rejections, "the scenario must exercise vetoes"
    assert max(risk.entries_by_day.values()) <= 5
    for order, book in risk.approved:
        mark = book.marks[order.symbol]
        assert order.stop_price is not None
        assert order.quantity * (mark - order.stop_price) <= book.equity * 0.005 * (1 + 1e-6)
        held = sum(q * book.marks[s] for s, q in book.positions.items())
        pending = sum(o.quantity * book.marks[o.symbol] for o in book.pending if o.side is Side.BUY)
        assert held + pending + order.quantity * mark <= book.equity * 0.5 * (1 + 1e-6)
        buys = {o.symbol for o in book.pending if o.side is Side.BUY}
        names = set(book.positions) | buys | {order.symbol}
        assert len(names) <= 2


def test_binary_track_does_not_import_track_m() -> None:
    forbidden = ("sentinel_quant.risk", "sentinel_quant.evaluation", "sentinel_quant.ledger")
    for path in (ROOT / "sentinel_quant/binary").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            assert not any(n.startswith(forbidden) for n in names), path

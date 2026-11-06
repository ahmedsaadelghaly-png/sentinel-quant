import random
import threading
from pathlib import Path
from typing import Any

import ccxt
import pytest
from conftest import HOUR_MS, T0, FakeExchange, hourly, make_client
from test_backtest_engine import COSTS, SYMBOL

from sentinel_quant.backtest.engine import run_backtest
from sentinel_quant.backtest.models import BacktestResult
from sentinel_quant.config import AppConfig, DailyControls, ExchangeConfig, StrategyConfig
from sentinel_quant.config.schema import TradingMode
from sentinel_quant.config.secrets import Secrets
from sentinel_quant.data.client import MarketDataError
from sentinel_quant.data.live import Candle
from sentinel_quant.execution.adapter import Balances, ExecutionError, FillReport
from sentinel_quant.execution.loop import TradingLoop
from sentinel_quant.execution.orders import OrderRequest, Side
from sentinel_quant.execution.service import build_service, ledger_path
from sentinel_quant.execution.sim import SimAdapter, SimState
from sentinel_quant.execution.testnet import TestnetAdapter, build_testnet_exchange
from sentinel_quant.ledger.store import Ledger
from sentinel_quant.risk.engine import Halt, RiskEngine, RiskState
from sentinel_quant.risk.kill_switch import KillSwitch
from sentinel_quant.strategies.base import Action, Signal, SizedStrategy, StrategyMetadata
from sentinel_quant.strategies.donchian import DonchianBreakout

ETH = "ETH/USDT"
CASH = 10_000.0
FAST = StrategyConfig(entry_lookback=5, exit_lookback=3, atr_period=3, atr_stop_multiple=1.5)
LIMITS = DailyControls(max_daily_trades=50, max_consecutive_losses=50)


class Alerts:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send(self, level: str, message: str) -> None:
        self.sent.append((level, message))


def market(seed: int, count: int, symbol: str = SYMBOL) -> list[Candle]:
    rng = random.Random(seed)  # noqa: S311
    bars: list[Candle] = []
    price = 100.0
    for index in range(count):
        close = price * (1 + rng.gauss(0.0003, 0.012))
        high = max(price, close) * (1 + abs(rng.gauss(0, 0.003)))
        low = min(price, close) * (1 - abs(rng.gauss(0, 0.003)))
        volume = 0.0 if rng.random() < 0.01 else 5.0
        bars.append(Candle(symbol, "1h", T0 + index * HOUR_MS, price, high, low, close, volume))
        price = close
    return bars


class Rig:
    """Everything build_service wires up, restorable from the ledger like a restart."""

    def __init__(self, path: Path, switch: KillSwitch, limits: DailyControls = LIMITS) -> None:
        self.ledger = Ledger(path, CASH)
        saved_risk = self.ledger.get_state("risk")
        state = RiskState.model_validate(saved_risk) if saved_risk else None
        self.risk = RiskEngine(limits, switch, state)
        saved = self.ledger.get_state("adapter")
        restored = SimState.model_validate(saved) if saved else None
        self.adapter = SimAdapter(COSTS, CASH, restored)
        self.signals = DonchianBreakout(FAST)
        self.alerts = Alerts()
        self.switch = switch
        self.risk_by_bar: dict[int, RiskState] = {}
        self.loop = TradingLoop(
            mode="sim",
            timeframe="1h",
            strategy=SizedStrategy(self.signals, self.risk),
            risk=self.risk,
            adapter=self.adapter,
            ledger=self.ledger,
            kill_switch=switch,
            notifier=self.alerts,
            save_adapter=lambda: self.adapter.to_state().model_dump(mode="json"),
        )

    def play(self, bars: dict[str, list[Candle]]) -> None:
        for time_ms in sorted({b.open_time_ms for s in bars.values() for b in s}):
            group = [b for s in sorted(bars) for b in bars[s] if b.open_time_ms == time_ms]
            self.loop.process(group, time_ms + HOUR_MS)
            self.risk_by_bar[time_ms] = self.risk.state.model_copy()


@pytest.fixture
def switch(tmp_path: Path) -> KillSwitch:
    return KillSwitch(tmp_path / "KILL")


def keyed(fills: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    return [
        (f["time_ms"], f["symbol"], f["side"], round(f["quantity"], 9), round(f["price"], 9))
        for f in fills
    ]


def backtest(bars: dict[str, list[Candle]], switch: KillSwitch) -> BacktestResult:
    risk = RiskEngine(LIMITS, switch)
    strategy = SizedStrategy(DonchianBreakout(FAST), risk)
    return run_backtest(bars, strategy, risk, COSTS, CASH)


@pytest.mark.parametrize("seed", range(6))
def test_sim_daemon_matches_the_backtester_exactly(
    tmp_path: Path, switch: KillSwitch, seed: int
) -> None:
    bars = {SYMBOL: market(seed, 800), ETH: market(seed + 50, 800, ETH)}
    expected = backtest(bars, switch)
    rig = Rig(tmp_path / "l.sqlite", switch)
    rig.play(bars)
    assert len(expected.fills) > 20
    assert keyed(rig.ledger.fills()) == [
        (f.time_ms, f.symbol, f.side.value, round(f.quantity, 9), round(f.price, 9))
        for f in expected.fills
    ]
    equity = rig.ledger.equity_curve()
    assert [t for t, _ in equity] == [p.time_ms for p in expected.equity_curve]
    assert [e for _, e in equity] == pytest.approx([p.equity for p in expected.equity_curve])
    assert not switch.engaged(), "ledger and simulator must agree throughout"


class Crash(BaseException):
    """Not an Exception, so no handler in the code under test can swallow it."""


def restart(path: Path, switch: KillSwitch, bars: dict[str, list[Candle]]) -> tuple[Rig, int]:
    rig = Rig(path, switch)
    last = max(rig.loop.last_bars.values(), default=T0 - HOUR_MS)
    for symbol in sorted(bars):
        for bar in bars[symbol]:
            if bar.open_time_ms <= last:
                rig.signals.on_bar(bar, False)
    rig.loop.recover(last + HOUR_MS)
    return rig, last


def remaining(bars: dict[str, list[Candle]], after: int) -> dict[str, list[Candle]]:
    return {s: [b for b in v if b.open_time_ms > after] for s, v in bars.items()}


@pytest.mark.parametrize("point", ["place", "checkpoint", "after_place", "fill"])
@pytest.mark.parametrize("nth", [1, 2, 3, 5, 8])
def test_crash_at_any_point_ends_exactly_like_no_crash(
    tmp_path: Path, switch: KillSwitch, point: str, nth: int
) -> None:
    bars = {SYMBOL: market(3, 400)}
    clean = Rig(tmp_path / "clean.sqlite", switch)
    clean.play(bars)

    path = tmp_path / "crash.sqlite"
    rig = Rig(path, switch)
    state = {"left": nth}

    def tick() -> None:
        state["left"] -= 1
        if state["left"] == 0:
            raise Crash

    if point == "place":
        real = rig.adapter.place

        def place(client_id: str, order: OrderRequest, signal_ms: int) -> None:
            tick()
            real(client_id, order, signal_ms)

        rig.adapter.place = place  # type: ignore[method-assign]
    elif point == "after_place":
        real = rig.adapter.place

        def place_then_die(client_id: str, order: OrderRequest, signal_ms: int) -> None:
            real(client_id, order, signal_ms)
            tick()

        rig.adapter.place = place_then_die  # type: ignore[method-assign]
    elif point == "fill":
        real_apply = rig.ledger.apply_fill

        def apply(fill: Any, on_booked: Any = None) -> bool:
            booked = real_apply(fill, on_booked)
            tick()
            return booked

        rig.ledger.apply_fill = apply  # type: ignore[method-assign]
    else:
        real_checkpoint = rig.loop._checkpoint

        def checkpoint() -> None:
            if rig.ledger.fills():
                tick()
            real_checkpoint()

        rig.loop._checkpoint = checkpoint  # type: ignore[method-assign]

    with pytest.raises(Crash):
        rig.play(bars)
    rig.ledger.close()

    resumed, last = restart(path, switch, bars)
    resumed.play(remaining(bars, last))

    assert keyed(resumed.ledger.fills()) == keyed(clean.ledger.fills())
    assert resumed.ledger.cash == pytest.approx(clean.ledger.cash)
    assert resumed.ledger.positions() == clean.ledger.positions()
    # Bar by bar: the daily reset would hide a wrong counter in the final state.
    assert resumed.risk_by_bar
    for time_ms, state_after_bar in resumed.risk_by_bar.items():
        assert state_after_bar == clean.risk_by_bar[time_ms]
    assert not switch.engaged()


def test_sim_never_fills_an_order_on_its_own_signal_bar() -> None:
    sim = SimAdapter(COSTS, CASH)
    order = OrderRequest(SYMBOL, Side.BUY, 1.0)
    sim.place("a", order, T0)
    sim.on_bar(flat(0))
    assert sim.poll()[0] == []
    sim.on_bar(flat(1))
    assert len(sim.poll()[0]) == 1


def test_restart_between_bars_changes_nothing(tmp_path: Path, switch: KillSwitch) -> None:
    bars = {SYMBOL: market(4, 400)}
    clean = Rig(tmp_path / "clean.sqlite", switch)
    clean.play(bars)
    path = tmp_path / "split.sqlite"
    first = Rig(path, switch)
    first.play({SYMBOL: bars[SYMBOL][:200]})
    first.ledger.close()
    resumed, last = restart(path, switch, bars)
    resumed.play(remaining(bars, last))
    assert keyed(resumed.ledger.fills()) == keyed(clean.ledger.fills())


class Always:
    """Enters on every bar while flat, for scenario tests."""

    metadata = StrategyMetadata("always", "-", (), "UNREVIEWED", "-", "-")

    def on_bar(self, bar: Candle, holding: bool) -> Signal | None:
        if holding:
            return None
        return Signal(bar.symbol, Action.ENTER, bar.open_time_ms, "test", bar.close * 0.99)


def rig_always(tmp_path: Path, switch: KillSwitch) -> Rig:
    rig = Rig(tmp_path / "a.sqlite", switch)
    rig.loop._strategy = SizedStrategy(Always(), rig.risk)
    return rig


def flat(index: int, price: float = 100.0, symbol: str = SYMBOL) -> Candle:
    return Candle(
        symbol, "1h", T0 + index * HOUR_MS, price, price * 1.001, price * 0.999, price, 5.0
    )


def test_old_bar_is_recorded_but_never_traded(tmp_path: Path, switch: KillSwitch) -> None:
    rig = rig_always(tmp_path, switch)
    rig.loop.process([flat(0)], T0 + 10 * HOUR_MS)
    assert rig.ledger.pending() == ()
    kinds = {d.kind for d in rig.ledger.decisions()}
    assert "skipped" in kinds
    assert "approved" not in kinds


def test_fresh_bar_is_traded(tmp_path: Path, switch: KillSwitch) -> None:
    rig = rig_always(tmp_path, switch)
    rig.loop.process([flat(0)], T0 + HOUR_MS)
    assert len(rig.ledger.pending()) == 1


def test_kill_switch_stops_the_daemon_placing_orders(tmp_path: Path, switch: KillSwitch) -> None:
    rig = rig_always(tmp_path, switch)
    switch.engage("operator")
    rig.play({SYMBOL: [flat(i) for i in range(5)]})
    assert rig.ledger.fills() == []
    assert rig.ledger.pending() == ()
    assert "refused: kill_switch" in rig.ledger.decisions()[0].detail


def test_reconciliation_difference_engages_kill_switch_before_new_orders(
    tmp_path: Path, switch: KillSwitch
) -> None:
    rig = rig_always(tmp_path, switch)
    rig.adapter._positions[SYMBOL] = 7.0  # someone traded behind the bot's back
    rig.loop.process([flat(0)], T0 + HOUR_MS)
    assert switch.engaged()
    assert rig.ledger.pending() == ()
    assert rig.alerts.sent[0][0] == "critical"
    assert any(d.kind == "reconciliation_failed" for d in rig.ledger.decisions())


def test_cash_difference_is_caught_too(tmp_path: Path, switch: KillSwitch) -> None:
    rig = rig_always(tmp_path, switch)
    rig.adapter._cash -= 1.0
    assert rig.loop.reconcile(T0) is False


def test_venue_outage_skips_reconciliation_without_a_false_alarm(
    tmp_path: Path, switch: KillSwitch
) -> None:
    rig = rig_always(tmp_path, switch)

    def down() -> Balances:
        raise ExecutionError("down")

    rig.adapter.balances = down  # type: ignore[method-assign]
    assert rig.loop.reconcile(T0) is False
    assert not switch.engaged()


def test_daily_loss_breach_alerts_flattens_and_stops_entries(
    tmp_path: Path, switch: KillSwitch
) -> None:
    rig = rig_always(tmp_path, switch)
    rig.play({SYMBOL: [flat(0), flat(1)]})
    assert rig.ledger.positions()
    held = rig.ledger.positions()[SYMBOL]
    crash_price = 100 - 0.03 * CASH / held  # far below the stop: a gap
    rig.play({SYMBOL: [flat(2, crash_price), flat(3, crash_price), flat(4, crash_price)]})
    assert rig.risk.state.halt is Halt.DAILY_LOSS
    assert rig.ledger.positions() == {}
    assert any("daily limit hit" in m for _, m in rig.alerts.sent)
    assert any(d.kind == "limit_hit" for d in rig.ledger.decisions())


def test_flatten_closes_a_healthy_position_after_a_breach_elsewhere(
    tmp_path: Path, switch: KillSwitch
) -> None:
    rig = Rig(tmp_path / "f.sqlite", switch, DailyControls(risk_per_trade_pct=0.25))
    rig.loop._strategy = SizedStrategy(Always(), rig.risk)
    rig.play({SYMBOL: [flat(0), flat(1)], ETH: [flat(0, symbol=ETH), flat(1, symbol=ETH)]})
    held = rig.ledger.positions()
    assert set(held) == {SYMBOL, ETH}
    crash = 100 - 0.04 * CASH / held[ETH]
    rig.play(
        {
            SYMBOL: [flat(2), flat(3), flat(4)],
            ETH: [flat(2, crash, ETH), flat(3, crash, ETH), flat(4, crash, ETH)],
        }
    )
    assert rig.risk.flatten_required
    assert rig.ledger.positions() == {}
    btc_exit = next(f for f in rig.ledger.fills() if f["symbol"] == SYMBOL and f["side"] == "sell")
    assert btc_exit["reason"] == "market"


def test_each_halt_alerts_once_including_halts_from_fills(
    tmp_path: Path, switch: KillSwitch
) -> None:
    limits = DailyControls(max_consecutive_losses=1)
    rig = Rig(tmp_path / "h.sqlite", switch, limits)
    rig.loop._strategy = SizedStrategy(Always(), rig.risk)
    rig.play({SYMBOL: [flat(0), flat(1), flat(2, 98.5), flat(3, 98.5), flat(4, 98.5)]})
    assert rig.risk.state.halt is Halt.CONSECUTIVE_LOSSES
    hits = [m for _, m in rig.alerts.sent if "daily limit hit" in m]
    assert hits == ["daily limit hit: max_consecutive_losses"]


def test_replaying_a_decision_does_not_count_the_entry_twice(
    tmp_path: Path, switch: KillSwitch
) -> None:
    rig = Rig(tmp_path / "r.sqlite", switch, DailyControls(risk_per_trade_pct=0.25))
    rig.loop._strategy = SizedStrategy(Always(), rig.risk)
    rig.loop.process([flat(0)], T0 + HOUR_MS)
    assert rig.risk.state.entries_today == 1
    (client_id, _, _) = rig.ledger.open_orders()[0]
    # Small enough to pass every limit, so only the replay guard can stop it.
    rig.loop._submit(OrderRequest(SYMBOL, Side.BUY, 0.01, stop_price=99.0), T0, 0)
    assert rig.risk.state.entries_today == 1
    assert [c for c, _, _ in rig.ledger.open_orders()] == [client_id]


def test_a_fill_reported_twice_is_logged_once(tmp_path: Path, switch: KillSwitch) -> None:
    rig = rig_always(tmp_path, switch)
    rig.play({SYMBOL: [flat(0), flat(1)]})
    (fill_row,) = rig.ledger.fills()
    repeat = FillReport(
        f"sq-unused:{T0}",
        "x",
        SYMBOL,
        Side.BUY,
        fill_row["quantity"],
        fill_row["price"],
        fill_row["fee"],
        fill_row["time_ms"],
        "market",
    )
    rig.ledger.apply_fill(repeat)
    rig.adapter.poll = lambda: ([repeat], [])  # type: ignore[method-assign]
    rig.loop._sync(T0)
    assert sum(d.kind == "fill" for d in rig.ledger.decisions()) == 1


def test_send_failure_leaves_the_order_for_recovery_under_the_same_id(
    tmp_path: Path, switch: KillSwitch
) -> None:
    rig = rig_always(tmp_path, switch)
    real = rig.adapter.place
    seen: list[str] = []

    def failing(client_id: str, order: OrderRequest, signal_ms: int) -> None:
        seen.append(client_id)
        raise ExecutionError("timeout")

    rig.adapter.place = failing  # type: ignore[method-assign]
    rig.loop.process([flat(0)], T0 + HOUR_MS)
    assert rig.alerts.sent[0][0] == "error"
    rig.adapter.place = real  # type: ignore[method-assign]
    rig.loop.recover(T0 + HOUR_MS)
    assert rig.ledger.open_orders()[0][0] == seen[0]
    rig.loop.process([flat(1)], T0 + 2 * HOUR_MS)
    assert rig.ledger.positions()


class FakePoller:
    def __init__(self, script: list[Any]) -> None:
        self.script = script
        self.wait_seconds = 0.0

    def poll_once(self) -> list[Candle]:
        item = self.script.pop(0) if self.script else []
        if isinstance(item, Exception):
            raise item
        return list(item)


class Countdown(threading.Event):
    def __init__(self, rounds: int) -> None:
        super().__init__()
        self.rounds = rounds

    def wait(self, timeout: float | None = None) -> bool:
        self.rounds -= 1
        if self.rounds <= 0:
            self.set()
        return self.is_set()


def test_service_survives_outages_and_alerts_once(tmp_path: Path, switch: KillSwitch) -> None:
    rig = rig_always(tmp_path, switch)
    failure = MarketDataError("down")
    poller = FakePoller([failure, failure, failure, failure, [flat(0)]])
    rig.loop.run(poller, lambda: T0 + HOUR_MS, Countdown(5))  # type: ignore[arg-type]
    assert [level for level, _ in rig.alerts.sent] == ["error"]
    assert rig.loop.last_bars == {SYMBOL: T0}
    assert rig.ledger.get_state("heartbeat_ms") == T0 + HOUR_MS


def test_limit_request_from_the_panel_is_applied_within_a_cycle(
    tmp_path: Path, switch: KillSwitch
) -> None:
    rig = rig_always(tmp_path, switch)
    stricter = LIMITS.model_copy(update={"max_daily_trades": 3}).model_dump(mode="json")
    rig.ledger.set_state({"requested_limits": stricter})
    rig.loop.run(FakePoller([[flat(0)]]), lambda: T0 + HOUR_MS, Countdown(1))  # type: ignore[arg-type]
    assert rig.risk.limits.max_daily_trades == 3
    assert rig.ledger.get_state("requested_limits") is None
    assert rig.ledger.get_state("risk")["limits"]["max_daily_trades"] == 3


def test_service_never_sleeps_past_the_wake_interval(tmp_path: Path, switch: KillSwitch) -> None:
    rig = rig_always(tmp_path, switch)
    poller = FakePoller([])
    poller.wait_seconds = 3000.0
    stop = Countdown(1)
    waits: list[float | None] = []
    real_wait = stop.wait

    def spy(timeout: float | None = None) -> bool:
        waits.append(timeout)
        return real_wait(timeout)

    stop.wait = spy  # type: ignore[method-assign]
    rig.loop.run(poller, lambda: T0, stop)  # type: ignore[arg-type]
    assert waits == [30.0]


def test_a_new_outage_alerts_again_after_recovery(tmp_path: Path, switch: KillSwitch) -> None:
    rig = rig_always(tmp_path, switch)
    down = MarketDataError("down")
    poller = FakePoller([down, down, down, [], down, down, down])
    rig.loop.run(poller, lambda: T0 + HOUR_MS, Countdown(7))  # type: ignore[arg-type]
    assert [level for level, _ in rig.alerts.sent] == ["error", "error"]


def test_bar_is_kept_when_the_venue_cannot_report_fills(tmp_path: Path, switch: KillSwitch) -> None:
    rig = rig_always(tmp_path, switch)
    real = rig.adapter.poll
    state = {"down": True}

    def flaky() -> Any:
        if state["down"]:
            state["down"] = False
            raise ExecutionError("cannot read fills")
        return real()

    rig.adapter.poll = flaky  # type: ignore[method-assign]
    poller = FakePoller([[flat(0)], []])
    rig.loop.run(poller, lambda: T0 + HOUR_MS, Countdown(2))  # type: ignore[arg-type]
    assert rig.loop.last_bars == {SYMBOL: T0}, "the bar must be retried, not lost"


def config(tmp_path: Path, **kwargs: Any) -> AppConfig:
    base: dict[str, Any] = {
        "runs_dir": str(tmp_path / "runs"),
        "kill_switch_path": str(tmp_path / "KILL"),
        "exchange": ExchangeConfig(symbols=(SYMBOL,)),
        "strategy": FAST,
    }
    return AppConfig(**{**base, **kwargs})


def test_live_mode_cannot_start_even_when_approved(tmp_path: Path) -> None:
    cfg = config(
        tmp_path,
        mode=TradingMode.LIVE,
        live_trading_approved=True,
        exchange=ExchangeConfig(symbols=(SYMBOL,), testnet=False),
    )
    client = make_client(FakeExchange(T0 + HOUR_MS))
    with pytest.raises(ExecutionError, match="not implemented"):
        build_service(cfg, Secrets(), client, Alerts())


def test_build_service_warms_up_and_resumes(tmp_path: Path) -> None:
    now = T0 + 30 * HOUR_MS + 60_000
    exchange = FakeExchange(now, hourly(T0, 30))
    cfg = config(tmp_path)
    service = build_service(cfg, Secrets(), make_client(exchange), Alerts())
    assert service.poller.poll_once() == []
    exchange.bars = hourly(T0, 31)
    exchange.now_ms = T0 + 31 * HOUR_MS + 60_000
    (candle,) = service.poller.poll_once()
    assert candle.open_time_ms == T0 + 30 * HOUR_MS
    service.loop.process([candle], exchange.now_ms)
    service.ledger.close()

    resumed = build_service(cfg, Secrets(), make_client(exchange), Alerts())
    assert resumed.loop.last_bars == {SYMBOL: T0 + 30 * HOUR_MS}
    assert resumed.poller.poll_once() == []
    resumed.ledger.close()
    assert ledger_path(cfg).name == "ledger-sim.sqlite"


def test_config_tightened_during_downtime_applies_on_restart(tmp_path: Path) -> None:
    exchange = FakeExchange(T0 + 30 * HOUR_MS + 60_000, hourly(T0, 30))
    cfg = config(tmp_path)
    service = build_service(cfg, Secrets(), make_client(exchange), Alerts())
    candle = hourly(T0, 30)[-1]
    service.loop.process([Candle(SYMBOL, "1h", candle[0], *candle[1:])], exchange.now_ms)
    service.ledger.close()

    stricter = config(tmp_path, daily_controls=DailyControls(max_daily_trades=1))
    resumed = build_service(stricter, Secrets(), make_client(exchange), Alerts())
    assert resumed.loop._risk.limits.max_daily_trades == 1
    resumed.ledger.close()


def test_corrupt_risk_state_refuses_to_start(tmp_path: Path) -> None:
    cfg = config(tmp_path)
    ledger = Ledger(ledger_path(cfg), CASH)
    ledger.set_state({"risk": {"nonsense": True}})
    ledger.close()
    client = make_client(FakeExchange(T0 + 30 * HOUR_MS, hourly(T0, 30)))
    with pytest.raises(ValueError, match="limits"):
        build_service(cfg, Secrets(), client, Alerts())


class FakeTestnet:
    urls: dict[str, Any] = {"api": {"public": "https://testnet.binance.vision/api"}}  # noqa: RUF012

    def __init__(self) -> None:
        self.base = {"BTC": 1.0}
        self.orders: dict[str, dict[str, Any]] = {}
        self.trades: list[dict[str, Any]] = []
        self.created: list[tuple[Any, ...]] = []
        self.stop_error: Exception | None = None
        self.lookup_error: Exception | None = None
        self.cancelled = 0

    def milliseconds(self) -> int:
        return T0

    def fetch_balance(self) -> dict[str, Any]:
        return {"total": self.base}

    def amount_to_precision(self, symbol: str, amount: float) -> str:
        return f"{amount:.6f}"

    def price_to_precision(self, symbol: str, price: float) -> str:
        return f"{price:.2f}"

    def fetch_order(self, order_id: Any, symbol: str, params: Any = None) -> dict[str, Any]:
        if self.lookup_error:
            raise self.lookup_error
        key = (params or {}).get("origClientOrderId") or order_id
        for oid, order in self.orders.items():
            if key in (oid, order["clientOrderId"]):
                return order
        raise ccxt.OrderNotFound("unknown")

    def create_order(
        self, symbol: str, kind: str, side: str, amount: float, price: Any, params: Any
    ) -> dict[str, Any]:
        self.created.append((kind, side, amount, price, dict(params)))
        if kind == "STOP_LOSS_LIMIT" and self.stop_error:
            raise self.stop_error
        oid = str(len(self.orders) + 1)
        order = {
            "id": oid,
            "clientOrderId": params["newClientOrderId"],
            "average": 200.0,
            "filled": amount,
        }
        self.orders[oid] = order
        if kind == "market":
            self.base["BTC"] += amount if side == "buy" else -amount
            self.trades.append(
                {
                    "id": f"t{oid}",
                    "order": oid,
                    "symbol": symbol,
                    "side": side,
                    "price": 200.0,
                    "amount": amount,
                    "timestamp": T0 + 1,
                    "fee": {"cost": 0.001, "currency": "BTC"},
                }
            )
        return order

    def cancel_all_orders(self, symbol: str) -> None:
        self.cancelled += 1
        raise ccxt.OrderNotFound("nothing open")

    def fetch_my_trades(self, symbol: str, since: int) -> list[dict[str, Any]]:
        return [t for t in self.trades if t["timestamp"] >= since]


def adapter(venue: FakeTestnet, state: Any = None) -> TestnetAdapter:
    return TestnetAdapter(venue, (SYMBOL,), {SYMBOL: 100.0}, state)


BUY = OrderRequest(SYMBOL, Side.BUY, 0.5, stop_price=95.0)


def test_mainnet_exchange_is_refused() -> None:
    venue = FakeTestnet()
    venue.urls = {"api": {"public": "https://api.binance.com/api/v3"}}
    with pytest.raises(ExecutionError, match="not a testnet"):
        adapter(venue)


def test_real_ccxt_sandbox_url_passes_the_testnet_guard(tmp_path: Path) -> None:
    from pydantic import SecretStr

    cfg = config(tmp_path, mode=TradingMode.PAPER)
    secrets = Secrets(exchange_api_key=SecretStr("k"), exchange_api_secret=SecretStr("s"))
    exchange = build_testnet_exchange(cfg, secrets)
    assert "testnet" in str(exchange.urls["api"]).lower()


def test_paper_mode_requires_keys_and_testnet(tmp_path: Path) -> None:
    from pydantic import SecretStr

    keyless = Secrets(_env_file=None, exchange_api_key=None, exchange_api_secret=None)
    with pytest.raises(ExecutionError, match="SQ_EXCHANGE_API_KEY"):
        build_testnet_exchange(config(tmp_path, mode=TradingMode.PAPER), keyless)
    keyed_secrets = Secrets(exchange_api_key=SecretStr("k"), exchange_api_secret=SecretStr("s"))
    with pytest.raises(ExecutionError, match="mode=paper"):
        build_testnet_exchange(config(tmp_path), keyed_secrets)


def test_buy_places_a_stop_at_the_same_distance_from_the_real_fill() -> None:
    venue = FakeTestnet()
    adapter(venue).place("sq1", BUY, T0)
    assert venue.created[0][:2] == ("market", "buy")
    kind, side, amount, limit, params = venue.created[1]
    assert (kind, side, amount) == ("STOP_LOSS_LIMIT", "sell", 0.5)
    assert params["stopPrice"] == 195.0  # filled at 200, signal stop was 5 below the mark
    assert limit == pytest.approx(193.05)


def test_failed_stop_closes_the_position_immediately() -> None:
    venue = FakeTestnet()
    venue.stop_error = ccxt.ExchangeError("rejected")
    adapter(venue).place("sq1", BUY, T0)
    assert venue.created[-1][:2] == ("market", "sell")
    assert venue.base["BTC"] == pytest.approx(1.0)


def test_repeated_client_id_does_not_create_a_second_order() -> None:
    venue = FakeTestnet()
    testnet = adapter(venue)
    testnet.place("sq1", BUY, T0)
    created = len(venue.created)
    testnet.place("sq1", BUY, T0)
    assert len(venue.created) == created


def test_unknown_order_state_does_not_resend() -> None:
    venue = FakeTestnet()
    venue.lookup_error = ccxt.RequestTimeout("slow")
    with pytest.raises(ExecutionError, match="cannot confirm"):
        adapter(venue).place("sq1", BUY, T0)
    assert venue.created == []


def test_rejected_order_is_reported_not_raised() -> None:
    venue = FakeTestnet()
    testnet = adapter(venue)

    def refuse(*_args: Any) -> None:
        raise ccxt.InvalidOrder("MIN_NOTIONAL")

    venue.create_order = refuse  # type: ignore[method-assign,assignment]
    testnet.place("sq1", BUY, T0)
    assert testnet.poll()[1][0].client_id == "sq1"


def test_market_exit_works_when_no_stop_is_open() -> None:
    venue = FakeTestnet()
    adapter(venue).place("sq2", OrderRequest(SYMBOL, Side.SELL, 0.5), T0)
    assert venue.cancelled == 1
    assert venue.created[0][:2] == ("market", "sell")


def test_fills_convert_base_fees_and_ignore_other_activity() -> None:
    venue = FakeTestnet()
    testnet = adapter(venue)
    testnet.place("sq1", BUY, T0)
    venue.orders["99"] = {"id": "99", "clientOrderId": "manual"}
    venue.trades.append({**venue.trades[0], "id": "t99", "order": "99"})
    fills, _ = testnet.poll()
    assert [f.fill_id for f in fills] == ["t1"]
    assert fills[0].fee == pytest.approx(0.2)


def test_restart_keeps_baseline_and_recognises_old_orders() -> None:
    venue = FakeTestnet()
    first = adapter(venue)
    first.place("sq1", BUY, T0)
    fills, _ = first.poll()
    saved = first.to_state()

    second = adapter(venue, saved)
    assert second.balances().positions == {SYMBOL: pytest.approx(0.5)}
    assert [f.fill_id for f in second.poll()[0]] == [fills[0].fill_id]


def test_outage_reading_balances_is_an_execution_error() -> None:
    venue = FakeTestnet()
    testnet = adapter(venue)

    def down() -> None:
        raise ccxt.NetworkError("down")

    venue.fetch_balance = down  # type: ignore[method-assign,assignment]
    with pytest.raises(ExecutionError):
        testnet.balances()

import random
from pathlib import Path
from typing import Any

import pytest
import yaml
from conftest import HOUR_MS, T0
from test_backtest_engine import COSTS, SYMBOL, candle
from test_risk_engine import snap

from sentinel_quant.backtest.engine import run_backtest
from sentinel_quant.cli import main
from sentinel_quant.config import DailyControls, StrategyConfig
from sentinel_quant.data.live import Candle
from sentinel_quant.data.quality import check_ohlcv
from sentinel_quant.data.store import DatasetKey, DatasetStore, frame_from_rows
from sentinel_quant.execution.orders import OrderRequest, Side
from sentinel_quant.features.indicators import (
    average_true_range,
    prior_high,
    prior_low,
    true_range,
)
from sentinel_quant.registry.store import Registry, code_hash
from sentinel_quant.risk.engine import RiskEngine
from sentinel_quant.risk.kill_switch import KillSwitch
from sentinel_quant.strategies.base import Action, Signal, SizedStrategy, StrategyMetadata
from sentinel_quant.strategies.donchian import METADATA, DonchianBreakout

SMALL = StrategyConfig(entry_lookback=3, exit_lookback=2, atr_period=2, atr_stop_multiple=2.0)


def series(seed: int, count: int) -> list[float]:
    rng = random.Random(seed)  # noqa: S311
    return [100 + rng.uniform(-5, 5) for _ in range(count)]


def test_prior_high_and_low_exclude_the_current_value() -> None:
    values = [1.0, 3.0, 2.0, 9.0]
    assert prior_high(values, 2) == [None, None, 3.0, 3.0]
    assert prior_low(values, 2) == [None, None, 1.0, 2.0]


def test_true_range_uses_the_previous_close() -> None:
    high = [10.0, 12.0, 11.0]
    low = [9.0, 11.0, 7.0]
    close = [9.5, 11.5, 8.0]
    assert true_range(high, low, close) == [None, 2.5, 4.5]


def test_atr_needs_a_full_window() -> None:
    high = [10.0, 12.0, 11.0]
    low = [9.0, 11.0, 7.0]
    close = [9.5, 11.5, 8.0]
    assert average_true_range(high, low, close, 2) == [None, None, 3.5]


@pytest.mark.parametrize("cut", [1, 5, 37, 99])
def test_truncation_every_feature_ignores_the_future(cut: int) -> None:
    high = [v + 1 for v in series(1, 100)]
    low = [v - 1 for v in series(1, 100)]
    close = series(1, 100)
    assert prior_high(high, 5)[:cut] == prior_high(high[:cut], 5)
    assert prior_low(low, 5)[:cut] == prior_low(low[:cut], 5)
    assert true_range(high, low, close)[:cut] == true_range(high[:cut], low[:cut], close[:cut])
    full = average_true_range(high, low, close, 5)
    assert full[:cut] == average_true_range(high[:cut], low[:cut], close[:cut], 5)


def feed(strategy: DonchianBreakout, closes: list[float], holding: bool = False) -> list[Any]:
    return [
        strategy.on_bar(candle(i, c, high=c + 1, low=c - 1, close=c), holding)
        for i, c in enumerate(closes)
    ]


def test_breakout_above_the_prior_high_enters_with_an_atr_stop() -> None:
    signals = feed(DonchianBreakout(SMALL), [100, 100, 100, 100, 110])
    signal = signals[-1]
    assert signal.action is Action.ENTER
    assert signal.symbol == SYMBOL
    # True ranges 2 and 11 give an ATR of 6.5, so the stop sits 13 below the close.
    assert signal.stop_price == pytest.approx(110 - 13)
    assert "above 3-bar high" in signal.reason


def test_nothing_happens_during_warmup() -> None:
    assert feed(DonchianBreakout(SMALL), [100, 200, 300]) == [None, None, None]


def test_close_inside_the_channel_does_nothing() -> None:
    assert feed(DonchianBreakout(SMALL), [100, 100, 100, 100, 100.5])[-1] is None


def test_close_below_the_prior_low_exits_when_holding() -> None:
    signal = feed(DonchianBreakout(SMALL), [100, 100, 100, 100, 90], holding=True)[-1]
    assert signal.action is Action.EXIT


def test_no_exit_signal_when_flat_and_no_entry_when_holding() -> None:
    assert feed(DonchianBreakout(SMALL), [100, 100, 100, 100, 90])[-1] is None
    assert feed(DonchianBreakout(SMALL), [100, 100, 100, 100, 110], holding=True)[-1] is None


def test_symbols_keep_separate_histories() -> None:
    strategy = DonchianBreakout(SMALL)
    for i in range(4):
        strategy.on_bar(candle(i, 100, high=101, low=99), False)
    other = candle(4, 500, high=501, low=499, close=500, symbol="ETH/USDT")
    assert strategy.on_bar(other, False) is None


def test_metadata_is_honest_about_its_status() -> None:
    assert METADATA.catalog_entity == "A-005"
    assert METADATA.sharia_status == "UNREVIEWED"
    assert METADATA.evidence == "NOT_ASSESSED"


class Fixed:
    metadata = StrategyMetadata("fixed", "-", (), "UNREVIEWED", "-", "-")

    def __init__(self, signal: Signal | None) -> None:
        self.signal = signal

    def on_bar(self, bar: Candle, holding: bool) -> Signal | None:
        return self.signal


@pytest.fixture
def risk(tmp_path: Path) -> RiskEngine:
    engine = RiskEngine(DailyControls(), KillSwitch(tmp_path / "K"))
    engine.observe(snap())
    return engine


ENTER = Signal(SYMBOL, Action.ENTER, T0, "test", 98.0)
EXIT = Signal(SYMBOL, Action.EXIT, T0, "test")


def test_size_comes_from_the_risk_engine_only(risk: RiskEngine) -> None:
    (order,) = SizedStrategy(Fixed(ENTER), risk).on_bar(candle(0, 100), snap())
    assert order.side is Side.BUY
    assert order.quantity == pytest.approx(25.0)
    assert order.stop_price == 98.0


def test_no_room_means_no_order(risk: RiskEngine) -> None:
    assert SizedStrategy(Fixed(ENTER), risk).on_bar(candle(0, 100), snap(cash=0.0)) == []


def test_exit_sells_the_whole_position_once(risk: RiskEngine) -> None:
    sized = SizedStrategy(Fixed(EXIT), risk)
    (order,) = sized.on_bar(candle(0, 100), snap(positions={SYMBOL: 3.0}))
    assert (order.side, order.quantity) == (Side.SELL, 3.0)
    pending = snap(positions={SYMBOL: 3.0}, pending=(OrderRequest(SYMBOL, Side.SELL, 3.0),))
    assert sized.on_bar(candle(0, 100), pending) == []
    assert sized.on_bar(candle(0, 100), snap()) == []


def test_pending_entry_counts_as_holding(risk: RiskEngine) -> None:
    class Spy(Fixed):
        def on_bar(self, bar: Candle, holding: bool) -> Signal | None:
            assert holding
            return None

    pending = snap(pending=(OrderRequest(SYMBOL, Side.BUY, 1.0, stop_price=90.0),))
    SizedStrategy(Spy(None), risk).on_bar(candle(0, 100), pending)


def trending_bars(count: int) -> list[Candle]:
    rng = random.Random(3)  # noqa: S311
    bars: list[Candle] = []
    price = 100.0
    for index in range(count):
        close = price * (1 + rng.gauss(0.0005, 0.01))
        bars.append(candle(index, price, close=close))
        price = close
    return bars


def test_full_loop_trades_within_limits(tmp_path: Path) -> None:
    risk = RiskEngine(DailyControls(), KillSwitch(tmp_path / "K"))
    strategy = SizedStrategy(DonchianBreakout(StrategyConfig()), risk)
    result = run_backtest({SYMBOL: trending_bars(3_000)}, strategy, risk, COSTS, 10_000.0)
    assert result.trades
    assert all(f.time_ms > f.submitted_ms for f in result.fills)


def test_strategy_truncation_future_bars_cannot_change_decisions(tmp_path: Path) -> None:
    bars = trending_bars(1_500)

    def run_on(data: list[Candle]) -> Any:
        risk = RiskEngine(DailyControls(), KillSwitch(tmp_path / "K"))
        strategy = SizedStrategy(DonchianBreakout(StrategyConfig()), risk)
        return run_backtest({SYMBOL: data}, strategy, risk, COSTS, 10_000.0)

    full, part = run_on(bars), run_on(bars[:900])
    assert part.fills
    assert full.fills[: len(part.fills)] == part.fills


def test_registry_counts_every_trial(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "r.sqlite")
    first = registry.record("s", ["d1"], {"a": 1}, {"sharpe": 1.5}, seed=7)
    second = registry.record("s", ["d1"], {"a": 2}, {"sharpe": 0.1})
    other = registry.record("t", ["d1"], {}, {})
    assert (first.trial_number, second.trial_number, other.trial_number) == (1, 2, 1)
    assert registry.trials("s") == 2
    assert first.config == {"a": 1}
    assert first.metrics == {"sharpe": 1.5}
    assert first.seed == 7
    assert first.dataset_ids == ("d1",)
    assert first.code_hash == code_hash()


def test_registry_survives_reopening(tmp_path: Path) -> None:
    Registry(tmp_path / "r.sqlite").record("s", [], {}, {})
    assert Registry(tmp_path / "r.sqlite").record("s", [], {}, {}).trial_number == 2


def test_code_hash_is_stable() -> None:
    assert code_hash() == code_hash()
    assert len(code_hash()) == 64


def test_cli_backtest_logs_each_run_and_warns(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "c.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "data_dir": str(tmp_path / "data"),
                "runs_dir": str(tmp_path / "runs"),
                "kill_switch_path": str(tmp_path / "KILL"),
                "exchange": {"symbols": [SYMBOL], "timeframe": "1h"},
            }
        ),
        encoding="utf-8",
    )
    assert main(["backtest", "--config", str(config)]) == 1  # no dataset yet

    bars = trending_bars(500)
    rows = [[b.open_time_ms, b.open, b.high, b.low, b.close, b.volume] for b in bars]
    frame = frame_from_rows(rows)
    as_of = T0 + 501 * HOUR_MS
    from datetime import UTC, datetime

    DatasetStore(tmp_path / "data").save(
        DatasetKey("binance", SYMBOL, "1h"),
        frame,
        check_ohlcv(frame, "1h", as_of),
        source="test",
        library_version="test",
        parent_dataset_id=None,
        fetched_at=datetime.fromtimestamp(as_of / 1000, tz=UTC),
    )
    capsys.readouterr()
    assert main(["backtest", "--config", str(config)]) == 0
    assert "NOT EVIDENCE OF AN EDGE" in capsys.readouterr().out
    main(["backtest", "--config", str(config), "--cost-multiplier", "2"])
    runs = Registry(tmp_path / "runs/registry.sqlite").runs("donchian_breakout")
    assert [r.trial_number for r in runs] == [1, 2]
    assert runs[1].config["costs"]["fee_bps"] == 20


def test_cli_backtest_is_not_blocked_by_the_operator_kill_switch(tmp_path: Path) -> None:
    switch = KillSwitch(tmp_path / "KILL")
    switch.engage("x")
    assert not KillSwitch(f"{switch.path}.backtest").engaged()

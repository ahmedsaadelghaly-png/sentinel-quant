import random
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest
import yaml
from conftest import HOUR_MS
from conftest import T0 as ANY_HOUR
from test_backtest_engine import COSTS, SYMBOL

from sentinel_quant.backtest.models import BacktestResult, CostModel, EquityPoint
from sentinel_quant.cli import main
from sentinel_quant.config import AppConfig, ExchangeConfig, StrategyConfig, ValidationConfig
from sentinel_quant.data.live import Candle
from sentinel_quant.data.quality import check_ohlcv
from sentinel_quant.data.store import DatasetKey, DatasetStore, frame_from_rows
from sentinel_quant.evaluation.validation import (
    GateResult,
    WindowResult,
    gate_g2,
    gate_g3,
    gate_g4,
    gate_g5,
    holdout_uses,
    neighbours,
    parameter_grid,
    rolling_windows,
    run_strategy,
    slice_bars,
    split_holdout,
    validate_strategy,
    walk_forward,
    year_returns,
)
from sentinel_quant.registry.store import Registry

DAY_MS = 24 * HOUR_MS
T0 = ANY_HOUR // DAY_MS * DAY_MS  # midnight, so 4h bars pass the alignment check
BASE = StrategyConfig(entry_lookback=20, exit_lookback=10, atr_period=5, atr_stop_multiple=2.0)
HOLDOUT = T0 + 150 * DAY_MS


def bars(days: int, seed: int = 1, drift: float = 0.0) -> list[Candle]:
    rng = random.Random(seed)  # noqa: S311
    out: list[Candle] = []
    price = 100.0
    for index in range(days * 6):
        close = price * (1 + rng.gauss(drift, 0.01))
        high, low = max(price, close) * 1.002, min(price, close) * 0.998
        out.append(Candle(SYMBOL, "4h", T0 + index * 4 * HOUR_MS, price, high, low, close, 5.0))
        price = close
    return out


def config(tmp_path: Path, **kwargs: Any) -> AppConfig:
    base: dict[str, Any] = {
        "runs_dir": str(tmp_path / "runs"),
        "kill_switch_path": str(tmp_path / "KILL"),
        "exchange": ExchangeConfig(symbols=(SYMBOL,), timeframe="4h"),
        "strategy": BASE,
        "validation": ValidationConfig(train_days=60, test_days=30),
    }
    return AppConfig(**{**base, **kwargs})


def test_holdout_split_is_exact_and_complete() -> None:
    data = {SYMBOL: bars(200)}
    development, holdout = split_holdout(data, HOLDOUT)
    assert max(b.open_time_ms for b in development[SYMBOL]) < HOLDOUT
    assert min(b.open_time_ms for b in holdout[SYMBOL]) >= HOLDOUT
    assert len(development[SYMBOL]) + len(holdout[SYMBOL]) == len(data[SYMBOL])


def test_windows_never_overlap_their_own_test_period() -> None:
    windows = rolling_windows(0, 400 * DAY_MS, 100, 50)
    assert windows[0] == (0, 100 * DAY_MS, 150 * DAY_MS)
    assert len(windows) == 6
    assert all(a < b < c for a, b, c in windows)
    assert all(w[2] <= 400 * DAY_MS for w in windows)
    tests = [(w[1], w[2]) for w in windows]
    assert all(x[1] <= y[0] for x, y in pairwise(tests))


def test_short_history_gives_no_windows() -> None:
    assert rolling_windows(0, 10 * DAY_MS, 100, 50) == []


def test_grid_and_neighbours_stay_valid_and_exclude_the_base_from_neighbours() -> None:
    assert BASE in parameter_grid(BASE)
    assert len(parameter_grid(BASE)) == 9
    variants = neighbours(BASE)
    assert len(variants) == 6
    assert BASE not in variants
    tiny = StrategyConfig(entry_lookback=2, exit_lookback=2, atr_period=2)
    assert all(v.entry_lookback >= 2 for v in parameter_grid(tiny))


def fake_result(curve: list[tuple[int, float]]) -> BacktestResult:
    return BacktestResult(
        timeframe="4h",
        dataset_ids=(),
        costs=COSTS,
        initial_cash=curve[0][1],
        equity_curve=tuple(EquityPoint(t, e, e) for t, e in curve),
        fills=(),
        trades=(),
        rejections=(),
        unfilled=(),
        open_positions={},
        fees_paid=0.0,
        slippage_paid=0.0,
    )


def test_walk_forward_selects_on_training_data_only() -> None:
    """Whatever happens in the test period must not influence the choice of parameters."""
    data = {SYMBOL: bars(120)}
    windows = [(T0, T0 + 60 * DAY_MS, T0 + 90 * DAY_MS)]
    train_end = windows[0][1]
    seen: list[tuple[str, int]] = []

    def runner(
        candles: Any, params: StrategyConfig, costs: CostModel, scope: str
    ) -> BacktestResult:
        last = max(b.open_time_ms for b in candles[SYMBOL])
        seen.append((scope, last))
        # Alternating returns: Sharpe rises with entry_lookback, so the winner is known.
        equity = 100.0
        curve = []
        for i in range(60):
            equity *= 1 + 0.0002 * params.entry_lookback + (0.01 if i % 2 else -0.01)
            curve.append((T0 + (i + 1) * DAY_MS, equity))
        return fake_result(curve)

    (result,) = walk_forward(data, BASE, COSTS, runner, windows)
    assert all(last < train_end for scope, last in seen if scope.endswith("train"))
    assert result.chosen.entry_lookback == max(p.entry_lookback for p in parameter_grid(BASE))


def test_walk_forward_measures_only_the_test_period() -> None:
    start = T0
    test_start = start + 60 * DAY_MS
    test_end = start + 90 * DAY_MS
    curve = [(start + i * DAY_MS, 100.0 if i < 60 else 110.0) for i in range(1, 91)]
    curve[59] = (start + 60 * DAY_MS, 200.0)  # equity going into the test period

    def runner(
        candles: Any, params: StrategyConfig, costs: CostModel, scope: str
    ) -> BacktestResult:
        return fake_result(curve)

    (result,) = walk_forward(
        {SYMBOL: bars(120)}, BASE, COSTS, runner, [(start, test_start, test_end)]
    )
    assert result.net_return_pct == pytest.approx(-45.0)


def test_future_bars_cannot_change_a_window_choice(tmp_path: Path) -> None:
    cfg = config(tmp_path)
    original = {SYMBOL: bars(100, seed=3)}
    window = (T0, T0 + 60 * DAY_MS, T0 + 90 * DAY_MS)
    altered_bars = [
        b if b.open_time_ms < window[1] else Candle(SYMBOL, "4h", b.open_time_ms, 50, 51, 49, 50, 5)
        for b in original[SYMBOL]
    ]

    def runner(
        candles: Any, params: StrategyConfig, costs: CostModel, scope: str
    ) -> BacktestResult:
        return run_strategy(cfg, candles, costs, params, [])

    first = walk_forward(original, BASE, COSTS, runner, [window])[0]
    second = walk_forward({SYMBOL: altered_bars}, BASE, COSTS, runner, [window])[0]
    assert first.chosen == second.chosen


def test_year_returns_chain_correctly() -> None:
    def ms(year: int, month: int) -> int:
        return int(datetime(year, month, 2, tzinfo=UTC).timestamp() * 1000)

    curve = [
        EquityPoint(ms(2023, 1), 100.0, 0.0),
        EquityPoint(ms(2023, 12), 110.0, 0.0),
        EquityPoint(ms(2024, 12), 99.0, 0.0),
    ]
    assert year_returns(curve) == pytest.approx({2023: 10.0, 2024: -10.0})


def test_g2_needs_profit_after_costs(tmp_path: Path) -> None:
    assert gate_g2(fake_result([(T0, 100.0), (T0 + 1, 120.0)])).status == "FAIL"  # no trades
    cfg = config(tmp_path)
    result = run_strategy(cfg, {SYMBOL: bars(200, seed=2)}, COSTS, BASE, [])
    gate = gate_g2(result)
    assert gate.status == ("PASS" if result.final_equity > result.initial_cash else "FAIL")


def test_g3_rules() -> None:
    assert gate_g3(None, 1.0, 0).status == "NOT_RUN"
    assert gate_g3(0.6, 1.0, 0).status == "PASS"
    assert gate_g3(0.4, 1.0, 0).status == "FAIL"
    assert gate_g3(-0.1, -1.0, 0).status == "FAIL"
    tainted = gate_g3(2.0, 1.0, 1)
    assert tainted.status == "NOT_ASSESSED"
    assert "already seen" in tainted.detail


def window(change: float) -> WindowResult:
    return WindowResult(0, 1, BASE, change)


def test_g4_rules() -> None:
    assert gate_g4([]).status == "NOT_ASSESSED"
    assert gate_g4([window(1), window(1), window(1), window(-1), window(-1)]).status == "PASS"
    assert gate_g4([window(1), window(-1)]).status == "FAIL"
    assert gate_g4([window(1), window(1), window(-50)]).status == "FAIL"  # stitched loss


def test_g5_rules() -> None:
    years = {2023: 1.0, 2024: -1.0}
    assert gate_g5([1, 1, 1, -1], 1.0, years).status == "PASS"
    assert gate_g5([1, -1, -1, -1], 1.0, years).status == "FAIL"
    assert gate_g5([1, 1, 1, 1], -1.0, years).status == "FAIL"
    assert gate_g5([1, 1, 1, 1], 1.0, {2023: -1.0, 2024: -1.0}).status == "FAIL"
    assert gate_g5([], 1.0, years).status == "FAIL"


def status(report: Any, gate: str) -> GateResult:
    return next(g for g in report.gates if g.gate.startswith(gate))


def test_validate_end_to_end_keeps_the_holdout_shut(tmp_path: Path) -> None:
    cfg = config(tmp_path)
    registry = Registry(tmp_path / "r.sqlite")
    data = {SYMBOL: bars(200, seed=5)}
    report = validate_strategy(cfg, data, ["d"], registry, HOLDOUT)
    assert status(report, "G3").status == "NOT_RUN"
    assert holdout_uses(registry, BASE.name) == 0
    for run in registry.runs(BASE.name):
        assert registry.equity(run.id)[-1][0] <= HOLDOUT + 4 * HOUR_MS


def test_changing_the_holdout_cannot_change_any_development_result(tmp_path: Path) -> None:
    original = bars(200, seed=6)
    altered = [
        b if b.open_time_ms < HOLDOUT else Candle(SYMBOL, "4h", b.open_time_ms, 9, 9.5, 8.5, 9, 5)
        for b in original
    ]
    first = validate_strategy(
        config(tmp_path / "a"), {SYMBOL: original}, ["d"], Registry(tmp_path / "a.sqlite"), HOLDOUT
    )
    second = validate_strategy(
        config(tmp_path / "b"), {SYMBOL: altered}, ["d"], Registry(tmp_path / "b.sqlite"), HOLDOUT
    )
    assert first.gates == second.gates
    assert first.windows == second.windows


def test_every_variant_counts_as_a_trial(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "r.sqlite")
    report = validate_strategy(config(tmp_path), {SYMBOL: bars(200)}, ["d"], registry, HOLDOUT)
    windows = len(report.windows)
    assert windows >= 1
    assert registry.trials(BASE.name) == 1 + 6 + 1 + windows * (9 + 1)


def test_opening_the_holdout_is_recorded_and_only_counts_once(tmp_path: Path) -> None:
    cfg = config(tmp_path)
    registry = Registry(tmp_path / "r.sqlite")
    data = {SYMBOL: bars(200, seed=7)}
    first = validate_strategy(cfg, data, ["d"], registry, HOLDOUT, open_holdout=True)
    assert status(first, "G3").status in ("PASS", "FAIL")
    assert holdout_uses(registry, BASE.name) == 1
    second = validate_strategy(cfg, data, ["d"], registry, HOLDOUT, open_holdout=True)
    assert status(second, "G3").status == "NOT_ASSESSED"


def test_a_run_with_no_holdout_record_counts_as_having_seen_it(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "r.sqlite")
    registry.record(BASE.name, ["d"], {"scope": "old"}, {})
    assert holdout_uses(registry, BASE.name) == 1


def test_report_never_claims_approval(tmp_path: Path) -> None:
    report = validate_strategy(
        config(tmp_path), {SYMBOL: bars(200)}, ["d"], Registry(tmp_path / "r.sqlite"), HOLDOUT
    )
    assert "never approves" in report.text
    assert status(report, "G7").status == "NOT_ASSESSED"
    assert status(report, "G8").status == "NOT_ASSESSED"
    assert status(report, "G1").status == "NOT_ASSESSED"


def test_noise_does_not_pass_every_automated_gate(tmp_path: Path) -> None:
    for seed in range(3):
        report = validate_strategy(
            config(tmp_path / str(seed)),
            {SYMBOL: bars(200, seed=20 + seed)},
            ["d"],
            Registry(tmp_path / f"{seed}.sqlite"),
            HOLDOUT,
        )
        assert any(g.status == "FAIL" for g in report.gates), "noise must fail something"


def test_slice_bars_is_half_open() -> None:
    data = {SYMBOL: bars(10)}
    sliced = slice_bars(data, T0, T0 + DAY_MS)[SYMBOL]
    assert len(sliced) == 6


def save_dataset(tmp_path: Path, candles: list[Candle]) -> None:
    rows = [[c.open_time_ms, c.open, c.high, c.low, c.close, c.volume] for c in candles]
    frame = frame_from_rows(rows)
    as_of = candles[-1].open_time_ms + 8 * HOUR_MS
    DatasetStore(tmp_path / "data").save(
        DatasetKey("binance", SYMBOL, "4h"),
        frame,
        check_ohlcv(frame, "4h", as_of),
        source="test",
        library_version="test",
        parent_dataset_id=None,
        fetched_at=datetime.fromtimestamp(as_of / 1000, tz=UTC),
    )


def cli_config(tmp_path: Path) -> str:
    holdout = datetime.fromtimestamp(HOLDOUT / 1000, tz=UTC)
    path = tmp_path / "c.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "data_dir": str(tmp_path / "data"),
                "runs_dir": str(tmp_path / "runs"),
                "kill_switch_path": str(tmp_path / "KILL"),
                "exchange": {"symbols": [SYMBOL], "timeframe": "4h"},
                "strategy": BASE.model_dump(),
                "validation": {
                    "holdout_start": holdout.date().isoformat(),
                    "train_days": 60,
                    "test_days": 30,
                },
            }
        ),
        encoding="utf-8",
    )
    return str(path)


def test_cli_backtest_stops_before_the_holdout_by_default(tmp_path: Path) -> None:
    save_dataset(tmp_path, bars(200))
    config_path = cli_config(tmp_path)
    assert main(["backtest", "--config", config_path]) == 0
    assert main(["backtest", "--config", config_path, "--include-holdout"]) == 0
    registry = Registry(tmp_path / "runs/registry.sqlite")
    shut, opened = registry.runs(BASE.name)
    assert registry.equity(shut.id)[-1][0] <= HOLDOUT + 4 * HOUR_MS
    assert registry.equity(opened.id)[-1][0] > HOLDOUT + DAY_MS
    assert shut.config["holdout_used"] is False
    assert opened.config["holdout_used"] is True


def test_cli_validate_writes_a_report(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    save_dataset(tmp_path, bars(200))
    assert main(["validate", "--config", cli_config(tmp_path)]) == 0
    assert "| G4 Walk-forward |" in capsys.readouterr().out
    assert list((tmp_path / "runs/reports").glob("validation-*.md"))


def test_run_strategy_uses_a_private_kill_switch(tmp_path: Path) -> None:
    cfg = config(tmp_path)
    (tmp_path / "KILL").write_text("x", encoding="utf-8")
    result = run_strategy(cfg, {SYMBOL: bars(200, seed=8)}, COSTS, BASE, [])
    assert not any("kill_switch" in r.reason for r in result.rejections)

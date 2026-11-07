from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import yaml
from conftest import HOUR_MS, T0
from test_backtest_engine import COSTS, FREE, SYMBOL, ApproveAll, buy, candle, run
from test_trading_loop import market

from sentinel_quant.backtest.engine import run_backtest
from sentinel_quant.backtest.models import BacktestError
from sentinel_quant.backtest.screener import screen
from sentinel_quant.cli import main
from sentinel_quant.data.live import Candle
from sentinel_quant.evaluation.report import (
    G6_MAX_PBO,
    G6_MIN_DEFLATED_SHARPE,
    EvaluationError,
    _verdict,
    daily_returns,
    evaluate_run,
)
from sentinel_quant.evaluation.statistics import (
    bootstrap_sharpe_interval,
    deflated_sharpe,
    expected_max_sharpe,
    kurtosis,
    probabilistic_sharpe,
    probability_of_overfitting,
    sharpe,
    skewness,
)
from sentinel_quant.execution.orders import OrderRequest, PortfolioSnapshot, Side
from sentinel_quant.registry.store import Registry

DAY_MS = 24 * HOUR_MS


def test_deflated_sharpe_reproduces_the_published_example() -> None:
    """Bailey and Lopez de Prado (2014): SR 2.5, 5 years, skew -3, kurtosis 10, 100 trials."""
    observed = 2.5 / np.sqrt(250)
    variance = 0.5 / 250
    assert expected_max_sharpe(100, variance) == pytest.approx(0.1132, abs=5e-4)
    assert deflated_sharpe(observed, 1250, -3.0, 10.0, 100, variance) == pytest.approx(
        0.9004, abs=2e-3
    )


def test_more_trials_means_a_higher_bar() -> None:
    values = [expected_max_sharpe(n, 0.01) for n in (2, 10, 100, 1000)]
    assert values == sorted(values)
    dsr = [deflated_sharpe(0.1, 1000, 0.0, 3.0, n, 0.001) for n in (1, 10, 100)]
    assert dsr == sorted(dsr, reverse=True)


def test_one_trial_has_no_luck_benchmark() -> None:
    assert expected_max_sharpe(1, 0.01) == 0
    assert deflated_sharpe(0.1, 500, 0.0, 3.0, 1, 0.01) == pytest.approx(
        probabilistic_sharpe(0.1, 0.0, 500, 0.0, 3.0)
    )


def test_probabilistic_sharpe_basics() -> None:
    assert probabilistic_sharpe(0.0, 0.0, 500, 0.0, 3.0) == pytest.approx(0.5)
    assert probabilistic_sharpe(0.2, 0.0, 500, 0.0, 3.0) > 0.99
    assert probabilistic_sharpe(-0.2, 0.0, 500, 0.0, 3.0) < 0.01


def test_negative_skew_and_fat_tails_lower_confidence() -> None:
    normal = probabilistic_sharpe(0.1, 0.0, 500, 0.0, 3.0)
    assert probabilistic_sharpe(0.1, 0.0, 500, -2.0, 3.0) < normal
    assert probabilistic_sharpe(0.1, 0.0, 500, 0.0, 30.0) < normal


def test_moments_of_a_normal_sample() -> None:
    sample = np.random.default_rng(1).normal(0, 1, 200_000)
    assert skewness(sample) == pytest.approx(0, abs=0.03)
    assert kurtosis(sample) == pytest.approx(3, abs=0.05)
    assert sharpe(np.zeros(10)) == 0


def test_bootstrap_interval_is_seeded_and_brackets_the_estimate() -> None:
    rng = np.random.default_rng(2)
    returns = rng.normal(0.001, 0.01, 2000)
    first = bootstrap_sharpe_interval(returns, seed=5)
    assert first == bootstrap_sharpe_interval(returns, seed=5)
    assert first != bootstrap_sharpe_interval(returns, seed=6)
    assert first.low < sharpe(returns) < first.high


def test_bootstrap_covers_the_true_value_about_as_often_as_it_claims() -> None:
    rng = np.random.default_rng(3)
    hits = 0
    for seed in range(100):
        sample = rng.normal(0.001, 0.01, 500)
        interval = bootstrap_sharpe_interval(sample, seed=seed, resamples=400)
        hits += interval.low < 0.1 < interval.high
    assert 85 <= hits <= 100


def test_block_bootstrap_widens_for_autocorrelated_returns() -> None:
    rng = np.random.default_rng(4)
    noise = rng.normal(0, 0.01, 3000)
    correlated = np.zeros(3000)
    for i in range(1, 3000):
        correlated[i] = 0.8 * correlated[i - 1] + noise[i]
    correlated += 0.001
    wide = bootstrap_sharpe_interval(correlated, seed=1, block=50)
    narrow = bootstrap_sharpe_interval(correlated, seed=1, block=1)
    assert wide.high - wide.low > narrow.high - narrow.low


def test_pbo_of_pure_noise_is_about_one_half() -> None:
    results = [
        probability_of_overfitting(np.random.default_rng(s).normal(0, 0.01, (1000, 20)), blocks=10)
        for s in range(8)
    ]
    assert np.mean(results) == pytest.approx(0.5, abs=0.12)


def test_pbo_of_a_real_edge_is_near_zero() -> None:
    rng = np.random.default_rng(5)
    trials = rng.normal(0, 0.01, (1000, 10))
    trials[:, 3] += 0.005
    assert probability_of_overfitting(trials, blocks=10) < 0.05


def test_pbo_catches_selection_of_a_lucky_period() -> None:
    """Each trial shines in one stretch and is bad elsewhere: picking winners backfires."""
    rng = np.random.default_rng(6)
    trials = rng.normal(-0.001, 0.002, (1000, 10))
    for column in range(10):
        trials[column * 100 : (column + 1) * 100, column] += 0.02
    assert probability_of_overfitting(trials, blocks=10) > 0.2


def test_pbo_needs_real_input() -> None:
    with pytest.raises(ValueError, match="two trials"):
        probability_of_overfitting(np.zeros((100, 1)))
    with pytest.raises(ValueError, match="too few"):
        probability_of_overfitting(np.zeros((3, 4)))


def test_identical_trials_are_not_skill_or_failure_by_accident() -> None:
    column = np.random.default_rng(7).normal(0, 0.01, 200)
    assert probability_of_overfitting(np.column_stack([column] * 4), blocks=4) in (0.0, 1.0)


def test_daily_returns_use_the_last_close_of_each_day() -> None:
    start = T0 // DAY_MS * DAY_MS
    curve = [
        (start + 6 * HOUR_MS, 100.0),
        (start + DAY_MS, 110.0),  # closes exactly at midnight: still the first day
        (start + DAY_MS + HOUR_MS, 121.0),
    ]
    days, returns = daily_returns(curve)
    assert returns == pytest.approx([0.1])
    assert len(days) == 1


def curve_for(returns: Any) -> list[tuple[int, float]]:
    equity = 10_000 * np.cumprod(1 + np.asarray(returns))
    start = T0 // DAY_MS * DAY_MS
    return [(start + (i + 1) * DAY_MS, float(v)) for i, v in enumerate(equity)]


def record(registry: Registry, returns: Any, name: str = "s", dataset: str = "d") -> int:
    return registry.record(name, [dataset], {}, {"trades": 1}, equity=curve_for(returns)).id


def test_thresholds_are_fixed_constants() -> None:
    assert G6_MIN_DEFLATED_SHARPE == 0.95
    assert G6_MAX_PBO == 0.25


def test_verdict_logic() -> None:
    assert _verdict(0.5, 0.1, 10)[0] == "FAIL"
    assert _verdict(0.99, 0.5, 10)[0] == "FAIL"
    assert _verdict(0.99, None, 2)[0] == "NOT_ASSESSED"
    assert _verdict(0.99, 0.1, 10)[0] == "PASS"
    assert _verdict(0.95, 0.25, 10)[0] == "PASS"


def test_report_on_a_strong_series_is_not_assessed_without_enough_trials(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "r.sqlite")
    returns = np.random.default_rng(8).normal(0.003, 0.01, 800)
    evaluation = evaluate_run(registry, record(registry, returns))
    assert evaluation.deflated_sharpe > 0.95
    assert evaluation.g6 == "NOT_ASSESSED"
    assert evaluation.pbo is None
    assert "G6 is one gate of eight" in evaluation.text


def test_report_on_noise_fails(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "r.sqlite")
    returns = np.random.default_rng(9).normal(0, 0.01, 800)
    assert evaluate_run(registry, record(registry, returns)).g6 == "FAIL"


def test_best_of_many_noise_trials_fails_after_deflation(tmp_path: Path) -> None:
    """The point of the exercise: the luckiest of 50 tries must not look like an edge."""
    registry = Registry(tmp_path / "r.sqlite")
    rng = np.random.default_rng(10)
    runs = {record(registry, r): sharpe(r) for r in rng.normal(0, 0.01, (50, 500))}
    best = max(runs, key=lambda k: runs[k])
    evaluation = evaluate_run(registry, best)
    assert evaluation.probabilistic_sharpe > 0.9, "it must look good before deflation"
    assert evaluation.deflated_sharpe < 0.5
    assert evaluation.trials == 50
    assert evaluation.g6 == "FAIL"


def test_full_pass_is_possible_for_a_genuine_edge(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "r.sqlite")
    rng = np.random.default_rng(11)
    best = 0
    for index in range(6):
        drift = 0.004 if index == 2 else 0.0
        run_id = record(registry, rng.normal(drift, 0.01, 800))
        best = run_id if index == 2 else best
    evaluation = evaluate_run(registry, best)
    assert evaluation.g6 == "PASS"
    assert evaluation.pbo is not None and evaluation.pbo <= G6_MAX_PBO


def test_pbo_only_compares_trials_on_the_same_data(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "r.sqlite")
    rng = np.random.default_rng(15)
    first = record(registry, rng.normal(0, 0.01, 200))
    for _ in range(2):
        record(registry, rng.normal(0, 0.01, 200))
    record(registry, rng.normal(0, 0.01, 200), dataset="other")
    evaluation = evaluate_run(registry, first)
    assert evaluation.trials == 4, "every trial still counts towards deflation"
    assert evaluation.pbo is None, "only three share this run's data"


def test_pbo_only_compares_trials_of_the_same_scope(tmp_path: Path) -> None:
    """A walk-forward window covers less history, so it is not comparable."""
    registry = Registry(tmp_path / "r.sqlite")
    rng = np.random.default_rng(16)
    curves = [curve_for(rng.normal(0, 0.01, 200)) for _ in range(4)]
    scopes = ["development", "development", "development", "window-0-test"]
    ids = [
        registry.record("s", ["d"], {"scope": scope}, {"trades": 1}, equity=curve).id
        for scope, curve in zip(scopes, curves, strict=True)
    ]
    assert evaluate_run(registry, ids[0]).pbo is None


def test_trials_of_another_strategy_do_not_count(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "r.sqlite")
    returns = np.random.default_rng(12).normal(0.001, 0.01, 200)
    target = record(registry, returns)
    record(registry, returns, name="other")
    assert evaluate_run(registry, target).trials == 1


def test_few_trials_cannot_shrink_the_luck_benchmark(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "r.sqlite")
    returns = np.random.default_rng(13).normal(0.002, 0.01, 400)
    first = record(registry, returns)
    record(registry, returns)  # identical trial: sample variance is exactly zero
    evaluation = evaluate_run(registry, first)
    assert evaluation.deflated_sharpe < evaluation.probabilistic_sharpe


def test_report_metrics_match_hand_values(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "r.sqlite")
    returns = np.array([0.01, -0.02] * 40)
    evaluation = evaluate_run(registry, record(registry, returns))
    assert evaluation.days == 79
    assert evaluation.worst_day_pct == pytest.approx(-2.0)
    assert evaluation.cvar_95_pct == pytest.approx(-2.0)
    assert evaluation.annual_sharpe < 0


def test_unusable_runs_are_refused(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "r.sqlite")
    with pytest.raises(EvaluationError, match="no run"):
        evaluate_run(registry, 99)
    bare = registry.record("s", [], {}, {}).id
    with pytest.raises(EvaluationError, match="no stored equity"):
        evaluate_run(registry, bare)
    short = record(registry, [0.01] * 5)
    with pytest.raises(EvaluationError, match="covers"):
        evaluate_run(registry, short)


def test_cli_evaluate_writes_the_report(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = tmp_path / "c.yaml"
    config.write_text(yaml.safe_dump({"runs_dir": str(tmp_path / "runs")}), encoding="utf-8")
    registry = Registry(tmp_path / "runs/registry.sqlite")
    run_id = record(registry, np.random.default_rng(14).normal(0, 0.01, 100))
    assert main(["evaluate", str(run_id), "--config", str(config)]) == 0
    assert "G6 verdict" in capsys.readouterr().out
    assert (tmp_path / f"runs/reports/run-{run_id}.md").exists()
    assert main(["evaluate", "999", "--config", str(config)]) == 1


class Target:
    def __init__(self, wanted: Any) -> None:
        self.wanted = wanted
        self.index = 0

    def on_bar(self, bar: Candle, portfolio: PortfolioSnapshot) -> Sequence[OrderRequest]:
        want = bool(self.wanted[self.index])
        self.index += 1
        pending = [o.side for o in portfolio.pending]
        holding = (portfolio.positions.get(bar.symbol, 0.0) > 0 or Side.BUY in pending) and (
            Side.SELL not in pending
        )
        if want and not holding:
            return [OrderRequest(bar.symbol, Side.BUY, 1.0)]
        if holding and not want:
            return [OrderRequest(bar.symbol, Side.SELL, 1.0)]
        return []


@pytest.mark.parametrize("seed", range(5))
def test_screener_agrees_with_the_engine(seed: int) -> None:
    bars = market(seed, 1500)  # includes zero-volume bars
    wanted = np.random.default_rng(seed).random(1500) < 0.5
    wanted = np.repeat(wanted[::5], 5)[:1500]
    engine = run_backtest({SYMBOL: bars}, Target(wanted), ApproveAll(), COSTS, 1e6)
    fast = screen(bars, wanted, 1.0, COSTS, 1e6)
    assert fast.tolist() == pytest.approx([p.equity for p in engine.equity_curve])
    assert len(engine.fills) > 50


def test_screener_buy_and_hold_golden() -> None:
    bars = [candle(0), candle(1, 100), candle(2, 130)]
    wanted = np.array([True, True, True])
    expected = run(bars, {0: [buy(1.0)]}, FREE, cash=1000.0)
    assert screen(bars, wanted, 1.0, FREE, 1000.0).tolist() == pytest.approx(
        [p.equity for p in expected.equity_curve]
    )


def test_screener_never_uses_the_signal_bar() -> None:
    bars = [candle(0, 100, close=200), candle(1, 300, close=300)]
    wanted = np.array([True, True])
    assert screen(bars, wanted, 1.0, FREE, 1000.0).tolist() == [1000.0, 1000.0]


def test_screener_truncation() -> None:
    bars = market(21, 400)
    wanted = np.random.default_rng(21).random(400) < 0.5
    full = screen(bars, wanted, 1.0, COSTS, 1e6)
    part = screen(bars[:250], wanted[:250], 1.0, COSTS, 1e6)
    assert full[:250].tolist() == part.tolist()


def test_screener_rejects_misaligned_input() -> None:
    with pytest.raises(BacktestError, match="one value per bar"):
        screen([candle(0)], np.array([True, False]), 1.0, FREE, 1.0)

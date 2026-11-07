"""The automated part of the §6 validation protocol: gates G2 to G6.

G1 (definition), G7 (paper) and G8 (approval) cannot be automated, so a clean report here
never means a strategy is approved. Thresholds are constants for the same reason as in
``report.py``: they are fixed before testing. Every variant tried is logged in the registry
and counts as a trial, because selection is what deflation corrects for.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from statistics import fmean
from typing import Literal

import numpy as np

from sentinel_quant.backtest.engine import run_backtest
from sentinel_quant.backtest.models import BacktestResult, CostModel, EquityPoint
from sentinel_quant.config.schema import AppConfig, StrategyConfig
from sentinel_quant.data.live import Candle
from sentinel_quant.evaluation.metrics import summarize
from sentinel_quant.evaluation.report import (
    EvaluationError,
    daily_returns,
    evaluate_run,
)
from sentinel_quant.evaluation.statistics import sharpe
from sentinel_quant.registry.store import Registry, RunRecord
from sentinel_quant.risk.engine import RiskEngine
from sentinel_quant.risk.kill_switch import KillSwitch
from sentinel_quant.strategies.base import SizedStrategy
from sentinel_quant.strategies.donchian import DonchianBreakout

G3_MIN_SHARPE_RETAINED = 0.5
G4_MIN_POSITIVE_WINDOWS = 0.6
G5_MIN_POSITIVE_NEIGHBOURS = 0.7
G5_MIN_POSITIVE_YEARS = 0.5
G5_COST_STRESS = 2.0
_DAY_MS = 86_400_000
_YEAR_MS = 365 * _DAY_MS

Candles = Mapping[str, Sequence[Candle]]
Status = Literal["PASS", "FAIL", "NOT_RUN", "NOT_ASSESSED"]
Runner = Callable[[Candles, StrategyConfig, CostModel, str], BacktestResult]


@dataclass(frozen=True)
class GateResult:
    gate: str
    status: Status
    detail: str


@dataclass(frozen=True)
class WindowResult:
    test_start_ms: int
    test_end_ms: int
    chosen: StrategyConfig
    net_return_pct: float


@dataclass(frozen=True)
class ValidationReport:
    gates: tuple[GateResult, ...]
    windows: tuple[WindowResult, ...]
    base_run_id: int
    text: str


def split_holdout(
    candles: Candles, holdout_ms: int
) -> tuple[dict[str, list[Candle]], dict[str, list[Candle]]]:
    """(development, holdout). A bar belongs to the holdout if it closes after the start."""
    development: dict[str, list[Candle]] = {}
    holdout: dict[str, list[Candle]] = {}
    for symbol, bars in candles.items():
        development[symbol] = [b for b in bars if b.open_time_ms < holdout_ms]
        holdout[symbol] = [b for b in bars if b.open_time_ms >= holdout_ms]
    return development, holdout


def slice_bars(candles: Candles, start_ms: int, end_ms: int) -> dict[str, list[Candle]]:
    return {s: [b for b in v if start_ms <= b.open_time_ms < end_ms] for s, v in candles.items()}


def rolling_windows(
    start_ms: int, end_ms: int, train_days: int, test_days: int
) -> list[tuple[int, int, int]]:
    """(train start, test start, test end), stepping forward by one test period."""
    windows = []
    train_ms, test_ms = train_days * _DAY_MS, test_days * _DAY_MS
    cursor = start_ms
    while cursor + train_ms + test_ms <= end_ms:
        windows.append((cursor, cursor + train_ms, cursor + train_ms + test_ms))
        cursor += test_ms
    return windows


def parameter_grid(base: StrategyConfig) -> list[StrategyConfig]:
    """Candidates for the walk-forward re-fit."""
    return [
        base.model_copy(update={"entry_lookback": entry, "exit_lookback": exit_})
        for entry in sorted({max(int(base.entry_lookback * f), 2) for f in (0.6, 1.0, 1.4)})
        for exit_ in sorted({max(int(base.exit_lookback * f), 2) for f in (0.5, 1.0, 1.5)})
    ]


def neighbours(base: StrategyConfig) -> list[StrategyConfig]:
    """One parameter moved at a time, either way: a real edge should not be a knife edge."""
    changes: list[dict[str, float]] = [
        {"entry_lookback": max(round(base.entry_lookback * f), 2)} for f in (0.8, 1.2)
    ]
    changes += [{"exit_lookback": max(round(base.exit_lookback * f), 2)} for f in (0.8, 1.2)]
    changes += [{"atr_stop_multiple": base.atr_stop_multiple * f} for f in (0.75, 1.25)]
    return [base.model_copy(update=c) for c in changes]


def _net_return_pct(curve: Sequence[EquityPoint], start_ms: int, end_ms: int) -> float:
    inside = [p for p in curve if start_ms < p.time_ms <= end_ms]
    before = [p.equity for p in curve if p.time_ms <= start_ms]
    if not inside:
        return 0.0
    opening = before[-1] if before else inside[0].equity
    return 100 * (inside[-1].equity / opening - 1)


def _train_score(result: BacktestResult) -> float:
    _, returns = daily_returns([(p.time_ms, p.equity) for p in result.equity_curve])
    return sharpe(returns) if len(returns) > 2 else float("-inf")


def walk_forward(
    candles: Candles,
    base: StrategyConfig,
    costs: CostModel,
    runner: Runner,
    windows: Sequence[tuple[int, int, int]],
) -> list[WindowResult]:
    """Choose parameters on each training period, then score them only on what follows."""
    results = []
    for index, (train_start, test_start, test_end) in enumerate(windows):
        train = slice_bars(candles, train_start, test_start)
        scored = [
            (_train_score(runner(train, params, costs, f"window-{index}-train")), position, params)
            for position, params in enumerate(parameter_grid(base))
        ]
        chosen = max(scored, key=lambda item: (item[0], -item[1]))[2]
        # The training bars warm the strategy up, but only the test period is measured.
        result = runner(
            slice_bars(candles, train_start, test_end), chosen, costs, f"window-{index}-test"
        )
        change = _net_return_pct(result.equity_curve, test_start, test_end)
        results.append(WindowResult(test_start, test_end, chosen, change))
    return results


def year_returns(curve: Sequence[EquityPoint]) -> dict[int, float]:
    """Net return per calendar year, so one lucky period cannot carry the result."""
    closes: dict[int, float] = {}
    for point in curve:
        closes[datetime.fromtimestamp((point.time_ms - 1) / 1000, tz=UTC).year] = point.equity
    years = sorted(closes)
    results: dict[int, float] = {}
    previous = curve[0].equity if curve else 0.0
    for year in years:
        results[year] = 100 * (closes[year] / previous - 1)
        previous = closes[year]
    return results


def gate_g2(result: BacktestResult) -> GateResult:
    summary = summarize(result)
    if summary.trades == 0:
        return GateResult("G2 In-sample", "FAIL", "no trades")
    expectancy = sum(t.net_pnl for t in result.trades) / summary.trades
    ok = summary.net_pnl > 0 and expectancy > 0
    detail = f"net P&L {summary.net_pnl:.2f}, expectancy per trade {expectancy:.2f}"
    return GateResult("G2 In-sample", "PASS" if ok else "FAIL", detail)


def gate_g3(
    holdout_sharpe: float | None, development_sharpe: float, earlier_uses: int
) -> GateResult:
    name = "G3 Out-of-sample"
    if holdout_sharpe is None:
        return GateResult(name, "NOT_RUN", "holdout kept unseen (--open-holdout spends it)")
    if earlier_uses > 0:
        detail = f"holdout already seen in {earlier_uses} earlier runs, so it is not out of sample"
        return GateResult(name, "NOT_ASSESSED", detail)
    required = max(development_sharpe, 0.0) * G3_MIN_SHARPE_RETAINED
    ok = holdout_sharpe > 0 and holdout_sharpe >= required
    detail = f"holdout Sharpe {holdout_sharpe:.2f}, development {development_sharpe:.2f}"
    return GateResult(name, "PASS" if ok else "FAIL", detail)


def gate_g4(windows: Sequence[WindowResult]) -> GateResult:
    name = "G4 Walk-forward"
    if not windows:
        return GateResult(name, "NOT_ASSESSED", "history too short for one window")
    positive = sum(w.net_return_pct > 0 for w in windows) / len(windows)
    total = 100 * (float(np.prod([1 + w.net_return_pct / 100 for w in windows])) - 1)
    ok = positive >= G4_MIN_POSITIVE_WINDOWS and total > 0
    detail = f"{positive:.0%} of {len(windows)} windows positive, stitched {total:.2f}%"
    return GateResult(name, "PASS" if ok else "FAIL", detail)


def gate_g5(
    neighbour_net: Sequence[float], stressed_net: float, years: Mapping[int, float]
) -> GateResult:
    positive = sum(n > 0 for n in neighbour_net) / len(neighbour_net) if neighbour_net else 0.0
    good_years = sum(v > 0 for v in years.values()) / len(years) if years else 0.0
    ok = (
        positive >= G5_MIN_POSITIVE_NEIGHBOURS
        and stressed_net > 0
        and good_years >= G5_MIN_POSITIVE_YEARS
    )
    detail = (
        f"{positive:.0%} of neighbours positive, net at x{G5_COST_STRESS:g} costs "
        f"{stressed_net:.2f}, {good_years:.0%} of years positive"
    )
    return GateResult("G5 Robustness", "PASS" if ok else "FAIL", detail)


def run_strategy(
    cfg: AppConfig,
    candles: Candles,
    costs: CostModel,
    params: StrategyConfig,
    dataset_ids: Sequence[str],
) -> BacktestResult:
    """A backtest through the real risk engine, with a switch private to research.

    The operator's kill switch must not silently turn a research run into one with no trades.
    """
    risk = RiskEngine(cfg.daily_controls, KillSwitch(f"{cfg.kill_switch_path}.backtest"))
    strategy = SizedStrategy(DonchianBreakout(params), risk)
    return run_backtest(candles, strategy, risk, costs, cfg.backtest.initial_cash, dataset_ids)


def record_run(
    registry: Registry,
    cfg: AppConfig,
    result: BacktestResult,
    params: StrategyConfig,
    costs: CostModel,
    dataset_ids: Sequence[str],
    scope: str,
    holdout_used: bool = False,
) -> RunRecord:
    return registry.record(
        params.name,
        dataset_ids,
        {
            "strategy": params.model_dump(),
            "daily_controls": cfg.daily_controls.model_dump(),
            "costs": {"fee_bps": costs.fee_bps, "slippage_bps": costs.slippage_bps},
            "initial_cash": cfg.backtest.initial_cash,
            "scope": scope,
            "holdout_used": holdout_used,
        },
        asdict(summarize(result)),
        equity=[(p.time_ms, p.equity) for p in result.equity_curve],
    )


def holdout_uses(registry: Registry, strategy_id: str) -> int:
    """Runs that saw the holdout. A run with no record of it is assumed to have seen it."""
    return sum(bool(r.config.get("holdout_used", True)) for r in registry.runs(strategy_id))


def _annual_sharpe(result: BacktestResult) -> float:
    _, returns = daily_returns([(p.time_ms, p.equity) for p in result.equity_curve])
    return sharpe(returns) * float(np.sqrt(365)) if len(returns) > 2 else 0.0


def validate_strategy(
    cfg: AppConfig,
    candles: Candles,
    dataset_ids: Sequence[str],
    registry: Registry,
    holdout_ms: int,
    open_holdout: bool = False,
) -> ValidationReport:
    development, _ = split_holdout(candles, holdout_ms)
    base = cfg.strategy
    costs = CostModel.from_config(cfg.backtest)
    earlier_uses = holdout_uses(registry, base.name)

    def runner(
        data: Candles, params: StrategyConfig, run_costs: CostModel, scope: str
    ) -> BacktestResult:
        result = run_strategy(cfg, data, run_costs, params, dataset_ids)
        record_run(registry, cfg, result, params, run_costs, dataset_ids, scope)
        return result

    base_result = run_strategy(cfg, development, costs, base, dataset_ids)
    base_run = record_run(registry, cfg, base_result, base, costs, dataset_ids, "development")
    variants = [runner(development, n, costs, "development") for n in neighbours(base)]
    stressed = runner(development, base, costs.stressed(G5_COST_STRESS), "development")

    times = [b.open_time_ms for bars in development.values() for b in bars]
    windows = rolling_windows(
        min(times), max(times), cfg.validation.train_days, cfg.validation.test_days
    )
    walked = walk_forward(development, base, costs, runner, windows)

    holdout_sharpe = None
    if open_holdout:
        result = run_strategy(cfg, candles, costs, base, dataset_ids)
        record_run(
            registry, cfg, result, base, costs, dataset_ids, "holdout-open", holdout_used=True
        )
        curve = [(p.time_ms, p.equity) for p in result.equity_curve if p.time_ms > holdout_ms]
        _, returns = daily_returns(curve)
        holdout_sharpe = sharpe(returns) * float(np.sqrt(365)) if len(returns) > 2 else 0.0

    try:
        evaluation = evaluate_run(registry, base_run.id)
        g6 = GateResult("G6 Statistics", evaluation.g6, evaluation.g6_reason)
    except EvaluationError as exc:
        g6 = GateResult("G6 Statistics", "NOT_ASSESSED", str(exc))

    years = year_returns(base_result.equity_curve)
    gates = (
        GateResult("G1 Definition", "NOT_ASSESSED", "manual: rules, data spec, Sharia, evidence"),
        gate_g2(base_result),
        gate_g3(holdout_sharpe, _annual_sharpe(base_result), earlier_uses),
        gate_g4(walked),
        gate_g5(
            [summarize(v).net_pnl for v in variants],
            summarize(stressed).net_pnl,
            years,
        ),
        g6,
        GateResult("G7 Paper", "NOT_ASSESSED", "needs a paper-trading period"),
        GateResult("G8 Approval", "NOT_ASSESSED", "your explicit decision, never automatic"),
    )
    text = _render(base, gates, walked, years, base_run, registry)
    return ValidationReport(gates, tuple(walked), base_run.id, text)


def _day(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).strftime("%Y-%m-%d")


def _render(
    base: StrategyConfig,
    gates: Sequence[GateResult],
    windows: Sequence[WindowResult],
    years: Mapping[int, float],
    run: RunRecord,
    registry: Registry,
) -> str:
    failed = [g.gate for g in gates if g.status == "FAIL"]
    headline = f"FAILED: {', '.join(failed)}" if failed else "No automated gate failed"
    lines = [
        f"# Validation of {base.name} (base run {run.id})",
        "",
        f"**{headline}.** This report never approves a strategy: G1, G7 and G8 are not automated.",
        "",
        "| Gate | Status | Detail |",
        "|---|---|---|",
    ]
    lines += [f"| {g.gate} | {g.status} | {g.detail} |" for g in gates]
    lines += ["", "## Walk-forward windows (out of sample)"]
    lines += [
        f"- {_day(w.test_start_ms)} to {_day(w.test_end_ms)}: {w.net_return_pct:+.2f}%, "
        f"entry {w.chosen.entry_lookback}, exit {w.chosen.exit_lookback}"
        for w in windows
    ] or ["- none"]
    lines += ["", "## Net return by year"]
    lines += [f"- {year}: {value:+.2f}%" for year, value in years.items()]
    mean = fmean(years.values()) if years else 0.0
    lines += [f"- mean {mean:+.2f}%", "", f"Trials now counted: {registry.trials(base.name)}."]
    return "\n".join(lines) + "\n"

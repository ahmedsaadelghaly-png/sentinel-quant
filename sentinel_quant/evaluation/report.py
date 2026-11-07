"""Evaluation report for one registry run, including the G6 verdict.

The G6 thresholds are constants on purpose: MASTER_PLAN §6 fixes them before testing, so
they must not be something a config edit can loosen after seeing a result. Changing them
takes a code change and an ADR.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

import numpy as np

from sentinel_quant.evaluation.statistics import (
    Floats,
    Interval,
    bootstrap_sharpe_interval,
    deflated_sharpe,
    kurtosis,
    probabilistic_sharpe,
    probability_of_overfitting,
    sharpe,
    skewness,
)
from sentinel_quant.registry.store import Registry, RunRecord

G6_MIN_DEFLATED_SHARPE = 0.95
G6_MAX_PBO = 0.25
MIN_TRIALS_FOR_PBO = 4
MIN_DAYS = 30
BOOTSTRAP_SEED = 20261106
_DAYS_PER_YEAR = 365  # crypto trades every day
_DAY_MS = 86_400_000


class EvaluationError(ValueError):
    """The run cannot be evaluated."""


@dataclass(frozen=True)
class Evaluation:
    run: RunRecord
    days: int
    cagr_pct: float
    annual_sharpe: float
    annual_sortino: float | None
    calmar: float | None
    max_drawdown_pct: float
    worst_day_pct: float
    var_95_pct: float
    cvar_95_pct: float
    skew: float
    kurt: float
    trials: int
    probabilistic_sharpe: float
    deflated_sharpe: float
    annual_sharpe_interval: Interval
    pbo: float | None
    g6: Literal["PASS", "FAIL", "NOT_ASSESSED"]
    g6_reason: str
    text: str


def daily_returns(equity: list[tuple[int, float]]) -> tuple[list[int], Floats]:
    """Close-of-day equity to daily returns. Daily, so autocorrelated bars don't inflate n."""
    closes: dict[int, float] = {}
    for time_ms, value in equity:
        closes[(time_ms - 1) // _DAY_MS] = value  # a bar closing at midnight ends that day
    days = sorted(closes)
    values = np.array([closes[d] for d in days], dtype=np.float64)
    return days[1:], values[1:] / values[:-1] - 1


def _max_drawdown_pct(returns: Floats) -> float:
    curve = np.cumprod(1 + returns)
    peaks = np.maximum.accumulate(np.concatenate(([1.0], curve)))[1:]
    return float(100 * np.max(1 - curve / peaks))


def _sharpe_variance(registry: Registry, run: RunRecord, observations: int) -> tuple[int, float]:
    """Trials count and the variance of their Sharpe ratios.

    Never below the sampling variance of a Sharpe estimate: with few trials the sample
    variance can be tiny, which would understate the luck benchmark.
    """
    others = registry.runs(run.strategy_id)
    estimates = []
    for other in others:
        curve = registry.equity(other.id)
        if curve:
            _, returns = daily_returns(curve)
            if len(returns) > 2:
                estimates.append(sharpe(returns))
    sampling = 1 / max(observations - 1, 1)
    sample = float(np.var(estimates, ddof=1)) if len(estimates) > 1 else 0.0
    return len(others), max(sample, sampling)


def _pbo(registry: Registry, run: RunRecord) -> float | None:
    """PBO across trials on the same data, aligned on the days they all cover."""
    series: list[dict[int, float]] = []
    for other in registry.runs(run.strategy_id):
        curve = registry.equity(other.id)
        same_scope = other.config.get("scope") == run.config.get("scope")
        if curve and other.dataset_ids == run.dataset_ids and same_scope:
            days, returns = daily_returns(curve)
            series.append(dict(zip(days, returns.tolist(), strict=True)))
    if len(series) < MIN_TRIALS_FOR_PBO:
        return None
    shared = sorted(set.intersection(*(set(s) for s in series)))
    matrix = np.array([[s[d] for s in series] for d in shared], dtype=np.float64)
    return probability_of_overfitting(matrix)


def _verdict(
    deflated: float, pbo: float | None, trials: int
) -> tuple[Literal["PASS", "FAIL", "NOT_ASSESSED"], str]:
    if deflated < G6_MIN_DEFLATED_SHARPE:
        return "FAIL", f"deflated Sharpe {deflated:.3f} is below {G6_MIN_DEFLATED_SHARPE}"
    if pbo is None:
        return "NOT_ASSESSED", f"PBO needs {MIN_TRIALS_FOR_PBO} trials on the same data ({trials})"
    if pbo > G6_MAX_PBO:
        return "FAIL", f"PBO {pbo:.3f} is above {G6_MAX_PBO}"
    return "PASS", f"deflated Sharpe {deflated:.3f}, PBO {pbo:.3f}"


def _number(value: float | None, digits: int = 2) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def evaluate_run(registry: Registry, run_id: int) -> Evaluation:
    run = next((r for r in registry.runs() if r.id == run_id), None)
    if run is None:
        raise EvaluationError(f"no run {run_id} in the registry")
    curve = registry.equity(run_id)
    if not curve:
        raise EvaluationError(f"run {run_id} has no stored equity curve")
    _, returns = daily_returns(curve)
    days = len(returns)
    if days < MIN_DAYS:
        raise EvaluationError(f"run {run_id} covers {days} days, need {MIN_DAYS}")

    root_year = math.sqrt(_DAYS_PER_YEAR)
    observed = sharpe(returns)
    skew, kurt = skewness(returns), kurtosis(returns)
    trials, variance = _sharpe_variance(registry, run, days)
    psr = probabilistic_sharpe(observed, 0.0, days, skew, kurt)
    dsr = deflated_sharpe(observed, days, skew, kurt, trials, variance)
    pbo = _pbo(registry, run)
    interval = bootstrap_sharpe_interval(returns, BOOTSTRAP_SEED)
    annual_interval = Interval(interval.low * root_year, interval.high * root_year)

    growth = float(np.prod(1 + returns))
    cagr = 100 * (growth ** (_DAYS_PER_YEAR / days) - 1)
    drawdown = _max_drawdown_pct(returns)
    downside = float(np.sqrt(np.mean(np.minimum(returns, 0.0) ** 2)))
    sortino = float(np.mean(returns)) / downside * root_year if downside > 0 else None
    calmar = cagr / drawdown if drawdown > 0 else None
    var_95 = float(np.quantile(returns, 0.05))
    tail = returns[returns <= var_95]
    verdict, reason = _verdict(dsr, pbo, trials)

    created = datetime.fromisoformat(run.created_at).astimezone(UTC)
    metrics = run.metrics
    lines = [
        f"# Evaluation of run {run.id}: {run.strategy_id}, trial {run.trial_number}",
        "",
        f"**G6 verdict: {verdict}.** {reason}.",
        "",
        "G6 is one gate of eight. A pass would not make this strategy safe to trade.",
        "This is one in-sample backtest: G3 to G5 need out-of-sample, walk-forward and",
        "robustness work that this report does not do.",
        "",
        "## Provenance",
        f"- Recorded {created:%Y-%m-%d %H:%M} UTC, code {run.code_hash[:12]}",
        f"- Datasets: {', '.join(run.dataset_ids)}",
        f"- Costs: {run.config.get('costs')}",
        f"- Trials counted for this strategy: {trials}",
        "",
        "## Performance (net of costs)",
        f"- CAGR {cagr:.2f}%, over {days} days",
        f"- Sharpe {observed * root_year:.2f}, 95% interval "
        f"{annual_interval.low:.2f} to {annual_interval.high:.2f}",
        f"- Sortino {_number(sortino)}, Calmar {_number(calmar)}",
        f"- Max drawdown {drawdown:.2f}%",
        f"- Net P&L {_number(metrics.get('net_pnl'))}, gross {_number(metrics.get('gross_pnl'))}",
        f"- Trades {metrics.get('trades')}, win rate {_number(metrics.get('win_rate_pct'))}%,"
        f" profit factor {_number(metrics.get('profit_factor'))}",
        "",
        "## Tail risk (daily)",
        f"- Worst day {100 * float(returns.min()):.2f}%",
        f"- 5% VaR {100 * var_95:.2f}%, 5% CVaR {100 * float(tail.mean()):.2f}%",
        f"- Skew {skew:.2f}, kurtosis {kurt:.2f}",
        "",
        "## Is it luck?",
        f"- Probabilistic Sharpe (true Sharpe above 0): {psr:.3f}",
        f"- Deflated Sharpe (above the luck of {trials} trials): {dsr:.3f}, "
        f"needs {G6_MIN_DEFLATED_SHARPE}",
        f"- PBO: {_number(pbo, 3)}, needs {G6_MAX_PBO} or less",
    ]
    return Evaluation(
        run=run,
        days=days,
        cagr_pct=cagr,
        annual_sharpe=observed * root_year,
        annual_sortino=sortino,
        calmar=calmar,
        max_drawdown_pct=drawdown,
        worst_day_pct=100 * float(returns.min()),
        var_95_pct=100 * var_95,
        cvar_95_pct=100 * float(tail.mean()),
        skew=skew,
        kurt=kurt,
        trials=trials,
        probabilistic_sharpe=psr,
        deflated_sharpe=dsr,
        annual_sharpe_interval=annual_interval,
        pbo=pbo,
        g6=verdict,
        g6_reason=reason,
        text="\n".join(lines) + "\n",
    )
